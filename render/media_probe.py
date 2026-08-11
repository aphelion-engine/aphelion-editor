"""Probe video containers and enforce the required audio track policy."""

from __future__ import annotations

from pathlib import Path

import av

from render.media_info import MediaInfo, MediaValidationError
from utils.logging_setup import get_logger

_LOG = get_logger("render.media_probe")

# Aphelion policy: every imported video must carry a real audio stream.
REQUIRE_AUDIO_TRACK: bool = True


def probe_media(path: str | Path, *, require_audio: bool = REQUIRE_AUDIO_TRACK) -> MediaInfo:
    """Inspect ``path`` and return combined video/audio metadata.

    Parameters:
        path: Media file path.
        require_audio: When ``True``, reject files with no usable audio.

    Returns:
        Validated ``MediaInfo``.

    Raises:
        MediaValidationError: Missing file, unreadable container, no video,
            or (when required) no audio track.
    """
    source = Path(path)
    if not source.is_file():
        raise MediaValidationError(f"Media file not found: {source}")

    try:
        container = av.open(str(source))
    except av.AVError as exc:
        raise MediaValidationError(f"Could not open media: {source}") from exc

    try:
        return _info_from_container(container, source, require_audio=require_audio)
    finally:
        container.close()


def _info_from_container(
    container: av.container.InputContainer,
    source: Path,
    *,
    require_audio: bool,
) -> MediaInfo:
    video = next((s for s in container.streams.video), None)
    if video is None:
        raise MediaValidationError(f"No video stream in: {source}")

    audio = next((s for s in container.streams.audio), None)
    fps = _stream_fps(video)
    frame_count = max(0, int(video.frames or 0))
    width = int(video.codec_context.width or 0)
    height = int(video.codec_context.height or 0)
    duration_sec = _stream_duration_sec(video, container)
    if frame_count <= 0 and duration_sec > 0.0 and fps > 0.0:
        frame_count = max(1, int(round(duration_sec * fps)))
    if duration_sec <= 0.0 and frame_count > 0 and fps > 0.0:
        duration_sec = float(frame_count) / fps

    if width <= 0 or height <= 0:
        raise MediaValidationError(f"Invalid video dimensions in: {source}")
    if duration_sec <= 0.0:
        raise MediaValidationError(f"Could not determine duration for: {source}")

    has_audio = audio is not None
    sample_rate = int(audio.rate or 0) if audio is not None else 0
    channels = int(audio.channels or 0) if audio is not None else 0
    audio_duration = (
        _stream_duration_sec(audio, container) if audio is not None else 0.0
    )
    if audio_duration <= 0.0 and has_audio:
        audio_duration = duration_sec

    info = MediaInfo(
        fps=fps,
        duration_sec=duration_sec,
        width=width,
        height=height,
        frame_count=frame_count,
        has_audio=has_audio,
        sample_rate=sample_rate,
        audio_channels=channels,
        audio_duration_sec=audio_duration,
    )
    if require_audio and not info.audio_ok:
        raise MediaValidationError(
            f"Video must include an audio track: {source.name}"
        )
    _LOG.debug(
        "Probed %s (fps=%.3f frames=%s audio=%s Hz x%s)",
        source.name,
        info.fps,
        info.frame_count,
        info.sample_rate,
        info.audio_channels,
    )
    return info


def _stream_fps(stream: av.video.stream.VideoStream) -> float:
    average = stream.average_rate
    if average is not None and float(average) > 0.001:
        return float(average)
    base = stream.base_rate
    if base is not None and float(base) > 0.001:
        return float(base)
    return 30.0


def _stream_duration_sec(
    stream: av.audio.stream.AudioStream | av.video.stream.VideoStream,
    container: av.container.InputContainer,
) -> float:
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return float(container.duration) / float(av.time_base)
    return 0.0
