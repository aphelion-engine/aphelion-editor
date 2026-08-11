"""Base node types, sockets, and property definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Any

import numpy as np

from config.constants import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH


class NodeSocketType(IntEnum):
    Frame = auto()
    Number = auto()
    Color = auto()


class VideoFrameErrorMethod(IntEnum):
    Black = auto()
    HoldPrevious = auto()
    NextFrame = auto()


class MediaLoopMode(IntEnum):
    """Legacy clamp/loop mode (prefer ``MediaEdgeMode`` on new nodes)."""

    Clamp = auto()
    Loop = auto()


class MediaEdgeMode(IntEnum):
    """What to show when sampling outside the active media range."""

    Black = auto()
    Hold = auto()
    Loop = auto()


class NodePropertyInputType(IntEnum):
    Number = auto()
    Slider = auto()
    File = auto()
    Checkbox = auto()
    CustomChoice = auto()
    VideoFrameErrorMethod = auto()
    NodeSocketType = auto()


@dataclass
class NodeProperty:
    input_type: NodePropertyInputType
    value: Any | None
    slider_min_value: int | float = 0.0
    slider_max_value: int | float = 0.0
    # Lower numbers appear first in the properties panel.
    priority: int = 100

    def to_dict(self) -> dict[str, Any]:
        from core.serialization import encode_value

        return {
            "input_type": self.input_type.name,
            "value": encode_value(self.value),
            "slider_min_value": self.slider_min_value,
            "slider_max_value": self.slider_max_value,
            "priority": self.priority,
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
        self._project_fps: float = float(DEFAULT_FPS)

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

    def prepare_evaluation(
        self,
        width: int,
        height: int,
        preview_max_width: int = 0,
        project_fps: float = 0.0,
    ) -> None:
        """Prepare per-evaluation size; ``preview_max_width`` is used by decoders."""
        _ = preview_max_width
        self._eval_width = width
        self._eval_height = height
        if project_fps > 0.0:
            self._project_fps = float(project_fps)

    def blank_frame(self) -> np.ndarray:
        return np.zeros((self._eval_height, self._eval_width, 3), dtype=np.uint8)

    def log_exception(self, e: Exception) -> None:
        """Record ``e`` on the node and emit it to the app logger."""
        from utils.logging_setup import get_logger

        self.exception_log.append(e)
        get_logger("nodes").error(
            "Node %s (%s) error: %s",
            self.name,
            self.node_type,
            e,
            exc_info=e,
        )

    @abstractmethod
    def evaluate(self, frame_num: int) -> np.ndarray:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Serialize this node for project documents (``.aph``).

        Sockets are omitted — they are reconstructed from the node class.
        Property values use stable enum encoding via ``core.serialization``.
        """
        from core.serialization import encode_value

        properties: dict[str, Any] = {}
        for key, prop in self.properties.items():
            if key.startswith("_input_"):
                continue
            properties[key] = encode_value(prop.value)

        return {
            "node_type": self.node_type,
            "node_category": self.node_category,
            "name": self.name,
            "x": float(self.x),
            "y": float(self.y),
            "properties": properties,
        }

    def apply_document(self, data: dict[str, Any]) -> None:
        """Apply serialized name, position, and property values onto this instance."""
        from core.serialization import decode_properties

        self.name = str(data.get("name", self.name))
        self.x = float(data.get("x", self.x))
        self.y = float(data.get("y", self.y))
        # Legacy documents may store position as a pair.
        position = data.get("position")
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            self.x = float(position[0])
            self.y = float(position[1])

        raw_props = data.get("properties", {})
        if not isinstance(raw_props, dict):
            return
        defaults = {key: prop.value for key, prop in self.properties.items()}
        restored = decode_properties(raw_props, defaults=defaults)
        for key, value in restored.items():
            if key in self.properties:
                self.set_property(key, value)
