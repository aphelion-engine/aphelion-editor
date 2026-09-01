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

import subprocess
import tempfile
from pathlib import Path
from types import TracebackType

import cv2
import imageio
import imageio_ffmpeg
import numpy as np

from core.audio import AudioData

_H264_CRF: int = 18
"""Constant rate factor for libx264 (lower is higher quality; 18 is near-lossless)."""

_H264_PRESET: str = "medium"
"""libx264 speed/efficiency preset; a reasonable default for export jobs."""


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
        self._audio_sample_rate: int = audio_sample_rate
        self._audio_channels: int = audio_channels
        self._fps: float = fps
        self._output_path: Path = output_path

        # Audio buffer for collecting samples across frames
        self._audio_buffer: list[np.ndarray] = []
        self._has_audio: bool = False

        # Initialize video writer using imageio
        self._writer = imageio.get_writer(
            str(output_path),
            format="FFMPEG",
            mode="I",
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=1,
            output_params=[
                "-crf",
                str(_H264_CRF),
                "-preset",
                _H264_PRESET,
                "-movflags",
                "+faststart",
            ],
        )

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
        self._writer.append_data(frame_rgb)

        # Collect audio samples
        if audio is not None and not audio.is_silent():
            self._has_audio = True
            self._audio_buffer.append(audio.samples)

    def write_video_only(self, frame_rgb: np.ndarray) -> None:
        """Append one uint8 HxWx3 RGB frame without audio (for backward compatibility)."""
        self.write(frame_rgb, audio=None)

    def close(self) -> None:
        """Flush buffered frames and finalize the MP4 container."""
        self._writer.close()

        # If we have audio, mux it into the video file
        if self._has_audio and self._audio_buffer:
            self._mux_audio()

    def _mux_audio(self) -> None:
        """Add audio track to the video file using FFmpeg."""
        if not self._audio_buffer:
            return

        try:
            # Concatenate all audio samples
            all_audio = np.concatenate(self._audio_buffer, axis=0)

            # Create temporary audio file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                temp_audio_path = temp_audio.name

            # Write audio to temporary WAV file
            import wave
            import struct

            with wave.open(temp_audio_path, "wb") as wav_file:
                wav_file.setnchannels(self._audio_channels)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self._audio_sample_rate)

                # Convert float32 [-1, 1] to int16
                audio_int16 = (all_audio * 32767).astype(np.int16)
                if self._audio_channels == 1:
                    audio_int16 = audio_int16.reshape(-1, 1)

                wav_file.writeframes(audio_int16.tobytes())

            # Create temporary output file
            temp_output = self._output_path.with_suffix(".temp.mp4")

            # Use FFmpeg to mux audio
            cmd = [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",  # Overwrite output file
                "-i", str(self._output_path),  # Video input
                "-i", temp_audio_path,  # Audio input
                "-c:v", "copy",  # Copy video stream
                "-c:a", "aac",  # Encode audio as AAC
                "-ar", str(self._audio_sample_rate),
                "-ac", str(self._audio_channels),
                "-movflags", "+faststart",
                str(temp_output),
            ]

            subprocess.run(cmd, capture_output=True, check=True, timeout=300)

            # Replace original file with muxed version
            import shutil
            shutil.move(str(temp_output), str(self._output_path))

            # Clean up temporary audio file
            Path(temp_audio_path).unlink(missing_ok=True)

        except Exception as e:
            # If audio muxing fails, we still have the video-only file
            import warnings
            warnings.warn(f"Failed to mux audio: {e}")

    def __enter__(self) -> Mp4VideoWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
