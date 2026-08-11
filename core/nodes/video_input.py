"""Video file input node."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.nodes.base import (
    Node,
    NodeProperty,
    NodePropertyInputType,
    NodeSocketType,
    VideoFrameErrorMethod,
)


class VideoInputNode(Node):
    """Acts as an input source for a video stream."""

    node_type = "Video Input"
    node_category = "Input/Output"
    node_description = "Acts as an input source for video stream"
    node_color = (50, 150, 50)

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self._previous_frame: np.ndarray | None = None
        self._current_frame: np.ndarray | None = None
        self._video_clip: Any = None
        self._last_file_path: str | None = None

    def _setup_sockets(self) -> None:
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "file_path",
            NodeProperty(input_type=NodePropertyInputType.File, value=""),
        )
        self.set_property(
            "on_error",
            NodeProperty(
                input_type=NodePropertyInputType.VideoFrameErrorMethod,
                value=VideoFrameErrorMethod.Black,
            ),
        )

    def handle_error_frame(self) -> np.ndarray:
        on_error = self.get_property("on_error")
        error_method = on_error.value if on_error else VideoFrameErrorMethod.Black

        if (
            error_method == VideoFrameErrorMethod.HoldPrevious
            and self._previous_frame is not None
        ):
            return self._previous_frame

        return self.blank_frame()

    def evaluate(self, frame_num: int) -> np.ndarray:
        file_prop = self.get_property("file_path")
        file_path = (file_prop.value if file_prop else "") or ""
        if not file_path:
            return self.blank_frame()

        try:
            from moviepy import VideoFileClip

            if file_path != self._last_file_path:
                if self._video_clip is not None:
                    self._video_clip.close()
                self._video_clip = VideoFileClip(file_path)
                self._last_file_path = file_path

            if self._video_clip is None:
                return self.handle_error_frame()

            fps = self._video_clip.fps or 30.0
            time_sec = frame_num / fps
            frame = self._video_clip.get_frame(time_sec)

            self._previous_frame = self._current_frame
            self._current_frame = frame
            return frame.astype(np.uint8) if frame.dtype != np.uint8 else frame

        except Exception as e:  # noqa: BLE001
            self.log_exception(e)
            return self.handle_error_frame()
