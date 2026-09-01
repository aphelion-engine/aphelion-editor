"""Audio data structures for carrying audio with video frames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class AudioData:
    """Immutable audio data container that travels with video frames.

    Stores audio samples synchronized with a specific video frame. The audio
    is represented as a float32 numpy array with values in the range [-1.0, 1.0].
    """

    samples: np.ndarray
    """Audio samples as a float32 array. Shape is (num_samples,) for mono
    or (num_samples, num_channels) for multi-channel audio."""

    sample_rate: int
    """Sample rate in Hz (e.g., 44100, 48000)"""

    def __post_init__(self) -> None:
        """Validate audio data structure."""
        if not isinstance(self.samples, np.ndarray):
            raise TypeError("Audio samples must be a numpy array")
        if self.samples.dtype != np.float32:
            raise TypeError("Audio samples must be float32")
        if self.samples.ndim not in (1, 2):
            raise ValueError("Audio samples must be 1D (mono) or 2D (multi-channel)")
        if self.sample_rate <= 0:
            raise ValueError("Sample rate must be positive")

    @property
    def num_samples(self) -> int:
        """Return the number of audio samples."""
        return self.samples.shape[0]

    @property
    def num_channels(self) -> int:
        """Return the number of audio channels."""
        if self.samples.ndim == 1:
            return 1
        return self.samples.shape[1]

    @property
    def duration(self) -> float:
        """Return audio duration in seconds."""
        return self.num_samples / self.sample_rate

    @classmethod
    def silence(cls, duration: float, sample_rate: int = 48000, channels: int = 1) -> AudioData:
        """Create silence audio data."""
        num_samples = int(duration * sample_rate)
        if channels == 1:
            samples = np.zeros(num_samples, dtype=np.float32)
        else:
            samples = np.zeros((num_samples, channels), dtype=np.float32)
        return cls(samples=samples, sample_rate=sample_rate)

    def is_silent(self, threshold: float = 1e-6) -> bool:
        """Check if audio is effectively silent."""
        return np.max(np.abs(self.samples)) < threshold

    def to_bytes(self) -> bytes:
        """Convert audio samples to bytes for transport/serialization."""
        return self.samples.tobytes()

    @classmethod
    def from_bytes(cls, data: bytes, sample_rate: int, num_channels: int = 1) -> AudioData:
        """Reconstruct AudioData from bytes."""
        samples = np.frombuffer(data, dtype=np.float32)
        if num_channels > 1:
            samples = samples.reshape(-1, num_channels)
        return cls(samples=samples, sample_rate=sample_rate)


@dataclass(frozen=True, slots=True)
class FrameWithAudio:
    """Container for a video frame with its synchronized audio data.

    This type is used to carry audio alongside video frames through the node graph,
    enabling audio processing and export without requiring separate audio connections.
    """

    frame: np.ndarray
    """Video frame as HxWx3 float32 array in range [0.0, 1.0]"""

    audio: AudioData | None
    """Audio data synchronized with this frame, or None if no audio"""

    @property
    def has_audio(self) -> bool:
        """Check if this frame has associated audio."""
        return self.audio is not None and not self.audio.is_silent()

    @property
    def audio_sample_rate(self) -> int:
        """Get audio sample rate, defaulting to 48000 if no audio."""
        return self.audio.sample_rate if self.audio else 48000

    @property
    def audio_channels(self) -> int:
        """Get number of audio channels, defaulting to 2 if no audio."""
        return self.audio.num_channels if self.audio else 2
