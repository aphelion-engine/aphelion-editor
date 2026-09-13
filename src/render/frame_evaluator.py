"""Background frame evaluation with generation-guarded latest-wins delivery.

The worker exists to answer one question well: *which frame should the
viewport be showing right now?* Everything else is secondary.

Design goals
------------
* **Latest request always wins.** Requests carry a monotonic id; a result
  whose id is no longer current is never presented while paused/scrubbing.
* **Stale frames are worthless.** Results carry the project *generation*
  they were produced for. Switching projects, seeking, or scrubbing all
  bump the generation, so a slow job from the old state can never paint
  over the new one.
* **Adaptive dropping.** While playing, if measured frame cost exceeds the
  playback budget the worker stops emitting late frames and races ahead to
  the frame the clock actually wants. Export never uses this path.
* **Prefetch must earn its keep.** Prefetched frames that are later
  requested count as hits; frames discarded by a seek/scrub count as
  wasted. The ratio is exposed for the overlay and benchmarks.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import numpy as np
from config.constants import DEFAULT_MAX_PREFETCH_FRAMES
from core.audio import FrameWithAudio
from core.perf.frame_drop import FrameDropMode, FrameDropPolicy
from core.perf.profiler import profiler
from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from core.project import Project


class FrameEvaluationWorker(QThread):
    """
    Background frame evaluator optimized for interactive playback.

    Design goals:
    - Latest request always wins.
    - Avoid unnecessary locking in the hot path.
    - Avoid unnecessary ndarray copies.
    - Prefetch sequentially while the UI is idle.
    - Never allow stale prefetch work to starve a newer request.
    """

    #: ``(node_id, frame_num, frame_or_none)``
    frame_ready = pyqtSignal(str, int, object)
    #: ``(node_id, frame_num)`` — emitted when work was discarded as stale.
    frame_discarded = pyqtSignal(str, int)

    def __init__(self, project: Project) -> None:
        super().__init__()

        self._project = project

        # Guards ``_pending``, ``_generation`` and the request id counter.
        # Held only for a few attribute writes on every request.
        self._request_lock = threading.Lock()

        self._pending: tuple[str, int, int, int] | None = None
        self._request_id = 0
        self._generation = 0

        # Prefetch accounting: hits are frames the user later asked for,
        # wasted are frames discarded by a seek/scrub before use.
        self._prefetched: set[int] = set()
        self._prefetch_hits = 0
        self._prefetch_wasted = 0
        self._prefetch_enabled = True
        self._prefetch_direction = 1
        self._adaptive_prefetch = True
        self._scrubbing = False

        # These are only written by the controlling/UI thread and read by
        # the worker. CPython's simple bool/int reads are atomic enough here.
        self._running = True
        self._playing = False
        self._max_prefetch = DEFAULT_MAX_PREFETCH_FRAMES

        self._drop_policy = FrameDropPolicy(FrameDropMode.ADAPTIVE, 30.0)
        self._stale_discarded = 0
        self._frames_presented = 0
        self._drop_events = 0

        # Written by the worker, read by the UI thread for adaptive quality.
        self.last_render_seconds = 0.0
        self.last_evaluated_frame = -1

        self._wake = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_max_prefetch(self, frame_count: int) -> None:
        """Set the maximum number of frames prefetched ahead."""
        self._max_prefetch = max(0, int(frame_count))

    def set_prefetch_enabled(self, enabled: bool) -> None:
        """Enable or disable speculative prefetch entirely."""
        self._prefetch_enabled = bool(enabled)
        if not enabled:
            self.clear_prefetch_tracking()

    def set_adaptive_prefetch(self, enabled: bool) -> None:
        """Allow prefetch to be suppressed during scrubs/random access."""
        self._adaptive_prefetch = bool(enabled)

    def set_scrubbing(self, scrubbing: bool) -> None:
        """Tell the worker the user is dragging the timeline.

        While scrubbing, prefetch is pointless: the next request invalidates
        it almost immediately. Suppressing it keeps decode capacity on the
        frame under the playhead.
        """
        was_scrubbing = self._scrubbing
        self._scrubbing = bool(scrubbing)
        if scrubbing and not was_scrubbing:
            self.clear_prefetch_tracking(wasted=True)
        elif not scrubbing:
            self._wake.set()

    def set_playback_direction(self, direction: int) -> None:
        """Set the prefetch direction (``1`` forward, ``-1`` reverse)."""
        self._prefetch_direction = -1 if int(direction) < 0 else 1

    def set_drop_mode(self, mode: FrameDropMode | str) -> None:
        """Apply the configured frame-dropping mode."""
        if isinstance(mode, str):
            mode = FrameDropMode.from_name(mode)
        self._drop_policy.set_mode(mode)

    def set_target_fps(self, fps: float) -> None:
        """Update the playback budget used by the dropping policy."""
        self._drop_policy.set_target_fps(fps)

    def request_frame(self, node_id: str, frame_num: int) -> None:
        """
        Request a frame.

        Latest-wins semantics mean that if the worker is busy, only the
        newest request matters.
        """
        with self._request_lock:
            self._request_id += 1
            self._pending = (
                node_id,
                int(frame_num),
                self._request_id,
                self._generation,
            )
            requested_frame = int(frame_num)

        self._note_prefetch_use(requested_frame)
        self._wake.set()

    def invalidate(self) -> None:
        """Discard pending work after a seek, scrub, or project change.

        Bumping the generation makes every in-flight job stale, so its
        result is dropped without waiting for it to finish.
        """
        with self._request_lock:
            self._generation += 1
            self._pending = None
        self.clear_prefetch_tracking(wasted=True)
        self._wake.set()

    def set_playing(self, playing: bool) -> None:
        """Enable/disable playback prefetch."""
        self._playing = bool(playing)

        if playing:
            self._drop_policy.set_target_fps(float(self._project.fps))
            self._wake.set()
        else:
            self.clear_prefetch_tracking()

    def set_project(self, project: Project) -> None:
        """Switch the worker to a new project."""
        with self._request_lock:
            self._project = project
            self._generation += 1
            self._pending = None

        self.clear_prefetch_tracking(wasted=True)
        self._drop_policy.reset()
        self._wake.set()

    def stop(self) -> None:
        """Stop the worker and wait for the active evaluation."""
        self._running = False
        self.requestInterruption()
        self._wake.set()

        if not self.wait(2000):
            self.terminate()
            self.wait(500)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main worker loop.

        We intentionally avoid polling every 50 ms. Event-driven wakeups
        make idle playback essentially free.
        """
        while self._running and not self.isInterruptionRequested():
            request = self._take_pending()

            if request is None:
                self._wake.wait()
                self._wake.clear()
                continue

            node_id, frame_num, request_id, generation = request

            if generation != self._generation:
                self._stale_discarded += 1
                continue

            started = time.perf_counter()
            with profiler.scope("graph"):
                frame = self._evaluate(node_id, frame_num)
            elapsed = time.perf_counter() - started

            self.last_render_seconds = elapsed
            self.last_evaluated_frame = frame_num

            decision = self._drop_policy.decide(
                latency_frames=self._latency_frames(frame_num)
            )
            self._drop_policy.observe(elapsed)

            if not self._running:
                return

            superseded = (
                generation != self._generation
                or request_id != self._current_request_id()
            )

            if superseded:
                self._stale_discarded += 1
                if self._playing:
                    if decision.drop:
                        # Skip ahead: loop immediately and pick up the newest
                        # request instead of paying for a frame nobody wants.
                        self._drop_events += 1
                        continue
                else:
                    # Paused/scrubbing results must match the playhead exactly.
                    self.frame_discarded.emit(node_id, frame_num)
                    continue

            self._frames_presented += 1
            self.frame_ready.emit(node_id, frame_num, frame)

            if self._playing and self._should_prefetch():
                self._prefetch(node_id, frame_num)

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def _take_pending(self) -> tuple[str, int, int, int] | None:
        with self._request_lock:
            request = self._pending
            self._pending = None
            return request

    def _current_request_id(self) -> int:
        with self._request_lock:
            return self._request_id

    def _has_pending(self) -> bool:
        """
        Cheap latest-request check.

        This is called frequently during prefetch, so keep it tiny.
        """
        with self._request_lock:
            return self._pending is not None

    def _latency_frames(self, frame_num: int) -> float:
        """Return how many frames behind the playhead ``frame_num`` already is."""
        try:
            clock = int(self._project.current_frame)
        except Exception:  # noqa: BLE001 - project may be mid-teardown
            return 0.0
        return float(max(0, clock - frame_num))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        node_id: str,
        frame_num: int,
    ) -> np.ndarray | FrameWithAudio | None:
        """
        Evaluate one frame.

        Avoid copying arrays unless they are actually non-contiguous.
        """
        try:
            result = self._project.evaluate_node(node_id, frame_num)

        except Exception as exc:  # noqa: BLE001
            self._project.log_exception(exc)
            return None

        if isinstance(result, FrameWithAudio):
            frame = result.frame

            if isinstance(frame, np.ndarray) and not frame.flags.c_contiguous:
                frame = np.ascontiguousarray(frame)

            return FrameWithAudio(
                frame=frame,
                audio=result.audio,
            )

        if isinstance(result, np.ndarray):
            if result.flags.c_contiguous:
                return result

            return np.ascontiguousarray(result)

        return None

    # ------------------------------------------------------------------
    # Prefetch
    # ------------------------------------------------------------------

    def _prefetch(self, node_id: str, frame_num: int) -> None:
        """
        Warm frames ahead of playback in the active direction.

        Prefetch is deliberately interruptible: the instant the UI asks
        for another frame, prefetching stops.
        """
        if not self._should_prefetch():
            return

        project = self._project

        # Read settings once rather than once per frame.
        settings = project.get_preview_settings()

        count = min(
            max(0, int(settings.prefetch_frames)),
            self._max_prefetch,
        )

        if count <= 0:
            return

        direction = self._prefetch_direction
        max_frame = project.max_frame

        first = max(0, min(frame_num + direction, max_frame))
        last = max(0, min(frame_num + direction * count, max_frame))

        lo, hi = (first, last) if first <= last else (last, first)

        for next_frame in range(lo, hi + 1, 1):
            # New UI request always wins.
            if self._project is not project or self._has_pending():
                return

            # Don't waste time after shutdown or a play-state change.
            if not self._should_prefetch():
                return

            self._evaluate(node_id, next_frame)
            self._prefetched.add(next_frame)

        self._trim_prefetch_tracking()

    def _should_prefetch(self) -> bool:
        """Whether prefetch is currently worth doing at all."""
        if not self._prefetch_enabled or self._max_prefetch <= 0:
            return False
        if self._adaptive_prefetch and self._scrubbing:
            return False
        if not self._playing or not self._running or self.isInterruptionRequested():
            return False
        return True

    def _trim_prefetch_tracking(self) -> None:
        """Bound the "recently prefetched" set, counting overflow as waste."""
        limit = max(4, self._max_prefetch * 3)
        excess = len(self._prefetched) - limit
        if excess <= 0:
            return
        self._prefetch_wasted += excess
        # Sets are unordered; keeping an arbitrary subset is fine because the
        # metric only needs a ballpark hit/waste ratio.
        self._prefetched = set(list(self._prefetched)[limit:])

    def _note_prefetch_use(self, frame_num: int) -> None:
        """Record that the user actually asked for a prefetched frame."""
        if frame_num in self._prefetched:
            self._prefetched.discard(frame_num)
            self._prefetch_hits += 1

    def clear_prefetch_tracking(self, wasted: bool = False) -> None:
        """Forget prefetched frames, optionally counting them as wasted."""
        if wasted and self._prefetched:
            self._prefetch_wasted += len(self._prefetched)
        self._prefetched.clear()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, float | int | str]:
        """Return worker counters for the overlay and benchmark harness."""
        total_prefetch = self._prefetch_hits + self._prefetch_wasted
        return {
            "presented": self._frames_presented,
            "stale_discarded": self._stale_discarded,
            "dropped": self._drop_events,
            "pending": 1 if self._has_pending() else 0,
            "last_ms": round(self.last_render_seconds * 1000.0, 3),
            "smoothed_ms": round(self._drop_policy.smoothed_ms, 3),
            "drop_mode": self._drop_policy.mode.label,
            "frame_budget_ms": round(self._drop_policy.frame_budget_ms, 3),
            "prefetch_hits": self._prefetch_hits,
            "prefetch_wasted": self._prefetch_wasted,
            "prefetch_hit_ratio": round(
                (self._prefetch_hits / total_prefetch) if total_prefetch else 0.0,
                4,
            ),
        }
