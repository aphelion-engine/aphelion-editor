"""Base node types, sockets, and property definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Any

import numpy as np

from config.constants import DEFAULT_HEIGHT, DEFAULT_WIDTH


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

    node_description: str = ""
    node_category: str = "Misc"
    node_type: str = "BaseNode"
    node_color: tuple[int, int, int] = (100, 100, 100)

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
        return

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
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": (self.x, self.y),
            "size": (self.width, self.height),
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "outputs": {k: v.to_dict() for k, v in self.outputs.items()},
            "properties": {k: prop.to_dict() for k, prop in self.properties.items()},
        }
