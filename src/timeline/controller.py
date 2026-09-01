"""Pure playback controller with no Qt dependencies."""

from __future__ import annotations

import time

PLAYBACK_SPEEDS: tuple[float, ...] = (0.25, 0.5, 1.0, 1.5, 2.0)
DEFAULT_PLAYBACK_SPEED: float = 1.0


class PlaybackController:
    """Manages play state, speed, looping, and in/out work range."""

    def __init__(self, max_frame: int) -> None:
        self.is_playing: bool = False
        self.is_looping: bool = True
        self.playback_speed: float = DEFAULT_PLAYBACK_SPEED
        self.in_point: int = 0
        self.out_point: int = max(0, max_frame)
        self._max_frame: int = max(0, max_frame)
        self._playback_accumulator_frames: float = 0.0
        self._last_tick_time: float | None = None

    def set_max_frame(self, max_frame: int) -> None:
        """Update timeline length and clamp markers."""
        self._max_frame = max(0, max_frame)
        self.in_point = min(self.in_point, self._max_frame)
        self.out_point = max(self.in_point, min(self.out_point, self._max_frame))

    @property
    def max_frame(self) -> int:
        return self._max_frame

    def timer_interval_ms(self, fps: float) -> int:
        """Return a responsive Qt timer interval for playback scheduling."""
        target_fps = max(fps, 0.001) * self.playback_speed
        return max(1, int(1000 / max(target_fps * 2.0, 1.0)))

    def set_in_point(self, frame: int) -> None:
        self.in_point = max(0, min(frame, self.out_point))

    def set_out_point(self, frame: int) -> None:
        self.out_point = max(self.in_point, min(frame, self._max_frame))

    def clear_range(self) -> None:
        self.in_point = 0
        self.out_point = self._max_frame

    def start_clock(self) -> None:
        self._playback_accumulator_frames = 0.0
        self._last_tick_time = time.monotonic()

    def stop_clock(self) -> None:
        self._playback_accumulator_frames = 0.0
        self._last_tick_time = None

    def frames_to_advance(self, fps: float) -> int:
        """Return how many frames playback should advance on this tick."""
        now = time.monotonic()
        if self._last_tick_time is None:
            self._last_tick_time = now
            return 1
        elapsed = max(0.0, now - self._last_tick_time)
        self._last_tick_time = now
        self._playback_accumulator_frames += elapsed * max(fps, 0.001) * self.playback_speed
        frames = int(self._playback_accumulator_frames)
        if frames <= 0:
            return 0
        self._playback_accumulator_frames -= frames
        return min(frames, 4)

    def next_frame(self, current_frame: int) -> int | None:
        """Compute the next frame index, or None if playback should stop."""
        end = self.out_point if self.out_point > self.in_point else self._max_frame
        nxt = current_frame + 1
        if nxt <= end:
            return nxt
        if self.is_looping:
            return self.in_point
        return None

    def format_timecode(self, frame_num: int, fps: float) -> str:
        """Format a frame number as HH:MM:SS:FF."""
        fps_i = max(1, int(fps))
        total_seconds = frame_num // fps_i
        frames = frame_num % fps_i
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
