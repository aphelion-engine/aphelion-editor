"""Master timeline clock for interactive playback.

The clock, not the renderer, decides which frame belongs on screen. A
renderer that falls behind therefore *skips* rather than slowing the
timeline down — which is the difference between a stuttering editor and one
that quietly drops frames the user never needed to see.

Two sources are supported:

``FREE_RUNNING``
    Monotonic wall-clock time multiplied by the playback rate. Used when
    there is no audio, or when audio is disabled.

``AUDIO_MASTER``
    The audio device's consumed-sample count, which is the only clock that
    is actually synchronised to what the user *hears*. Video follows it.
    Corrections are slew-limited: a large discontinuity (a real seek) jumps,
    a small one (scheduling jitter) is absorbed gradually so the picture
    never visibly snaps.

All public methods take an explicit ``now`` value (seconds from
``time.monotonic``) rather than reading the clock themselves, which makes
the whole module deterministic under test.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["ClockSource", "MediaClock"]


class ClockSource(IntEnum):
    """Which signal drives the timeline position."""

    FREE_RUNNING = 0
    AUDIO_MASTER = 1


#: Corrections smaller than this are absorbed gradually (seconds).
_SLEW_THRESHOLD_SEC: float = 0.030
#: Fraction of the drift corrected per resync while inside the slew window.
_SLEW_RATE: float = 0.10
#: Drift beyond this is treated as a real seek and applied immediately.
_JUMP_THRESHOLD_SEC: float = 0.250


class MediaClock:
    """Maps wall-clock/audio progress onto a timeline frame position.

    Parameters:
        fps: Timeline frame rate.
        source: Initial clock source.

    Example::

        clock = MediaClock(fps=30.0, source=ClockSource.FREE_RUNNING)
        clock.start(frame=120, now=time.monotonic())
        ...
        target = clock.frame_at(time.monotonic())   # what to show now
    """

    __slots__ = (
        "_fps",
        "_source",
        "_running",
        "_speed",
        "_anchor_frame",
        "_anchor_time",
        "_audio_offset",
        "_last_audio_seconds",
        "_resyncs",
        "_max_drift",
    )

    def __init__(
        self,
        fps: float = 30.0,
        source: ClockSource = ClockSource.FREE_RUNNING,
    ) -> None:
        self._fps = max(0.001, float(fps))
        self._source = ClockSource(source)
        self._running = False
        self._speed = 1.0
        self._anchor_frame = 0
        self._anchor_time = 0.0
        #: Difference between the wall clock and the audio clock, applied to
        #: translate audio progress into timeline seconds.
        self._audio_offset = 0.0
        self._last_audio_seconds = 0.0
        self._resyncs = 0
        self._max_drift = 0.0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def fps(self) -> float:
        """Timeline frame rate."""
        return self._fps

    def set_fps(self, fps: float) -> None:
        """Update the frame rate without disturbing the running position."""
        self._fps = max(0.001, float(fps))

    @property
    def source(self) -> ClockSource:
        """Active clock source."""
        return self._source

    def set_source(self, source: ClockSource) -> None:
        """Switch clock source; the next resync re-anchors."""
        self._source = ClockSource(source)

    @property
    def speed(self) -> float:
        """Playback rate multiplier."""
        return self._speed

    def set_speed(self, speed: float) -> None:
        """Set the playback rate (negative values are not yet supported)."""
        self._speed = max(0.001, float(speed))

    @property
    def running(self) -> bool:
        """Whether the clock is advancing."""
        return self._running

    @property
    def frame_budget_seconds(self) -> float:
        """Seconds available per frame at the current rate."""
        return 1.0 / max(0.001, self._fps * self._speed)

    @property
    def frame_budget_ms(self) -> float:
        """Milliseconds available per frame at the current rate."""
        return self.frame_budget_seconds * 1000.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, frame: int, now: float) -> None:
        """Anchor the clock at ``frame`` and begin advancing."""
        self._anchor_frame = int(frame)
        self._anchor_time = float(now)
        self._audio_offset = 0.0
        self._last_audio_seconds = 0.0
        self._running = True

    def stop(self) -> None:
        """Freeze the clock (the position is retained)."""
        self._running = False

    def seek(self, frame: int, now: float) -> None:
        """Jump the clock to ``frame``; a real discontinuity."""
        self._anchor_frame = int(frame)
        self._anchor_time = float(now)
        self._audio_offset = 0.0
        self._last_audio_seconds = 0.0

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------

    def position_frames(self, now: float) -> float:
        """Return the exact (fractional) timeline frame position."""
        if not self._running:
            return float(self._anchor_frame)

        elapsed = self._elapsed_seconds(now)
        return self._anchor_frame + elapsed * self._fps * self._speed

    def _elapsed_seconds(self, now: float) -> float:
        """Return timeline seconds elapsed since the anchor."""
        if self._source is ClockSource.AUDIO_MASTER and self._last_audio_seconds > 0.0:
            # Audio progress plus any accumulated correction offset.
            return max(0.0, self._last_audio_seconds + self._audio_offset)
        return max(0.0, float(now) - self._anchor_time)

    def frame_at(self, now: float) -> int:
        """Return the integer frame that should be visible at ``now``."""
        return int(self.position_frames(now))

    def due_time(self, frame: int) -> float:
        """Return the monotonic time at which ``frame`` should be presented.

        This is the deadline a renderer is racing. It is derived from the
        anchor, never from how long rendering actually took, so a slow frame
        cannot push later deadlines further away.
        """
        rate = self._fps * self._speed
        if rate <= 0.0:
            return self._anchor_time
        return self._anchor_time + (float(frame) - self._anchor_frame) / rate

    def lateness_seconds(self, frame: int, now: float) -> float:
        """Return how late ``frame`` already is (negative when early)."""
        return float(now) - self.due_time(frame)

    def frames_ahead(self, now: float) -> float:
        """Return how many frames of slack exist before the next deadline."""
        return self.position_frames(now) - int(self.position_frames(now))

    # ------------------------------------------------------------------
    # Audio mastering
    # ------------------------------------------------------------------

    def resync_to_audio(self, presented_seconds: float) -> float:
        """Align the clock to audio progress; returns the applied correction.

        Parameters:
            presented_seconds: Timeline seconds already presented by the
                audio device.

        Returns:
            The correction applied this call, in seconds. Small values are
            smoothed across subsequent frames; large values jump.
        """
        if self._source is not ClockSource.AUDIO_MASTER:
            self._last_audio_seconds = presented_seconds
            return 0.0

        if self._last_audio_seconds <= 0.0:
            # First sample: adopt it without correction.
            self._last_audio_seconds = presented_seconds
            return 0.0

        wall_seconds = self._last_audio_seconds + self._audio_offset
        drift = presented_seconds - wall_seconds

        if abs(drift) >= _JUMP_THRESHOLD_SEC:
            applied = drift
        else:
            applied = drift * _SLEW_RATE

        self._audio_offset += applied
        self._last_audio_seconds = presented_seconds
        self._resyncs += 1

        absolute = abs(drift)
        if absolute > self._max_drift:
            self._max_drift = absolute

        return applied

    def drift_seconds(self) -> float:
        """Return the largest observed audio/video drift, in seconds."""
        return self._max_drift

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def resync_count(self) -> int:
        """How many audio resyncs have been applied."""
        return self._resyncs

    def stats(self) -> dict[str, float | int | str]:
        """Return a snapshot for the overlay and traces."""
        return {
            "source": self._source.name,
            "running": int(self._running),
            "fps": round(self._fps, 3),
            "speed": round(self._speed, 3),
            "budget_ms": round(self.frame_budget_ms, 3),
            "resyncs": self._resyncs,
            "max_drift_ms": round(self._max_drift * 1000.0, 3),
        }

    def reset(self) -> None:
        """Clear drift statistics (does not change the position)."""
        self._resyncs = 0
        self._max_drift = 0.0
