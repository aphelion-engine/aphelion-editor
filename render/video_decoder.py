"""Fast OpenCV-backed video decode for interactive preview.

Design goals:
- Sequential reads during playback (avoid brittle random seeks)
- Optional downscale at decode time (proxy) so the UI never scales 4K
- RGB uint8 output ready for QImage.Format_RGB888
- Quiet FFmpeg/OpenCV stderr noise from mid-GOP seeks
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

# Must be set before the first OpenCV/FFmpeg capture is created.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")  # AV_LOG_FATAL
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")

import cv2
import numpy as np

# Prefer sequential decode over hard seeks within this many frames.
_MAX_FORWARD_GRABS: int = 48
_SEEK_READ_RETRIES: int = 3

_CAPTURE_LOCK = threading.RLock()
_LOGGING_CONFIGURED = False


def _configure_decoder_logging() -> None:
    """Mute noisy libav/OpenCV decode warnings (mid-GOP seeks, etc.)."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True

    try:
        cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass


_configure_decoder_logging()


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Lightweight media metadata used to sync the project timeline."""

    fps: float
    duration_sec: float
    width: int
    height: int
    frame_count: int


class VideoDecoder:
    """Stateful decoder optimized for scrub + forward playback."""

    def __init__(self) -> None:
        self._capture: cv2.VideoCapture | None = None
        self._path: str | None = None
        self._fps: float = 30.0
        self._frame_count: int = 0
        self._width: int = 0
        self._height: int = 0
        self._next_index: int = 0
        self._last_rgb: np.ndarray | None = None
        self._last_index: int = -1

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def open(self, path: str) -> MediaInfo | None:
        """Open ``path`` and return media info, or ``None`` on failure."""
        with _CAPTURE_LOCK:
            if self._path == path and self.is_open:
                return self.info()

            self._close_unlocked()
            capture = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
            if not capture.isOpened():
                capture.release()
                return None

            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0.001:
                fps = 30.0
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if width <= 0 or height <= 0:
                capture.release()
                return None

            self._capture = capture
            self._path = path
            self._fps = fps
            self._frame_count = max(0, frame_count)
            self._width = width
            self._height = height
            self._next_index = 0
            self._last_rgb = None
            self._last_index = -1
            return self.info()

    def info(self) -> MediaInfo | None:
        if not self.is_open:
            return None
        duration = (
            self._frame_count / self._fps
            if self._frame_count > 0
            else 0.0
        )
        return MediaInfo(
            fps=self._fps,
            duration_sec=duration,
            width=self._width,
            height=self._height,
            frame_count=self._frame_count,
        )

    def close(self) -> None:
        with _CAPTURE_LOCK:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._path = None
        self._next_index = 0
        self._last_rgb = None
        self._last_index = -1

    def read_rgb(self, frame_num: int, max_width: int) -> np.ndarray | None:
        """Return an RGB frame at ``frame_num``, optionally proxy-scaled."""
        with _CAPTURE_LOCK:
            if not self.is_open or self._capture is None:
                return None

            target = max(0, int(frame_num))
            if self._frame_count > 0:
                target = min(target, self._frame_count - 1)

            if target == self._last_index and self._last_rgb is not None:
                return self._scale_rgb(self._last_rgb, max_width)

            if not self._position_to(target):
                return self._held_frame(max_width)

            frame = self._read_bgr_with_retry()
            if frame is None:
                # Hard seeks into H.264 often fail once; hold last good frame.
                return self._held_frame(max_width)

            self._next_index = target + 1
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._last_rgb = rgb
            self._last_index = target
            return self._scale_rgb(rgb, max_width)

    def _held_frame(self, max_width: int) -> np.ndarray | None:
        if self._last_rgb is None:
            return None
        return self._scale_rgb(self._last_rgb, max_width)

    def _read_bgr_with_retry(self) -> np.ndarray | None:
        if self._capture is None:
            return None
        for _ in range(_SEEK_READ_RETRIES):
            ok, bgr = self._capture.read()
            if ok and bgr is not None:
                return bgr
        return None

    def _position_to(self, target: int) -> bool:
        """Seek or advance so the next ``read()`` yields ``target``."""
        if self._capture is None:
            return False

        if target == self._next_index:
            return True

        forward_gap = target - self._next_index
        if 0 < forward_gap <= _MAX_FORWARD_GRABS:
            for _ in range(forward_gap):
                if not self._capture.grab():
                    return False
            self._next_index = target
            return True

        # Prefer time-based seek — slightly more stable than POS_FRAMES on H.264.
        time_ms = (target / max(self._fps, 0.001)) * 1000.0
        seeked = self._capture.set(cv2.CAP_PROP_POS_MSEC, time_ms)
        if not seeked:
            seeked = self._capture.set(cv2.CAP_PROP_POS_FRAMES, float(target))
        if not seeked:
            return False

        # After a hard seek, reported position can be a nearby keyframe.
        reported = int(self._capture.get(cv2.CAP_PROP_POS_FRAMES) or target)
        self._next_index = max(0, reported)
        if self._next_index < target:
            for _ in range(min(target - self._next_index, _MAX_FORWARD_GRABS)):
                if not self._capture.grab():
                    break
                self._next_index += 1
        return True

    @staticmethod
    def _scale_rgb(rgb: np.ndarray, max_width: int) -> np.ndarray:
        if max_width <= 0:
            return np.ascontiguousarray(rgb)
        height, width = rgb.shape[:2]
        if width <= max_width:
            return np.ascontiguousarray(rgb)
        scale = max_width / float(width)
        new_w = max(1, int(round(width * scale)))
        new_h = max(1, int(round(height * scale)))
        scaled = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(scaled)


def probe_video(path: str) -> MediaInfo | None:
    """Open briefly to read metadata, then release the capture."""
    _configure_decoder_logging()
    with _CAPTURE_LOCK:
        capture = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            capture.release()
            return None
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0.001:
            fps = 30.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        capture.release()

    if width <= 0 or height <= 0 or frame_count <= 0:
        return None
    return MediaInfo(
        fps=fps,
        duration_sec=frame_count / fps,
        width=width,
        height=height,
        frame_count=frame_count,
    )
