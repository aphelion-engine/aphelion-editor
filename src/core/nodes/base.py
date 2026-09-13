"""Base node types, sockets, and property definitions."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Any

import numpy as np
from config.constants import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH
from core.animation import AnimationCurve
from core.audio import AudioData, FrameWithAudio

NodeValue = np.ndarray | float | AudioData | FrameWithAudio | dict[str, float | AudioData | FrameWithAudio]
TimeResampler = Callable[[int], Any]
PropertyResolver = Callable[[str, str], "float | None"]
NodePropertyResolver = Callable[[str, str], "float | None"]
PropertyDriveLookup = Callable[[str], "float | None"]


class NodeSocketType(IntEnum):
    Frame = auto()
    Mask = auto()
    Number = auto()
    Color = auto()
    Node = auto()   # Legacy node-reference socket
    Audio = auto()
    Any = auto()    # NEW: Accept ANY output type (used for PropertyDrive/Link)


FRAME_DTYPE: np.dtype = np.dtype(np.float32)


class VideoFrameErrorMethod(IntEnum):
    Black = auto()
    HoldPrevious = auto()
    NextFrame = auto()


class MediaLoopMode(IntEnum):
    Clamp = auto()
    Loop = auto()


class MediaEdgeMode(IntEnum):
    Black = auto()
    Hold = auto()
    Loop = auto()


class NodePropertyInputType(IntEnum):
    Number = auto()
    Slider = auto()
    File = auto()
    Checkbox = auto()
    Color = auto()
    CustomChoice = auto()
    VideoFrameErrorMethod = auto()
    NodeSocketType = auto()
    Text = auto()
    NodePropertyChoice = auto()
    ImageFile = auto()
    Custom = auto()


ColorRgb = tuple[int, int, int]
NEUTRAL_COLOR_RGB: ColorRgb = (128, 128, 128)
WHITE_COLOR_RGB: ColorRgb = (255, 255, 255)


@dataclass
class NodeProperty:
    input_type: NodePropertyInputType
    value: Any | None
    slider_min_value: int | float = 0.0
    slider_max_value: int | float = 0.0
    priority: int = 100
    group: str = "General"
    label: str | None = None
    description: str = ""
    suffix: str = ""
    custom_widget_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        from core.serialization import encode_value

        return {
            "input_type": self.input_type.name,
            "value": encode_value(self.value),
            "slider_min_value": self.slider_min_value,
            "slider_max_value": self.slider_max_value,
            "priority": self.priority,
            "group": self.group,
            "label": self.label,
            "description": self.description,
            "suffix": self.suffix,
            "custom_widget_id": self.custom_widget_id,
        }


class NodeSocket:
    """Input / output socket for nodes."""

    def __init__(self, name: str, socket_type: NodeSocketType, is_input: bool = False) -> None:
        self.name = name
        self.socket_type = socket_type
        self.is_input = is_input

    def is_node_reference_socket(self) -> bool:
        """Node and Any both behave as node-reference sockets."""
        return self.socket_type in (NodeSocketType.Node, NodeSocketType.Any)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.socket_type.name,
            "is_input": self.is_input,
        }


class PreviewCost(IntEnum):
    """Rough execution cost class used by the interactive preview governor.

    Nodes declare this instead of the engine hard-coding a list of "slow"
    node types. The governor uses it to decide what to scale back first when
    a frame cannot meet its deadline, and the graph complexity readout uses
    it to tell the user when a composition needs caching.
    """

    LIGHT = 0
    MEDIUM = 1
    HEAVY = 2
    EXTREME = 3


class Node(ABC):
    """Base class for all nodes.

    Engine capability declarations
    ------------------------------
    These class attributes let the compiled render plan
    (``core.render_plan``) make execution decisions *before* any frame is
    evaluated, instead of the engine guessing at runtime.

    ``accepts_u8_frame``
        The node tolerates a raw 8-bit RGB frame on its frame inputs — it
        promotes via ``ensure_rgb_f32`` itself. Declaring this is what
        allows a source to skip the eager float promotion and hand its
        decoded frame straight over. **Defaults to False**: a node that has
        not been verified keeps the old, always-float behaviour, so opting
        in is a deliberate, reviewable act rather than an accident.

    ``can_emit_u8_frame``
        The node originates frames and is able to hand them over in raw
        8-bit form when the plan proves every downstream node tolerates it.

    ``preserves_frame_dtype``
        The node's output dtype follows its input dtype (pure routing).

    ``is_static_output``
        The output cannot change while the frame number changes, so it may
        be cached indefinitely until a parameter or upstream input changes.

    ``is_temporal``
        The node reads frames other than the requested one (motion blur,
        temporal denoise, ...). Forces sequential evaluation during export
        and blocks parallel frame rendering.
    """

    node_description: str = ""
    node_category: str = "Misc"
    node_type: str = "BaseNode"
    node_color: tuple[int, int, int] = (100, 100, 100)

    #: Preview cost class, used by the adaptive quality governor.
    preview_cost: PreviewCost = PreviewCost.MEDIUM

    #: Whether ``evaluate`` tolerates a raw uint8 RGB frame on frame inputs.
    accepts_u8_frame: bool = False

    #: Whether this node can originate raw uint8 frames.
    can_emit_u8_frame: bool = False

    #: Whether the output dtype simply follows the input dtype.
    preserves_frame_dtype: bool = False

    #: Whether the output is independent of the frame number.
    is_static_output: bool = False

    #: Whether the node reads neighbouring frames.
    is_temporal: bool = False

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.node_type
        self.x: float = 0
        self.y: float = 0
        self.width: int = 150
        self.height: int = 100

        self.inputs: dict[str, NodeSocket] = {}
        self.outputs: dict[str, NodeSocket] = {}
        self.properties: dict[str, NodeProperty] = {}
        self.animated_properties: dict[str, AnimationCurve] = {}
        self._input_values: dict[str, Any] = {}
        self._eval_width: int = DEFAULT_WIDTH
        self._eval_height: int = DEFAULT_HEIGHT
        self._preview_max_width: int = 0
        self._project_fps: float = float(DEFAULT_FPS)
        self._project_max_frame: int = 0
        self._current_frame_num: int = 0
        self._time_resampler: TimeResampler | None = None
        self._property_resolver: PropertyResolver | None = None
        self._node_property_resolver: NodePropertyResolver | None = None
        self._property_drive_lookup: PropertyDriveLookup | None = None

        # Reusable evaluation helpers. ``Project`` binds these once per
        # node instead of allocating a fresh closure for every node on
        # every evaluated frame, which matters for long exports.
        self._drive_lookup: Any = None
        self._eval_resampler: Any = None

        # Set by ``Project`` from the compiled render plan, once per
        # evaluation tree. False means "promote eagerly", which is the
        # historical behaviour and the safe default.
        self._emit_u8_allowed: bool = False

        self.exception_log: list[Exception] = []
        self._setup_sockets()

    def _setup_sockets(self) -> None:
        return

    def add_input(self, name: str, socket_type: NodeSocketType) -> None:
        """Allow Any to accept ANY output type."""
        if socket_type == NodeSocketType.Node:
            socket_type = NodeSocketType.Any
        self.inputs[name] = NodeSocket(name, socket_type, is_input=True)

    def add_output(self, name: str, socket_type: NodeSocketType) -> None:
        self.outputs[name] = NodeSocket(name, socket_type, is_input=False)

    def set_property(self, key: str, value: Any | NodeProperty, input_type: NodePropertyInputType | None = None) -> None:
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

    def input_required(self, slot: str) -> bool:
        """Whether evaluating outputs needs this connected input."""
        return True

    def get_input_value(self, slot: str) -> Any | None:
        return self._input_values.get(slot)

    def clear_input_values(self) -> None:
        self._input_values.clear()

    def prepare_evaluation(
        self,
        width: int,
        height: int,
        preview_max_width: int = 0,
        project_fps: float = 0.0,
        frame_num: int = 0,
        project_max_frame: int = 0,
    ) -> None:
        self._eval_width = width
        self._eval_height = height
        self._preview_max_width = max(0, int(preview_max_width))
        if project_fps > 0.0:
            self._project_fps = float(project_fps)
        self._project_max_frame = max(0, int(project_max_frame))
        self._current_frame_num = int(frame_num)

    def set_time_resampler(self, resampler: TimeResampler | None) -> None:
        self._time_resampler = resampler

    def resample_frame(self, frame_num: int) -> Any | None:
        if self._time_resampler is None:
            return None
        return self._time_resampler(int(frame_num))

    def set_property_resolver(self, resolver: PropertyResolver | None) -> None:
        self._property_resolver = resolver

    def set_node_property_resolver(self, resolver: NodePropertyResolver | None) -> None:
        self._node_property_resolver = resolver

    def set_property_drive_lookup(self, lookup: PropertyDriveLookup | None) -> None:
        self._property_drive_lookup = lookup

    def property_drive_value(self, key: str) -> float | None:
        if self._property_drive_lookup is None:
            return None
        return self._property_drive_lookup(key)

    def resolve_named_property(self, node_name: str, property_key: str) -> float | None:
        if self._property_resolver is None:
            return None
        return self._property_resolver(node_name, property_key)

    def resolve_node_property(self, node_id: str, property_key: str) -> float | None:
        if self._node_property_resolver is None:
            return None
        return self._node_property_resolver(node_id, property_key)

    def evaluation_frame_size(self) -> tuple[int, int]:
        width: int = max(1, self._eval_width)
        height: int = max(1, self._eval_height)
        if self._preview_max_width <= 0 or width <= self._preview_max_width:
            return width, height
        scale: float = self._preview_max_width / float(width)
        return self._preview_max_width, max(1, round(height * scale))

    def blank_frame(self) -> np.ndarray:
        return np.zeros((self._eval_height, self._eval_width, 3), dtype=FRAME_DTYPE)

    def log_exception(self, e: Exception) -> None:
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
    def evaluate(self, frame_num: int) -> NodeValue:
        raise NotImplementedError

    def snapshot_data(self) -> dict[str, Any]:
        """Return extra state needed to recreate this node for undo / copy.

        The base implementation returns nothing because most nodes are fully
        described by ``node_type`` plus their serialized properties. Nodes
        that own non-property state (for example a custom node's embedded
        subgraph definition) override this so undo, redo, duplicate, and
        copy/paste all preserve it.
        """
        return {}

    def restore_snapshot_data(self, data: dict[str, Any]) -> None:
        """Restore state previously produced by :meth:`snapshot_data`."""
        return

    def to_dict(self) -> dict[str, Any]:
        from core.serialization import encode_value

        properties: dict[str, Any] = {}
        for key, prop in self.properties.items():
            if key.startswith("_input_"):
                continue
            properties[key] = encode_value(prop.value)

        animated: dict[str, Any] = {
            key: curve.to_dict()
            for key, curve in self.animated_properties.items()
            if not curve.is_empty
        }

        return {
            "node_type": self.node_type,
            "node_category": self.node_category,
            "name": self.name,
            "x": float(self.x),
            "y": float(self.y),
            "properties": properties,
            "animated_properties": animated,
        }

    def apply_document(self, data: dict[str, Any]) -> None:
        from core.serialization import decode_properties

        self.name = str(data.get("name", self.name))
        self.x = float(data.get("x", self.x))
        self.y = float(data.get("y", self.y))

        position = data.get("position")
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            self.x = float(position[0])
            self.y = float(position[1])

        raw_props = data.get("properties", {})
        if isinstance(raw_props, dict):
            defaults = {key: prop.value for key, prop in self.properties.items()}
            restored = decode_properties(raw_props, defaults=defaults)
            for key, value in restored.items():
                if key in self.properties:
                    self.set_property(key, value)

        raw_curves = data.get("animated_properties", {})
        if isinstance(raw_curves, dict):
            for key, curve_data in raw_curves.items():
                if key not in self.properties or not isinstance(curve_data, dict):
                    continue
                curve = AnimationCurve.from_dict(curve_data)
                if not curve.is_empty:
                    self.animated_properties[key] = curve
