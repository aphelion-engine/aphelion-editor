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
        return self.samples.size == 0 or bool(np.max(np.abs(self.samples)) < threshold)

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


def frame_sample_bounds(frame_num: int, fps: float, sample_rate: int) -> tuple[int, int]:
    """Absolute sample boundaries; fractional FPS never accumulates rounding drift."""
    if not np.isfinite(fps) or fps <= 0 or sample_rate <= 0:
        raise ValueError("FPS and sample rate must be positive")
    return round(frame_num * sample_rate / fps), round((frame_num + 1) * sample_rate / fps)


def convert_audio(audio: AudioData | None, sample_rate: int, channels: int,
                  sample_count: int | None = None) -> AudioData:
    """Convert rate/layout and pad or trim a timeline block without mutating it."""
    if channels < 1 or sample_rate < 1:
        raise ValueError("Invalid output audio format")
    if audio is None:
        samples = np.zeros((sample_count or 0, channels), np.float32)
    else:
        samples = np.asarray(audio.samples, dtype=np.float32)
        if samples.ndim == 1:
            samples = samples[:, None]
        if channels == 1 and samples.shape[1] > 1:
            samples = samples.mean(axis=1, keepdims=True)
        elif samples.shape[1] == 1 and channels > 1:
            samples = np.repeat(samples, channels, axis=1)
        elif samples.shape[1] != channels:
            converted = np.zeros((len(samples), channels), np.float32)
            n = min(channels, samples.shape[1])
            converted[:, :n] = samples[:, :n]
            samples = converted
        if audio.sample_rate != sample_rate and len(samples):
            count = round(len(samples) * sample_rate / audio.sample_rate)
            positions = np.arange(count, dtype=np.float64) * audio.sample_rate / sample_rate
            samples = np.column_stack([np.interp(positions, np.arange(len(samples)), samples[:, c])
                                       for c in range(channels)]).astype(np.float32)
        if sample_count is not None:
            block = np.zeros((sample_count, channels), np.float32)
            count = min(sample_count, len(samples))
            block[:count] = samples[:count]
            samples = block
    samples = np.array(samples, dtype=np.float32, copy=True, order="C")
    return AudioData(samples[:, 0] if channels == 1 else samples, sample_rate)
