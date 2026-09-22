"""Timeline Input node: composes a multi-track timeline into frame + audio.

This is the node-graph entry point for the CapCut-style timeline editor. The
node owns a :class:`~core.timeline.Timeline` of video and audio clips; on
evaluation it decodes every active clip, composites video clips by layer
(lowest track first) with per-clip opacity, and mixes the active audio.
"""

from __future__ import annotations

import cv2
import numpy as np
from core.audio import AudioData, FrameWithAudio
from core.nodes.base import NodeSocketType, NodeValue
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import color_property
from core.timeline import ClipKind, Timeline, TimelineClip
from effects.frame_ops import from_source_u8
from render.audio_decoder import AudioDecoder
from render.video_decoder import VideoDecoder

_TIMELINE_INPUT_COLOR: tuple[int, int, int] = (90, 170, 130)


class TimelineInputNode(FrameNode):
    """Source node that renders a multi-track timeline."""

    node_type = "Timeline Input"
    node_category = "Input/Output"
    node_description = "Compose video and audio clips from a multi-track timeline."
    node_color = _TIMELINE_INPUT_COLOR

    def _setup_sockets(self) -> None:
        self.add_output("frame", NodeSocketType.Frame)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property(
            "background",
            color_property(
                (0, 0, 0),
                priority=0,
                group="Timeline",
                label="Background",
                description="Color shown where no clip covers the frame.",
            ),
        )

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self._timeline = Timeline()
        self._video_decoders: dict[str, VideoDecoder] = {}
        self._video_fps: dict[str, float] = {}
        self._audio_decoders: dict[str, AudioDecoder] = {}
        self._image_cache: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Timeline access (the timeline editor mutates this)
    # ------------------------------------------------------------------

    @property
    def timeline(self) -> Timeline:
        return self._timeline

    # ------------------------------------------------------------------
    # Persistence (project save/load, undo, duplicate, copy/paste)
    # ------------------------------------------------------------------

    def snapshot_data(self) -> dict:
        return {"timeline": self._timeline.to_dict()}

    def restore_snapshot_data(self, data: dict) -> None:
        self._timeline = Timeline.from_dict((data or {}).get("timeline"))

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["timeline"] = self._timeline.to_dict()
        return payload

    def apply_document(self, data: dict) -> None:
        super().apply_document(data)
        self._timeline = Timeline.from_dict(data.get("timeline"))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_output(self, frame_num: int, output_slot: str) -> NodeValue:
        composed = self.evaluate(frame_num)
        if output_slot == "audio":
            return composed.audio if isinstance(composed, FrameWithAudio) else None
        return composed

    def evaluate(self, frame_num: int) -> NodeValue:
        width, height = self.evaluation_frame_size()
        background = self.color_value("background", (0, 0, 0))
        output = np.empty((height, width, 3), dtype=np.float32)
        output[..., 0] = background[0] / 255.0
        output[..., 1] = background[1] / 255.0
        output[..., 2] = background[2] / 255.0

        fps = float(self._project_fps) or 30.0
        frame_period = 1.0 / fps

        for clip in self._timeline.video_clips_at(frame_num):
            frame = self._decode_video(clip, frame_num, width, height)
            if frame is None:
                continue
            alpha = float(np.clip(clip.opacity, 0.0, 1.0))
            if alpha >= 1.0:
                output = frame
            else:
                output = output * (1.0 - alpha) + frame * alpha

        audio_chunks: list[np.ndarray] = []
        audio_rate = 48000
        for clip in self._timeline.audio_clips_at(frame_num):
            block = self._decode_audio(clip, frame_num, fps, frame_period)
            if block is None:
                continue
            samples = np.asarray(block.samples, dtype=np.float32)
            if clip.volume != 1.0:
                samples = samples * float(clip.volume)
            audio_rate = block.sample_rate
            audio_chunks.append(samples)

        if audio_chunks:
            audio = AudioData(samples=self._mix_audio(audio_chunks), sample_rate=audio_rate)
        else:
            audio = AudioData.silence(frame_period, audio_rate, 2)

        return FrameWithAudio(frame=output, audio=audio)

    def _decode_video(self, clip: TimelineClip, frame_num: int, width: int, height: int) -> np.ndarray | None:
        if clip.kind == ClipKind.IMAGE:
            frame = self._image_cache.get(clip.path)
            if frame is None:
                bgr = cv2.imread(clip.path, cv2.IMREAD_COLOR)
                if bgr is None:
                    return None
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                frame = from_source_u8(rgb)
                self._image_cache[clip.path] = frame
            if frame.shape[:2] != (height, width):
                return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            return frame

        decoder = self._video_decoders.get(clip.path)
        if decoder is None:
            decoder = VideoDecoder()
            info = decoder.open(clip.path)
            if info is None:
                return None
            self._video_decoders[clip.path] = decoder
            self._video_fps[clip.path] = info.fps if info.fps > 0 else 30.0
        source_frame = clip.source_frame_at(frame_num)
        rgb_u8 = decoder.read_rgb(source_frame, max_width=width)
        if rgb_u8 is None:
            return None
        frame = from_source_u8(rgb_u8)
        if frame.shape[:2] != (height, width):
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        return frame

    def _decode_audio(
        self,
        clip: TimelineClip,
        frame_num: int,
        fps: float,
        frame_period: float,
    ) -> AudioData | None:
        if clip.kind == ClipKind.VIDEO:
            decoder = self._video_decoders.get(clip.path)
            if decoder is None:
                decoder = VideoDecoder()
                info = decoder.open(clip.path)
                if info is None:
                    return None
                self._video_decoders[clip.path] = decoder
                self._video_fps[clip.path] = info.fps if info.fps > 0 else 30.0
            source_fps = self._video_fps.get(clip.path, fps)
            source_frame = clip.source_frame_at(frame_num)
            start_sec = source_frame / max(source_fps, 0.001)
            return decoder.read_audio_range(start_sec, frame_period)

        decoder = self._audio_decoders.get(clip.path)
        if decoder is None:
            decoder = AudioDecoder()
            if decoder.open(clip.path) is None:
                return None
            self._audio_decoders[clip.path] = decoder
        start_sec = clip.source_start_sec + (frame_num - clip.start_frame) / max(fps, 0.001)
        return decoder.extract_audio_for_time_range(start_sec, frame_period)

    @staticmethod
    def _mix_audio(chunks: list[np.ndarray]) -> np.ndarray:
        length = max(chunk.shape[0] for chunk in chunks)
        channels = max(chunk.shape[1] if chunk.ndim > 1 else 1 for chunk in chunks)
        mixed = np.zeros((length, channels), dtype=np.float32)
        for chunk in chunks:
            if chunk.ndim == 1:
                chunk = chunk[:, None]
            if chunk.shape[1] == 1 and channels > 1:
                chunk = np.repeat(chunk, channels, axis=1)
            take = min(length, chunk.shape[0])
            mixed[:take, : chunk.shape[1]] += chunk[:take]
        return np.clip(mixed, -1.0, 1.0)
