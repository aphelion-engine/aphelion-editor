"""Audio extraction from video files using FFmpeg."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from core.audio import AudioData

if TYPE_CHECKING:
    pass


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


class AudioDecoder:
    """Extract audio from video files using FFmpeg."""

    def __init__(self) -> None:
        self._path: str | None = None
        self._audio_info: AudioInfo | None = None
        self._temp_audio_file: str | None = None

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._path is not None and self._audio_info is not None

    def open(self, path: str) -> AudioInfo | None:
        """Open a video file and extract audio info."""
        if self._path == path and self.is_open:
            return self._audio_info

        self._close()

        try:
            # Use FFmpeg to probe audio information
            cmd = [
                "ffmpeg",
                "-i", path,
                "-hide_banner",
                "-loglevel", "error",
                "-f", "null",
                "-"
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            # Extract audio info using ffprobe
            probe_cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=sample_rate,channels,duration",
                "-of", "json",
                path
            ]
            probe_result = subprocess.run(
                probe_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if probe_result.returncode != 0:
                # No audio stream
                self._path = path
                self._audio_info = AudioInfo(
                    sample_rate=48000,
                    num_channels=2,
                    duration_sec=0.0,
                    has_audio=False
                )
                return self._audio_info

            import json
            probe_data = json.loads(probe_result.stdout)

            if not probe_data.get("streams"):
                # No audio stream found
                self._path = path
                self._audio_info = AudioInfo(
                    sample_rate=48000,
                    num_channels=2,
                    duration_sec=0.0,
                    has_audio=False
                )
                return self._audio_info

            stream = probe_data["streams"][0]
            sample_rate = int(stream.get("sample_rate", 48000))
            num_channels = int(stream.get("channels", 2))
            duration = float(stream.get("duration", 0.0))

            self._path = path
            self._audio_info = AudioInfo(
                sample_rate=sample_rate,
                num_channels=num_channels,
                duration_sec=duration,
                has_audio=True
            )

            return self._audio_info

        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError) as e:
            # Fallback: assume no audio
            self._path = path
            self._audio_info = AudioInfo(
                sample_rate=48000,
                num_channels=2,
                duration_sec=0.0,
                has_audio=False
            )
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
        if self._temp_audio_file and os.path.exists(self._temp_audio_file):
            try:
                os.unlink(self._temp_audio_file)
            except OSError:
                pass
        self._temp_audio_file = None

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
        if not self.is_open or self._audio_info is None or not self._audio_info.has_audio:
            # Return silence
            return AudioData.silence(
                duration=duration_per_frame,
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2
            )

        if self._path is None:
            return AudioData.silence(duration=duration_per_frame)

        try:
            # Calculate start time for this frame
            start_time = frame_num / fps

            # Extract audio segment for this frame using FFmpeg
            cmd = [
                "ffmpeg",
                "-ss", str(start_time),
                "-i", self._path,
                "-t", str(duration_per_frame),
                "-vn",  # No video
                "-acodec", "pcm_f32le",  # Float32 PCM
                "-ar", str(self._audio_info.sample_rate),
                "-ac", str(self._audio_info.num_channels),
                "-f", "f32le",  # Raw float32 output
                "-"  # Output to stdout
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30
            )

            if result.returncode != 0:
                return AudioData.silence(
                    duration=duration_per_frame,
                    sample_rate=self._audio_info.sample_rate,
                    channels=self._audio_info.num_channels
                )

            # Convert raw bytes to numpy array
            samples = np.frombuffer(result.stdout, dtype=np.float32)

            # Reshape for multi-channel audio
            if self._audio_info.num_channels > 1:
                samples = samples.reshape(-1, self._audio_info.num_channels)

            return AudioData(
                samples=samples,
                sample_rate=self._audio_info.sample_rate
            )

        except (subprocess.TimeoutExpired, ValueError) as e:
            return AudioData.silence(
                duration=duration_per_frame,
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2
            )
