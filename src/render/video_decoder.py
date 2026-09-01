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
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# Must be set before the first OpenCV/FFmpeg capture is created.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")  # AV_LOG_FATAL
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")

import cv2
import numpy as np

from config.constants import DEFAULT_DECODE_CACHE_FRAMES
from core.audio import AudioData
from render.audio_decoder import AudioDecoder, AudioInfo

# Prefer sequential decode over hard seeks within this many frames.
_MAX_FORWARD_GRABS: int = 48
_SEEK_READ_RETRIES: int = 3

_CAPTURE_LOCK = threading.RLock()
_LOGGING_CONFIGURED = False

# Global performance knobs, pushed from Preferences via the setters below.
# Kept module-level (rather than per-instance constructor args) so every
# VideoInput node's decoder picks up a preference change immediately,
# without the node graph needing to know about the preference system.
_DECODE_CACHE_FRAMES: int = DEFAULT_DECODE_CACHE_FRAMES
_HARDWARE_DECODE_ENABLED: bool = False


def set_decode_cache_frames(frame_count: int) -> None:
    """Set how many full-resolution decoded frames each decoder retains.

    A larger LRU avoids re-seeking/re-decoding when a user scrubs back over
    recently visited source frames, or when a downstream (non-source) node
    property changes and invalidates only the node-output cache. Cost is
    O(frame_count) full-resolution frames of RAM per open Video Input node.
    """
    global _DECODE_CACHE_FRAMES
    _DECODE_CACHE_FRAMES = max(1, int(frame_count))


def set_hardware_decode_enabled(enabled: bool) -> None:
    """Toggle best-effort hardware-accelerated decode for newly opened media.

    Side effects:
        Takes effect the next time a ``VideoDecoder`` opens a file; already
        open captures are unaffected until re-opened.
    """
    global _HARDWARE_DECODE_ENABLED
    _HARDWARE_DECODE_ENABLED = bool(enabled)


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


