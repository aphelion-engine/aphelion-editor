"""Video file input node — OpenCV decode with sequential playback."""

from __future__ import annotations

import numpy as np

from config.constants import DEFAULT_PREVIEW_MAX_WIDTH
from core.nodes.base import (
    FRAME_DTYPE,
    MediaEdgeMode,
    Node,
    NodeProperty,
    NodePropertyInputType,
    NodeSocketType,
    VideoFrameErrorMethod,
)
from effects.frame_ops import from_source_u8
from render.video_decoder import MediaInfo, VideoDecoder


class VideoInputNode(Node):
    """Acts as an input source for a video stream."""

    node_type = "Video Input"
    node_category = "Input/Output"
    node_description = "Acts as an input source for video stream"
    node_color = (50, 150, 50)

    def __init__(self, name: str | None = None) -> None:
        self._decoder: VideoDecoder = VideoDecoder()
        self._previous_frame: np.ndarray | None = None
        self._current_frame: np.ndarray | None = None
        self._preview_max_width: int = DEFAULT_PREVIEW_MAX_WIDTH
        super().__init__(name)

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
        """Blank frame sized to the active preview proxy when possible."""
        if self._preview_max_width > 0 and self._eval_width > 0:
            width = min(self._eval_width, self._preview_max_width)
            scale = width / float(self._eval_width)
            height = max(1, round(self._eval_height * scale))
            return np.zeros((height, width, 3), dtype=FRAME_DTYPE)
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

    def _file_path(self) -> str:
        file_prop = self.get_property("file_path")
        return str((file_prop.value if file_prop else "") or "")

    def _ensure_open(self) -> MediaInfo | None:
        path = self._file_path()
        if not path:
            self._decoder.close()
            return None
        return self._decoder.open(path)

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

    def evaluate(self, frame_num: int) -> np.ndarray:
        if not self._bool_prop("enabled", True):
            return self.blank_frame()

        path = self._file_path()
        if not path:
            return self.blank_frame()

        try:
            info = self._ensure_open()
            if info is None:
                return self.handle_error_frame()

            source_frame = self._resolve_source_frame(
                frame_num,
                info.frame_count,
                info.fps,
            )
            if source_frame is None:
                return self.blank_frame()

            frame_u8 = self._decoder.read_rgb(source_frame, self._preview_max_width)
            if frame_u8 is None:
                return self.handle_error_frame()

            frame: np.ndarray = from_source_u8(frame_u8)
            self._previous_frame = self._current_frame
            self._current_frame = frame
            return frame
        except Exception as e:  # noqa: BLE001
            self.log_exception(e)
            return self.handle_error_frame()

    def close(self) -> None:
        """Release the underlying decoder (call when removing the node)."""
        self._decoder.close()
