"""Video file input node — OpenCV decode with sequential playback."""

from __future__ import annotations

from enum import IntEnum, auto

import numpy as np
from config.constants import DEFAULT_FPS, DEFAULT_PREVIEW_MAX_WIDTH
from core.audio import AudioData, FrameWithAudio
from core.nodes.base import (FRAME_DTYPE, MediaEdgeMode, Node, NodeProperty,
                             NodePropertyInputType, NodeSocketType,
                             PreviewCost, VideoFrameErrorMethod)
from core.nodes.enums import DECODE_QUALITY_SCALE, DecodeQuality
from effects.frame_ops import SOURCE_DTYPE, from_source_u8
from render.video_decoder import MediaInfo, VideoDecoder


class AudioChannelMode(IntEnum):
    """Audio channel output mode."""

    Stereo = auto()
    Mono = auto()


class VideoInputNode(Node):
    """Acts as an input source for a video stream.

    This node is where the single largest interactive win lives. It is the
    only place that touches decoder pixels, so it is the only place that can
    avoid the historical eager ``uint8 → float32`` promotion.

    ``can_emit_u8_frame`` tells the compiled render plan that this node is
    *able* to hand over its raw decoded buffer. Whether it actually does is
    decided per evaluation tree: ``Project`` only grants permission when the
    plan proved every node between this source and the Viewer tolerates
    8-bit input (see ``Node.accepts_u8_frame``).

    The promotion it skips is bit-identical to the one ``ensure_rgb_f32``
    performs on the first node that genuinely needs float precision, so
    final render output is unchanged — only the work disappears.
    """

    node_type = "Video Input"
    node_category = "Input/Output"
    node_description = "Acts as an input source for video stream"
    node_color = (50, 150, 50)

    #: Able to hand over the decoder's raw 8-bit buffer.
    can_emit_u8_frame = True
    #: A source is structurally cheap; decode cost is tracked separately.
    preview_cost = PreviewCost.LIGHT

    def __init__(self, name: str | None = None) -> None:
        self._decoder: VideoDecoder = VideoDecoder()
        self._previous_frame: np.ndarray | None = None
        self._current_frame: np.ndarray | None = None
        self._preview_max_width: int = DEFAULT_PREVIEW_MAX_WIDTH
        super().__init__(name)

    @property
    def _output_dtype(self) -> np.dtype:
        """Dtype this node should produce for the current evaluation tree."""
        return SOURCE_DTYPE if self._emit_u8_allowed else FRAME_DTYPE

    def _setup_sockets(self) -> None:
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "file_path",
            NodeProperty(
                input_type=NodePropertyInputType.File,
                value="",
                priority=0,
                group="Source",
                label="File",
                description="Video file decoded by this source node.",
            ),
        )
        self.set_property(
            "enabled",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=5,
                group="Source",
                label="Enabled",
                description="Disable decoding without removing graph connections.",
            ),
        )
        self.set_property(
            "start_frame",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=0,
                slider_min_value=0,
                slider_max_value=999999,
                priority=10,
                group="Trim",
                label="Start",
                description="First source frame included in playback.",
            ),
        )
        self.set_property(
            "end_frame",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=-1,
                slider_min_value=-1,
                slider_max_value=999999,
                priority=11,
                group="Trim",
                label="End",
                description="Last source frame; -1 uses the media end.",
            ),
        )
        self.set_property(
            "frame_offset",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=0,
                slider_min_value=-999999,
                slider_max_value=999999,
                priority=20,
                group="Timing",
                label="Offset",
                description="Project-frame delay before source playback begins.",
                suffix=" fr",
            ),
        )
        self.set_property(
            "fps",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=0.0,
                slider_min_value=0.0,
                slider_max_value=240.0,
                priority=25,
                group="Timing",
                label="FPS",
                description="Override source FPS; zero follows media metadata.",
                suffix=" fps",
            ),
        )
        self.set_property(
            "speed",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=1.0,
                slider_min_value=0.01,
                slider_max_value=16.0,
                priority=26,
                group="Timing",
                label="Speed",
                description="Playback speed multiplier.",
                suffix="×",
            ),
        )
        self.set_property(
            "reverse",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=False,
                priority=30,
                group="Timing",
                label="Reverse",
                description="Read source frames in reverse order.",
            ),
        )
        self.set_property(
            "before_start",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=MediaEdgeMode.Black,
                priority=40,
                group="Edges",
                label="Before Start",
                description="Sampling behavior before the active source range.",
            ),
        )
        self.set_property(
            "after_end",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=MediaEdgeMode.Hold,
                priority=41,
                group="Edges",
                label="After End",
                description="Sampling behavior after the active source range.",
            ),
        )
        self.set_property(
            "on_error",
            NodeProperty(
                input_type=NodePropertyInputType.VideoFrameErrorMethod,
                value=VideoFrameErrorMethod.Black,
                priority=50,
                group="Recovery",
                label="On Error",
                description="Fallback used when a source frame cannot be decoded.",
            ),
        )
        self._setup_quality_properties()
        self.set_property(
            "auto_sync_timeline",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=60,
                group="Project",
                label="Sync Timeline",
                description="Adopt loaded media duration, FPS, and frame dimensions.",
            ),
        )
        self.set_property(
            "audio_enabled",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=70,
                group="Audio",
                label="Enabled",
                description="Enable audio output from this source.",
            ),
        )
        self.set_property(
            "audio_volume",
            NodeProperty(
                input_type=NodePropertyInputType.Slider,
                value=100,
                slider_min_value=0,
                slider_max_value=200,
                priority=71,
                group="Audio",
                label="Volume",
                description="Audio volume multiplier.",
                suffix="%",
            ),
        )
        self.set_property(
            "audio_channel_mode",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=AudioChannelMode.Stereo,
                priority=72,
                group="Audio",
                label="Channels",
                description="Audio channel output mode.",
            ),
        )

    def _setup_quality_properties(self) -> None:
        """Expose the decode-quality controls.

        These are the knobs that decide how much of the source is
        materialised on the way to a frame. They are grouped separately
        from ``Source`` because they change *how* the file is read rather
        than *which* file it is — and because they are the first thing to
        reach for when a high-resolution source plays badly with no effects
        in the graph at all.

        The defaults keep the previous behaviour for ordinary footage and
        improve it for large sources: ``Auto`` decodes at whatever the
        Viewer can show, which is exactly what playback wants, while an
        explicit quality choice pins the source fraction for the cases
        where softness matters more than speed.
        """
        self.set_property(
            "decode_quality",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=DecodeQuality.Auto,
                priority=55,
                group="Quality",
                label="Decode Quality",
                description=(
                    "How much of the source resolution is decoded. Auto "
                    "matches the Viewer width, so no pixel is decoded that "
                    "cannot be displayed — the fastest setting, and the "
                    "reason a 4K source can play at preview size."
                ),
            ),
        )
        self.set_property(
            "decode_width",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=0,
                slider_min_value=0,
                slider_max_value=8192,
                priority=56,
                group="Quality",
                label="Decode Width Cap",
                description=(
                    "Hard ceiling on decoded frame width; 0 disables it. "
                    "Use for very large sources (8K, screen recordings) "
                    "where even full quality is not a realistic ask."
                ),
                suffix=" px",
            ),
        )
        self.set_property(
            "decode_threads",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=0,
                slider_min_value=0,
                slider_max_value=64,
                priority=57,
                group="Quality",
                label="Decode Threads",
                description=(
                    "Decoder worker threads; 0 uses the codec's own default. "
                    "Raise it when decoding saturates one core, lower it "
                    "when several sources compete for CPU. Applies the next "
                    "time the file is opened."
                ),
            ),
        )
        self.set_property(
            "use_proxy",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=58,
                group="Quality",
                label="Use Proxy",
                description=(
                    "Read from a generated editing proxy when one is "
                    "available, when proxies are also enabled globally in "
                    "Preferences."
                ),
            ),
        )

    def _apply_decode_preferences(self) -> None:
        """Push this node's quality properties into its decoder.

        Called on every open so the decoder sees the current values before
        the first frame is read — threads in particular are fixed when the
        codec context is created and cannot be changed afterwards.
        """
        quality = self._enum_prop("decode_quality", DecodeQuality)
        self._decoder.set_decode_preferences(
            quality_scale=DECODE_QUALITY_SCALE.get(quality, None),
            width_cap=self._int_prop("decode_width", 0),
            threads=self._int_prop("decode_threads", 0),
        )

    def prepare_evaluation(
        self,
        width: int,
        height: int,
        preview_max_width: int = 960,
        project_fps: float = 0.0,
        frame_num: int = 0,
        project_max_frame: int = 0,
    ) -> None:
        """Store project size, fps, and active Viewer proxy width for decode."""
        super().prepare_evaluation(
            width,
            height,
            preview_max_width=preview_max_width,
            project_fps=project_fps,
            frame_num=frame_num,
            project_max_frame=project_max_frame,
        )
        self._preview_max_width = max(0, int(preview_max_width))

    def blank_frame(self) -> np.ndarray:
        """Blank frame sized to the active preview proxy when possible.

        The dtype follows the active output representation so that error,
        blank, and hold-previous frames never mix representations inside a
        single graph evaluation.
        """
        if self._preview_max_width > 0 and self._eval_width > 0:
            width = min(self._eval_width, self._preview_max_width)
            scale = width / float(self._eval_width)
            height = max(1, round(self._eval_height * scale))
            return np.zeros((height, width, 3), dtype=self._output_dtype)
        return super().blank_frame()

    def handle_error_frame(self) -> np.ndarray:
        on_error = self.get_property("on_error")
        error_method = on_error.value if on_error else VideoFrameErrorMethod.Black

        if (
            error_method == VideoFrameErrorMethod.HoldPrevious
            and self._previous_frame is not None
        ):
            return self._previous_frame

        return self.blank_frame()

    def _bool_prop(self, key: str, default: bool) -> bool:
        prop = self.get_property(key)
        if prop is None or prop.value is None:
            return default
        return bool(prop.value)

    def _int_prop(self, key: str, default: int) -> int:
        prop = self.get_property(key)
        if prop is None or prop.value is None:
            return default
        return int(prop.value)

    def _float_prop(self, key: str, default: float) -> float:
        prop = self.get_property(key)
        if prop is None or prop.value is None:
            return default
        return float(prop.value)

    def _edge_mode(self, key: str, default: MediaEdgeMode) -> MediaEdgeMode:
        prop = self.get_property(key)
        if prop is not None and isinstance(prop.value, MediaEdgeMode):
            return prop.value
        return default

    def _enum_prop(self, key: str, enum_type: type[IntEnum]) -> IntEnum:
        """Return an enum property's value, falling back to its first member.

        Saved projects can carry a member name from a newer build, and a
        missing enum must not take the node down — a decode quality is a
        preference, not a contract.
        """
        prop = self.get_property(key)
        value = prop.value if prop is not None else None
        if isinstance(value, enum_type):
            return value
        try:
            return next(iter(enum_type))
        except StopIteration:  # pragma: no cover - enums are never empty
            return value

    def decode_quality(self) -> DecodeQuality:
        """Return this source's decode-quality setting."""
        return self._enum_prop("decode_quality", DecodeQuality)  # type: ignore[return-value]

    def decode_status(self) -> dict[str, object]:
        """Describe the active decode configuration for diagnostics."""
        status: dict[str, object] = dict(self._decoder.decode_status())
        status["use_proxy"] = self._bool_prop("use_proxy", True)
        return status

    def _file_path(self) -> str:
        file_prop = self.get_property("file_path")
        return str((file_prop.value if file_prop else "") or "")

    def _is_proxy_available(self) -> bool:
        """Return whether a verified proxy exists for the current file.

        Used only for the node's status text; the actual substitution is
        decided inside the decoder so a stale proxy can be rejected there.
        """
        path = self._file_path()
        if not path:
            return False
        try:
            from core.media.proxy import get_proxy_manager

            return get_proxy_manager().lookup_with_info(path) is not None
        except Exception:  # noqa: BLE001 - proxies are strictly optional
            return False

    def _ensure_open(self) -> MediaInfo | None:
        path = self._file_path()
        if not path:
            self._decoder.close()
            return None
        self._apply_decode_preferences()
        return self._decoder.open(path, use_proxy=self._bool_prop("use_proxy", True))

    def probe_media(self) -> tuple[float, float, int, int] | None:
        """Return ``(fps, duration_sec, width, height)`` for the current file."""
        try:
            info = self._ensure_open()
            if info is None or info.duration_sec <= 0.0:
                return None
            return info.fps, info.duration_sec, info.width, info.height
        except Exception as e:  # noqa: BLE001
            self.log_exception(e)
            return None

    def _media_range(self, frame_count: int) -> tuple[int, int]:
        """Return inclusive ``(start, end)`` clamped to the media."""
        start = max(0, self._int_prop("start_frame", 0))
        end_value = self._int_prop("end_frame", -1)
        last = max(0, frame_count - 1)
        end = last if end_value < 0 else min(last, end_value)
        start = min(start, end)
        return start, end

    def _apply_edge(
        self,
        local: float,
        *,
        start: int,
        end: int,
        range_len: int,
        mode: MediaEdgeMode,
    ) -> int | None:
        """Map an out-of-range local index into a source frame, or ``None`` for black."""
        if mode == MediaEdgeMode.Black:
            return None
        if mode == MediaEdgeMode.Hold:
            if local < 0:
                return start
            return end
        # Loop within the active range.
        wrapped = local % float(range_len)
        if wrapped < 0:
            wrapped += float(range_len)
        return start + int(wrapped)

    def _resolve_source_frame(
        self,
        frame_num: int,
        frame_count: int,
        source_fps: float,
    ) -> int | None:
        """Map timeline frame → media frame using range, fps, speed, and edges."""
        start, end = self._media_range(frame_count)
        range_len = end - start + 1
        if range_len <= 0:
            return None

        project_fps = max(1.0, float(self._project_fps))
        play_fps = self._float_prop("fps", 0.0)
        if play_fps <= 0.0:
            play_fps = source_fps if source_fps > 0.0 else project_fps
        speed = max(0.01, self._float_prop("speed", 1.0))
        offset = self._int_prop("frame_offset", 0)

        timeline_time = (float(frame_num) + float(offset)) / project_fps
        local = timeline_time * play_fps * speed
        if self._bool_prop("reverse", False):
            local = float(range_len - 1) - local

        if local < 0.0:
            return self._apply_edge(
                local,
                start=start,
                end=end,
                range_len=range_len,
                mode=self._edge_mode("before_start", MediaEdgeMode.Black),
            )
        if local > float(range_len - 1):
            return self._apply_edge(
                local,
                start=start,
                end=end,
                range_len=range_len,
                mode=self._edge_mode("after_end", MediaEdgeMode.Hold),
            )
        return start + int(local)

    def evaluate(self, frame_num: int) -> FrameWithAudio:
        if not self._bool_prop("enabled", True):
            frame = self.blank_frame()
            audio = self._get_silence_audio()
            return FrameWithAudio(frame=frame, audio=audio)

        path = self._file_path()
        if not path:
            frame = self.blank_frame()
            audio = self._get_silence_audio()
            return FrameWithAudio(frame=frame, audio=audio)

        try:
            info = self._ensure_open()
            if info is None:
                frame = self.handle_error_frame()
                audio = self._get_silence_audio()
                return FrameWithAudio(frame=frame, audio=audio)

            source_frame = self._resolve_source_frame(
                frame_num,
                info.frame_count,
                info.fps,
            )
            if source_frame is None:
                frame = self.blank_frame()
                audio = self._get_silence_audio()
                return FrameWithAudio(frame=frame, audio=audio)

            frame_u8 = self._decoder.read_rgb(source_frame, self._preview_max_width)
            if frame_u8 is None:
                frame = self.handle_error_frame()
                audio = self._get_silence_audio()
                return FrameWithAudio(frame=frame, audio=audio)

            # Hand over the decoder's own buffer when the compiled plan
            # proved the path to the Viewer tolerates 8-bit input. This
            # skips a full-frame promote (astype + multiply) and lets the
            # frame cache hold 4x more source frames per byte budget.
            #
            # ``ensure_rgb_f32`` produces bit-identical values on the first
            # node that needs float precision, so nothing downstream can
            # tell the difference.
            frame: np.ndarray = (
                frame_u8 if self._emit_u8_allowed else from_source_u8(frame_u8)
            )
            self._previous_frame = self._current_frame
            self._current_frame = frame

            # Get audio for this frame
            audio = self._decoder.read_audio(source_frame)
            if audio is None:
                audio = self._get_silence_audio()
            else:
                # Apply audio controls
                audio = self._process_audio(audio)

            return FrameWithAudio(frame=frame, audio=audio)

        except Exception as e:  # noqa: BLE001
            self.log_exception(e)
            frame = self.handle_error_frame()
            audio = self._get_silence_audio()
            return FrameWithAudio(frame=frame, audio=audio)

    def _get_silence_audio(self) -> AudioData:
        """Get silence audio data for the current frame duration."""
        duration_per_frame = 1.0 / max(self._project_fps, 1.0)
        # Try to get audio info from decoder for correct sample rate/channels
        info = self._decoder.info()
        if info and info.has_audio:
            return AudioData.silence(
                duration=duration_per_frame,
                sample_rate=info.audio_sample_rate,
                channels=info.audio_channels
            )
        return AudioData.silence(duration=duration_per_frame)

    def _process_audio(self, audio: AudioData) -> AudioData:
        """Apply audio controls (volume, channel mode) to audio data."""
        if not self._bool_prop("audio_enabled", True):
            return AudioData.silence(
                duration=audio.duration,
                sample_rate=audio.sample_rate,
                channels=audio.num_channels
            )

        # Apply volume
        volume = self._float_prop("audio_volume", 100.0) / 100.0
        if abs(volume - 1.0) >= 0.001:
            samples = audio.samples * volume
            samples = np.clip(samples, -1.0, 1.0)
        else:
            samples = audio.samples

        # Apply channel mode
        channel_mode = self.get_property("audio_channel_mode")
        if channel_mode is not None and isinstance(channel_mode.value, AudioChannelMode):
            if channel_mode.value == AudioChannelMode.Mono and audio.num_channels > 1:
                # Mix down to mono by averaging channels
                if samples.ndim == 2:
                    samples = np.mean(samples, axis=1, keepdims=True)

        return AudioData(samples=samples.astype(np.float32), sample_rate=audio.sample_rate)

    def preview_audio_chunk(
        self,
        frame_num: int,
        *,
        duration_frames: int = 6,
    ) -> AudioData:
        """Return a forward contiguous audio chunk for preview playback."""
        info = self._ensure_open()
        if info is None:
            duration = max(1, int(duration_frames)) / max(float(self._project_fps), 1.0)
            return AudioData.silence(duration=duration)

        source_frame = self._resolve_source_frame(
            frame_num,
            info.frame_count,
            info.fps,
        )
        if source_frame is None:
            duration = max(1, int(duration_frames)) / max(float(self._project_fps), 1.0)
            return self._get_silence_audio() if duration_frames <= 1 else AudioData.silence(
                duration=duration,
                sample_rate=info.audio_sample_rate,
                channels=info.audio_channels,
            )

        project_fps = max(float(self._project_fps), 1.0)
        seconds_per_frame = 1.0 / project_fps
        chunk_duration = max(1, int(duration_frames)) * seconds_per_frame
        start_time = float(source_frame) / max(float(info.fps) if info.fps > 0 else float(DEFAULT_FPS), 0.001)
        audio = self._decoder.read_audio_range(start_time, chunk_duration)
        if audio is None:
            return AudioData.silence(
                duration=chunk_duration,
                sample_rate=info.audio_sample_rate,
                channels=info.audio_channels,
            )
        return self._process_audio(audio)

    def close(self) -> None:
        """Release the underlying decoder (call when removing the node)."""
        self._decoder.close()
