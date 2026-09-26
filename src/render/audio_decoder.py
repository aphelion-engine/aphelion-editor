"""Audio extraction from video files using FFmpeg."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from core.audio import AudioData
from utils.logging_setup import get_logger

_LOG = get_logger("audio.decode")


def _resolve_ffprobe_exe(ffmpeg_exe: str) -> str | None:
    """Return a usable ffprobe path near the bundled ffmpeg, if present."""
    ffmpeg_path = Path(ffmpeg_exe)
    sibling = ffmpeg_path.with_name(ffmpeg_path.name.replace("ffmpeg", "ffprobe", 1))
    if sibling.is_file():
        return str(sibling)
    generic = ffmpeg_path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if generic.is_file():
        return str(generic)
    return None


@dataclass(frozen=True, slots=True)
class AudioInfo:
    """Metadata about audio in a video file."""

    sample_rate: int
    """Sample rate in Hz"""

    num_channels: int
    """Number of audio channels"""

    duration_sec: float
    """Duration in seconds"""

    has_audio: bool = True


_AUDIO_CACHE_LIMIT: int = 32
_AUDIO_CACHE: dict[tuple[str, int, int], tuple[AudioInfo, np.ndarray | None]] = {}
_AUDIO_CACHE_LOCK = threading.Lock()


def _audio_cache_key(path: str) -> tuple[str, int, int] | None:
    try:
        stat = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        return None


def clear_audio_cache() -> None:
    """Clear cached audio buffers."""
    with _AUDIO_CACHE_LOCK:
        _AUDIO_CACHE.clear()


class AudioDecoder:
    """Extract audio from video files using FFmpeg."""

    def __init__(self) -> None:
        self._path: str | None = None
        self._audio_info: AudioInfo | None = None
        self._decoded_samples: np.ndarray | None = None

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._path is not None and self._audio_info is not None

    def open(self, path: str, *, decode_samples: bool = True) -> AudioInfo | None:
        """Open a video file, optionally deferring full audio decoding."""
        if self._path == path and self.is_open and (
            not decode_samples or self._decoded_samples is not None
        ):
            return self._audio_info

        self._close()

        key = _audio_cache_key(path)
        if key is not None:
            with _AUDIO_CACHE_LOCK:
                cached = _AUDIO_CACHE.get(key)
                if cached is not None:
                    self._path = path
                    self._audio_info, self._decoded_samples = cached
                    return self._audio_info

        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            ffprobe_exe = _resolve_ffprobe_exe(ffmpeg_exe)

            sample_rate = 48000
            num_channels = 2
            duration = 0.0

            if ffprobe_exe is not None:
                probe_cmd = [
                    ffprobe_exe,
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=sample_rate,channels,duration",
                    "-of", "json",
                    path,
                ]
                probe_result = subprocess.run(
                    probe_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if probe_result.returncode == 0:
                    probe_data = json.loads(probe_result.stdout)
                    if probe_data.get("streams"):
                        stream = probe_data["streams"][0]
                        sample_rate = int(stream.get("sample_rate", 48000))
                        num_channels = int(stream.get("channels", 2))
                        duration = float(stream.get("duration", 0.0) or 0.0)

            else:
                _LOG.info("No ffprobe binary found next to bundled ffmpeg; using decode-only audio detection")

            has_audio = bool(probe_data.get("streams")) if ffprobe_exe is not None and probe_result.returncode == 0 else True
            self._path = path
            self._audio_info = AudioInfo(
                sample_rate=sample_rate,
                num_channels=num_channels,
                duration_sec=duration,
                has_audio=has_audio,
            )
            if not decode_samples:
                return self._audio_info

            decode_cmd = [
                ffmpeg_exe,
                "-v", "error",
                "-i", path,
                "-vn",
                "-map", "0:a:0",
                "-ac", str(num_channels),
                "-ar", str(sample_rate),
                "-acodec", "pcm_f32le",
                "-f", "f32le",
                "-",
            ]
            decode_result = subprocess.run(
                decode_cmd,
                capture_output=True,
                timeout=120,
            )
            if decode_result.returncode != 0 or not decode_result.stdout:
                self._audio_info = AudioInfo(
                    sample_rate=sample_rate,
                    num_channels=num_channels,
                    duration_sec=duration,
                    has_audio=False,
                )
                return self._audio_info

            samples = np.frombuffer(decode_result.stdout, dtype=np.float32)
            if num_channels > 1:
                frame_count = samples.size // num_channels
                samples = samples[: frame_count * num_channels].reshape(frame_count, num_channels)
            self._decoded_samples = np.ascontiguousarray(samples.astype(np.float32, copy=False))

            if duration <= 0.0 and sample_rate > 0:
                duration = float(self._decoded_samples.shape[0]) / float(sample_rate)

            self._audio_info = AudioInfo(
                sample_rate=sample_rate,
                num_channels=num_channels,
                duration_sec=duration,
                has_audio=self._decoded_samples.size > 0,
            )
            _LOG.info(
                "Decoded audio for %s: has_audio=%s sample_rate=%s channels=%s samples=%s duration=%.3fs",
                path,
                self._audio_info.has_audio,
                self._audio_info.sample_rate,
                self._audio_info.num_channels,
                self._decoded_samples.shape[0] if self._decoded_samples.ndim > 1 else self._decoded_samples.size,
                self._audio_info.duration_sec,
            )

            if key is not None:
                with _AUDIO_CACHE_LOCK:
                    if len(_AUDIO_CACHE) >= _AUDIO_CACHE_LIMIT:
                        _AUDIO_CACHE.pop(next(iter(_AUDIO_CACHE)))
                    _AUDIO_CACHE[key] = (self._audio_info, self._decoded_samples)

            return self._audio_info

        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError, FileNotFoundError) as exc:
            _LOG.warning("Audio decode setup failed for %s: %s", path, exc, exc_info=exc)
            self._path = path
            self._audio_info = AudioInfo(
                sample_rate=48000,
                num_channels=2,
                duration_sec=0.0,
                has_audio=False,
            )
            self._decoded_samples = None
            return self._audio_info

    def info(self) -> AudioInfo | None:
        """Return audio info if decoder is open."""
        return self._audio_info

    def close(self) -> None:
        """Clean up resources."""
        self._close()

    def _close(self) -> None:
        """Internal close without path check."""
        self._path = None
        self._audio_info = None
        self._decoded_samples = None

    def sample_at_times(self, times: np.ndarray) -> AudioData:
        """Read fractional source positions; out-of-media samples are silent."""
        self._ensure_samples()
        rate = self._audio_info.sample_rate if self._audio_info else 48000
        channels = self._audio_info.num_channels if self._audio_info else 2
        result = np.zeros((len(times), channels), np.float32)
        if self._decoded_samples is not None and self._decoded_samples.size:
            source = self._decoded_samples.reshape(-1, channels)
            positions = np.asarray(times, dtype=np.float64) * rate
            valid = np.isfinite(positions) & (positions >= 0) & (positions < len(source))
            left = np.floor(positions[valid]).astype(np.int64)
            right = np.minimum(left + 1, len(source) - 1)
            weight = (positions[valid] - left)[:, None]
            result[valid] = source[left] * (1 - weight) + source[right] * weight
        return AudioData(result[:, 0] if channels == 1 else result, rate)

    def extract_audio_for_time_range(
        self,
        start_time_sec: float,
        duration_sec: float,
    ) -> AudioData:
        """Extract audio samples for an arbitrary time range from the decoded buffer."""
        self._ensure_samples()
        if (
            not self.is_open
            or self._audio_info is None
            or not self._audio_info.has_audio
            or self._decoded_samples is None
        ):
            return AudioData.silence(
                duration=max(0.0, duration_sec),
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2,
            )

        sample_rate = self._audio_info.sample_rate
        channels = self._audio_info.num_channels
        safe_start = max(0.0, float(start_time_sec))
        safe_duration = max(0.0, float(duration_sec))
        start_index = max(0, int(round(safe_start * sample_rate)))
        end_index = max(start_index, int(round((safe_start + safe_duration) * sample_rate)))
        sliced = self._decoded_samples[start_index:end_index]

        expected_samples = end_index - start_index
        if sliced.shape[0] < expected_samples:
            if channels > 1:
                pad = np.zeros((expected_samples - sliced.shape[0], channels), dtype=np.float32)
            else:
                pad = np.zeros(expected_samples - sliced.shape[0], dtype=np.float32)
            sliced = np.concatenate((sliced, pad), axis=0)

        return AudioData(
            samples=np.ascontiguousarray(sliced.astype(np.float32, copy=False)),
            sample_rate=sample_rate,
        )

    def _ensure_samples(self) -> None:
        """Decode PCM only when a caller actually requests audio samples."""
        if self._decoded_samples is not None or not self._path:
            return
        if self._audio_info is not None and not self._audio_info.has_audio:
            return
        self.open(self._path, decode_samples=True)

    def extract_audio_for_frame(
        self,
        frame_num: int,
        fps: float,
        duration_per_frame: float
    ) -> AudioData:
        """Extract audio samples corresponding to a specific video frame.

        Args:
            frame_num: The video frame number
            fps: Video frame rate
            duration_per_frame: Duration of each frame in seconds

        Returns:
            AudioData containing samples for this frame, or silence if no audio
        """
        start_time = float(frame_num) / max(fps, 0.001)
        audio = self.extract_audio_for_time_range(start_time, duration_per_frame)
        if frame_num < 3:
            _LOG.info(
                "Audio slice frame=%s start_time=%.6f duration=%.6f actual=%s silent=%s",
                frame_num,
                start_time,
                duration_per_frame,
                audio.num_samples,
                audio.is_silent(),
            )
        return audio
