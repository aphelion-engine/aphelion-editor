from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Any

import numpy as np

from core.constants import DEFAULT_HEIGHT, DEFAULT_WIDTH


class NodeSocketType(IntEnum):
    Frame = auto()
    Number = auto()
    Color = auto()


class VideoFrameErrorMethod(IntEnum):
    Black = auto()
    HoldPrevious = auto()
    NextFrame = auto()


class NodePropertyInputType(IntEnum):
    Number = auto()
    Slider = auto()
    File = auto()
    CustomChoice = auto()
    VideoFrameErrorMethod = auto()
    NodeSocketType = auto()


@dataclass
class NodeProperty:
    input_type: NodePropertyInputType
    value: Any | None
    slider_min_value: int | float = 0.0
    slider_max_value: int | float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_type": self.input_type.name,
            "value": self.value,
            "slider_min_value": self.slider_min_value,
            "slider_max_value": self.slider_max_value,
        }


class NodeSocket:
    """Input / output socket for nodes."""

    def __init__(
        self,
        name: str,
        socket_type: NodeSocketType,
        is_input: bool = False,
    ) -> None:
        self.name = name
        self.socket_type = socket_type
        self.is_input = is_input

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.socket_type.name,
            "is_input": self.is_input,
        }


class Node(ABC):
    """Base class for all nodes."""

    node_description = ""
    node_category = "Misc"
    node_type = "BaseNode"
    node_color = (100, 100, 100)

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.node_type
        self.x: float = 0
        self.y: float = 0
        self.width = 150
        self.height = 100

        self.inputs: dict[str, NodeSocket] = {}
        self.outputs: dict[str, NodeSocket] = {}
        self.properties: dict[str, NodeProperty] = {}
        self._input_values: dict[str, Any] = {}
        self._eval_width = DEFAULT_WIDTH
        self._eval_height = DEFAULT_HEIGHT

        self.exception_log: list[Exception] = []
        self._setup_sockets()

    def _setup_sockets(self) -> None:
        pass  # noqa: PIE790

    def add_input(self, name: str, socket_type: NodeSocketType) -> None:
        self.inputs[name] = NodeSocket(name, socket_type, is_input=True)

    def add_output(self, name: str, socket_type: NodeSocketType) -> None:
        self.outputs[name] = NodeSocket(name, socket_type, is_input=False)

    def set_property(
        self,
        key: str,
        value: Any | NodeProperty,
        input_type: NodePropertyInputType | None = None,
    ) -> None:
        if isinstance(value, NodeProperty):
            self.properties[key] = value
        elif key in self.properties:
            self.properties[key].value = value
        else:
            self.properties[key] = NodeProperty(
                input_type=input_type or NodePropertyInputType.Number,
                value=value,
            )

    def get_property(self, key: str) -> NodeProperty | None:
        return self.properties.get(key)

    def set_input_value(self, slot: str, value: Any) -> None:
        self._input_values[slot] = value

    def get_input_value(self, slot: str) -> Any | None:
        return self._input_values.get(slot)

    def prepare_evaluation(self, width: int, height: int) -> None:
        self._eval_width = width
        self._eval_height = height

    def blank_frame(self) -> np.ndarray:
        return np.zeros((self._eval_height, self._eval_width, 3), dtype=np.uint8)

    def log_exception(self, e: Exception) -> None:
        self.exception_log.append(e)

    @abstractmethod
    def evaluate(self, frame_num: int) -> np.ndarray:
        pass  # noqa: PIE790

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": (self.x, self.y),
            "size": (self.width, self.height),
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "outputs": {k: v.to_dict() for k, v in self.outputs.items()},
            "properties": {k: prop.to_dict() for k, prop in self.properties.items()},
        }


class VideoInputNode(Node):
    node_type = "Video Input"
    node_category = "Input/Output"
    node_description = "Acts as an input source for video stream"
    node_color = (50, 150, 50)

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self._previous_frame: np.ndarray | None = None
        self._current_frame: np.ndarray | None = None
        self._video_clip = None
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
        error_method = (
            on_error.value if on_error else VideoFrameErrorMethod.Black
        )

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
                if self._video_clip:
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


class ViewerNode(Node):
    node_type = "Viewer"
    node_category = "Input/Output"
    node_description = "Connects to an input source to view a video stream"
    node_color = (200, 50, 50)

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        input_frame = self.get_input_value("frame")
        if input_frame is None:
            return self.blank_frame()
        return input_frame