def _try_enable_hardware_acceleration(capture: cv2.VideoCapture) -> None:
    """Best-effort request for hardware-accelerated decode.

    Not every OpenCV build exposes ``CAP_PROP_HW_ACCELERATION`` and not every
    platform has a working backend, so failures are silently ignored and
    decode falls back to software — this is strictly an opt-in speed hint,
    never a correctness requirement.
    """
    accel_flag = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)
    accel_any = getattr(cv2, "VIDEO_ACCELERATION_ANY", None)
    if accel_flag is None or accel_any is None:
        return
    try:
        capture.set(accel_flag, accel_any)
    except Exception:  # noqa: BLE001
        pass


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Lightweight media metadata used to sync the project timeline."""

    fps: float
    duration_sec: float
    width: int
    height: int
    frame_count: int
    has_audio: bool = False
    audio_sample_rate: int = 48000
    audio_channels: int = 2


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
        # Bounded LRU of full-resolution decoded frames, keyed by source
        # frame index. Scaling to the requested proxy width happens on
        # every read from this cache — cheap relative to decode/seek.
        self._frame_cache: OrderedDict[int, np.ndarray] = OrderedDict()
        # Audio decoder for extracting audio from video files
        self._audio_decoder: AudioDecoder = AudioDecoder()
        self._audio_info: AudioInfo | None = None

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
            if _HARDWARE_DECODE_ENABLED:
                _try_enable_hardware_acceleration(capture)
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
            self._frame_cache.clear()

            # Open audio decoder
            self._audio_info = self._audio_decoder.open(path)

            return self.info()

    def info(self) -> MediaInfo | None:
        if not self.is_open:
            return None
        duration = (
            self._frame_count / self._fps
            if self._frame_count > 0
            else 0.0
        )

        # Get audio info if available
        has_audio = False
        audio_sample_rate = 48000
        audio_channels = 2
        if self._audio_info is not None:
            has_audio = self._audio_info.has_audio
            audio_sample_rate = self._audio_info.sample_rate
            audio_channels = self._audio_info.num_channels

        return MediaInfo(
            fps=self._fps,
            duration_sec=duration,
            width=self._width,
            height=self._height,
            frame_count=self._frame_count,
            has_audio=has_audio,
            audio_sample_rate=audio_sample_rate,
            audio_channels=audio_channels,
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
        self._frame_cache.clear()
        self._audio_decoder.close()
        self._audio_info = None

    def read_rgb(self, frame_num: int, max_width: int) -> np.ndarray | None:
        """Return an RGB frame at ``frame_num``, optionally proxy-scaled."""
        with _CAPTURE_LOCK:
            if not self.is_open or self._capture is None:
                return None

            target = max(0, int(frame_num))
            if self._frame_count > 0:
                target = min(target, self._frame_count - 1)

            cached = self._frame_cache.get(target)
            if cached is not None:
                self._frame_cache.move_to_end(target)
                return self._scale_rgb(cached, max_width)

            if not self._position_to(target):
                return self._held_frame(max_width)

            frame = self._read_bgr_with_retry()
            if frame is None:
                # Hard seeks into H.264 often fail once; hold last good frame.
                return self._held_frame(max_width)

            self._next_index = target + 1
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._remember(target, rgb)
            return self._scale_rgb(rgb, max_width)

    def _remember(self, frame_num: int, rgb: np.ndarray) -> None:
        """Insert ``rgb`` into the bounded LRU, evicting the oldest entry."""
        self._frame_cache[frame_num] = rgb
        self._frame_cache.move_to_end(frame_num)
        while len(self._frame_cache) > max(1, _DECODE_CACHE_FRAMES):
            self._frame_cache.popitem(last=False)

    def _held_frame(self, max_width: int) -> np.ndarray | None:
        if not self._frame_cache:
            return None
        _, last_rgb = next(reversed(self._frame_cache.items()))
        return self._scale_rgb(last_rgb, max_width)

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

    def read_audio(self, frame_num: int) -> "AudioData | None":
        """Read audio samples for a specific frame."""
        if not self.is_open or self._audio_info is None or not self._audio_info.has_audio:
            duration_per_frame = 1.0 / max(self._fps, 0.001)
            return AudioData.silence(
                duration=duration_per_frame,
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2
            )

        duration_per_frame = 1.0 / max(self._fps, 0.001)
        return self._audio_decoder.extract_audio_for_frame(
            frame_num=frame_num,
            fps=self._fps,
            duration_per_frame=duration_per_frame
        )

    def read_audio_range(self, start_time_sec: float, duration_sec: float) -> "AudioData | None":
        """Read a contiguous audio range by time for smoother preview playback."""
        if not self.is_open or self._audio_info is None or not self._audio_info.has_audio:
            return AudioData.silence(
                duration=max(0.0, float(duration_sec)),
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2,
            )
        return self._audio_decoder.extract_audio_for_time_range(start_time_sec, duration_sec)


def _probe_video_metadata(path: str) -> tuple[float, int, int, int] | None:
    """Return ``(fps, frame_count, width, height)`` or ``None`` on failure."""
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
    return fps, frame_count, width, height


def _probe_audio_metadata(path: str) -> AudioInfo | None:
    """Return audio metadata for ``path`` without retaining decoder state."""
    audio_decoder = AudioDecoder()
    try:
        return audio_decoder.open(path)
    finally:
        audio_decoder.close()


def probe_video(path: str) -> MediaInfo | None:
    """Open briefly to read metadata, then release the capture."""
    _configure_decoder_logging()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-probe") as executor:
        video_future = executor.submit(_probe_video_metadata, path)
        audio_future = executor.submit(_probe_audio_metadata, path)
        video_info = video_future.result()
        audio_info = audio_future.result()

    if video_info is None:
        return None

    fps, frame_count, width, height = video_info
    has_audio = audio_info.has_audio if audio_info else False
    audio_sample_rate = audio_info.sample_rate if audio_info else 48000
    audio_channels = audio_info.num_channels if audio_info else 2

    return MediaInfo(
        fps=fps,
        duration_sec=frame_count / fps,
        width=width,
        height=height,
        frame_count=frame_count,
        has_audio=has_audio,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
    )
