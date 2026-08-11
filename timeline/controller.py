"""Pure playback controller with no Qt dependencies."""

from __future__ import annotations

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

    def set_max_frame(self, max_frame: int) -> None:
        """Update timeline length and clamp markers."""
        self._max_frame = max(0, max_frame)
        self.in_point = min(self.in_point, self._max_frame)
        self.out_point = max(self.in_point, min(self.out_point, self._max_frame))

    @property
    def max_frame(self) -> int:
        return self._max_frame

    def timer_interval_ms(self, fps: float) -> int:
        """Return Qt timer interval for the current speed."""
        return max(1, int(1000 / (max(fps, 0.001) * self.playback_speed)))

    def set_in_point(self, frame: int) -> None:
        self.in_point = max(0, min(frame, self.out_point))

    def set_out_point(self, frame: int) -> None:
        self.out_point = max(self.in_point, min(frame, self._max_frame))

    def clear_range(self) -> None:
        self.in_point = 0
        self.out_point = self._max_frame

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
