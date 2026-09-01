"""Reliable H.264 MP4 writer used by the export pipeline.

``cv2.VideoWriter`` with the ``mp4v`` fourcc is the previous approach and is
a common source of "corrupted" exports: OpenCV's headless build lacks a
proper H.264 encoder, so it silently falls back to tagging a non-standard
MPEG-4 Part 2 bitstream as an ``.mp4`` container. Many players, browsers,
and NLEs refuse to open the result or report it as damaged.

This module instead pipes raw RGB frames straight through FFmpeg (via the
bundled ``imageio-ffmpeg`` binary, so no system FFmpeg install is required)
encoded as H.264 with 4:2:0 chroma subsampling and a ``+faststart`` moov
atom, which is the de-facto standard for universally playable MP4 output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import wave
from enum import Enum, auto
from pathlib import Path
from types import TracebackType

import cv2
import imageio_ffmpeg
import numpy as np

from core.audio import AudioData
from render.audio_playback import _resample_audio


class ExportQuality(Enum):
    """Export speed/quality profiles for MP4 encoding."""

    DRAFT = auto()
    FAST = auto()
    BALANCED = auto()
    HIGH_QUALITY = auto()


_EXPORT_PROFILE_SETTINGS: dict[ExportQuality, tuple[str, int]] = {
    ExportQuality.DRAFT: ("ultrafast", 24),
    ExportQuality.FAST: ("veryfast", 20),
    ExportQuality.BALANCED: ("medium", 18),
    ExportQuality.HIGH_QUALITY: ("slow", 16),
}


class Mp4VideoWriter:
    """Streams uint8 HxWx3 RGB frames to disk as an H.264 MP4 via FFmpeg."""

    def __init__(
        self,
        output_path: Path,
        *,
        fps: float,
        width: int,
        height: int,
        audio_sample_rate: int = 48000,
        audio_channels: int = 2,
        include_audio: bool = True,
        quality: ExportQuality = ExportQuality.FAST,
    ) -> None:
        """Open the FFmpeg-backed writer.

        Parameters:
            output_path: Destination ``.mp4`` file path.
            fps: Output frame rate (clamped to at least 1 by the caller).
            width: Source frame width in pixels.
            height: Source frame height in pixels.
            audio_sample_rate: Audio sample rate in Hz.
            audio_channels: Number of audio channels.

        Side effects:
            Spawns an FFmpeg subprocess (via ``imageio-ffmpeg``) that remains
            open until ``close`` is called.

        Raises:
            OSError: If the FFmpeg binary cannot be located or started.
            RuntimeError: If the writer fails to initialize.
        """
        # libx264 requires even dimensions for 4:2:0 chroma subsampling;
        # pad by one replicated pixel row/column rather than resizing so the
        # visible image is never distorted.
        self._pad_right: int = width % 2
        self._pad_bottom: int = height % 2
        self._audio_sample_rate: int = max(1, int(audio_sample_rate))
        self._audio_channels: int = 1 if int(audio_channels) == 1 else 2
        self._include_audio: bool = bool(include_audio)
        self._fps: float = fps
        self._output_path: Path = output_path
        self._temp_video_path: Path = output_path.with_suffix(".video.mp4") if self._include_audio else output_path
        self._quality: ExportQuality = quality

        self._has_audio: bool = False
        self._audio_wav_path: str | None = None
        self._audio_wave: wave.Wave_write | None = None
        self._audio_write_lock = threading.Lock()

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        input_width = width + self._pad_right
        input_height = height + self._pad_bottom
        preset, crf = _EXPORT_PROFILE_SETTINGS.get(self._quality, _EXPORT_PROFILE_SETTINGS[ExportQuality.FAST])
        extra_video_args: list[str] = []
        if self._quality == ExportQuality.DRAFT:
            extra_video_args.extend(["-tune", "zerolatency"])
        cmd = [
            ffmpeg_exe,
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{input_width}x{input_height}",
            "-r", f"{fps:g}",
            "-i", "-",
            "-an",
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            *extra_video_args,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(self._temp_video_path),
        ]
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if self._include_audio:
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            self._audio_wav_path = temp_audio.name
            temp_audio.close()
            self._audio_wave = wave.open(self._audio_wav_path, "wb")
            self._audio_wave.setnchannels(self._audio_channels)
            self._audio_wave.setsampwidth(2)
            self._audio_wave.setframerate(self._audio_sample_rate)

    def write(self, frame_rgb: np.ndarray, audio: "AudioData | None" = None) -> None:
        """Append one uint8 HxWx3 RGB frame, padding to even dimensions.

        Args:
            frame_rgb: Video frame as RGB uint8 array
            audio: Optional audio data for this frame
        """
        if self._pad_right or self._pad_bottom:
            frame_rgb = cv2.copyMakeBorder(
                frame_rgb,
                0,
                self._pad_bottom,
                0,
                self._pad_right,
                cv2.BORDER_REPLICATE,
            )
        if self._process.stdin is None:
            raise RuntimeError("FFmpeg video writer stdin is unavailable")
        self._process.stdin.write(np.ascontiguousarray(frame_rgb).tobytes())

        if self._include_audio and audio is not None and self._audio_wave is not None:
            samples = np.asarray(audio.samples, dtype=np.float32)
            if samples.ndim == 1:
                samples = samples[:, np.newaxis]
            if samples.shape[1] > self._audio_channels:
                samples = samples[:, :self._audio_channels]
            elif samples.shape[1] < self._audio_channels:
                if samples.shape[1] == 1 and self._audio_channels == 2:
                    samples = np.repeat(samples, 2, axis=1)
                else:
                    padding = np.zeros(
                        (samples.shape[0], self._audio_channels - samples.shape[1]),
                        dtype=np.float32,
                    )
                    samples = np.concatenate((samples, padding), axis=1)
            if int(audio.sample_rate) != self._audio_sample_rate:
                samples = _resample_audio(samples, int(audio.sample_rate), self._audio_sample_rate)
            audio_int16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16, copy=False)
            with self._audio_write_lock:
                self._audio_wave.writeframes(audio_int16.tobytes())
            if not audio.is_silent():
                self._has_audio = True

    def write_video_only(self, frame_rgb: np.ndarray) -> None:
        """Append one uint8 HxWx3 RGB frame without audio (for backward compatibility)."""
        self.write(frame_rgb, audio=None)

    def close(self) -> None:
        """Flush buffered frames and finalize the MP4 container."""
        if self._process.stdin is not None:
            self._process.stdin.close()
        stderr = ""
        if self._process.stderr is not None:
            stderr = self._process.stderr.read().decode("utf-8", errors="replace")
            self._process.stderr.close()
        return_code = self._process.wait(timeout=300)
        if return_code != 0:
            raise RuntimeError(f"FFmpeg video encode failed ({return_code}): {stderr.strip()}")

        if self._audio_wave is not None:
            self._audio_wave.close()
            self._audio_wave = None

        if self._include_audio and self._has_audio and self._audio_wav_path is not None:
            self._mux_audio()
        elif self._include_audio and self._temp_video_path != self._output_path:
            shutil.move(str(self._temp_video_path), str(self._output_path))
            if self._audio_wav_path is not None:
                Path(self._audio_wav_path).unlink(missing_ok=True)

    def _mux_audio(self) -> None:
        """Add audio track to the video file using FFmpeg."""
        if self._audio_wav_path is None:
            return

        try:
            temp_output = self._output_path.with_suffix(".temp.mp4")
            cmd = [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i", str(self._temp_video_path),
                "-i", self._audio_wav_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-ar", str(self._audio_sample_rate),
                "-ac", str(self._audio_channels),
                "-movflags", "+faststart",
                str(temp_output),
            ]

            subprocess.run(cmd, capture_output=True, check=True, timeout=300)
            shutil.move(str(temp_output), str(self._output_path))
            if self._temp_video_path != self._output_path:
                Path(self._temp_video_path).unlink(missing_ok=True)

        except Exception as e:
            import warnings
            warnings.warn(f"Failed to mux audio: {e}")
            if self._temp_video_path != self._output_path and Path(self._temp_video_path).exists():
                shutil.move(str(self._temp_video_path), str(self._output_path))
        finally:
            if self._audio_wav_path is not None:
                Path(self._audio_wav_path).unlink(missing_ok=True)
                self._audio_wav_path = None

    def __enter__(self) -> Mp4VideoWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
