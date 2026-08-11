"""Shared media metadata and validation errors for A/V assets."""

from __future__ import annotations

from dataclasses import dataclass


class MediaValidationError(ValueError):
    """Raised when a media file fails Aphelion's import rules."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Video + audio metadata used for timeline sync and playback."""

    fps: float
    duration_sec: float
    width: int
    height: int
    frame_count: int
    has_audio: bool
    sample_rate: int
    audio_channels: int
    audio_duration_sec: float

    @property
    def audio_ok(self) -> bool:
        """Return whether a usable audio track is present."""
        return (
            self.has_audio
            and self.sample_rate > 0
            and self.audio_channels > 0
            and self.audio_duration_sec > 0.0
        )
