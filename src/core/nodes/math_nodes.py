"""Scalar Number-socket nodes: constants, arithmetic, and property extraction.

These are the building blocks for "property modulation" — a keyframed
``ValueNode``, a tracker, or a ``PropertyLinkNode`` can all feed a live
number into any other node's exposed modulation input (see
``FrameNode.expose_modulation_input``).
"""

from __future__ import annotations

import math
from typing import Any

from core.nodes.base import NodeSocketType, NodeValue
from core.nodes.enums import MathFunction, MathOperation
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (
    choice_property,
    node_property_choice_property,
    number_property,
    toggle_property,
)
from core.nodes.property_link import (
    PROPERTY_DRIVE_PROPERTY_KEY,
    PROPERTY_DRIVE_TARGET_SLOT,
    PROPERTY_DRIVE_VALUE_SLOT,
    PROPERTY_LINK_PROPERTY_KEY,
    PROPERTY_LINK_SOURCE_SLOT,
)

MATH_CATEGORY: str = "Math"


class ValueNode(FrameNode):
    """Emit a single keyframeable scalar as a Number output."""

    node_type: str = "Value"
    node_category: str = MATH_CATEGORY
    node_description: str = "A single animatable number, usable to drive other properties"
    node_color: tuple[int, int, int] = (92, 150, 168)

    def _setup_sockets(self) -> None:
        """Register the Number output and its backing value."""
        self.add_output("value", NodeSocketType.Number)
        self.set_property(
            "value",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=0,
                group="Value",
                label="Value",
                description="Keyframe this to animate the output over time.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the resolved (possibly keyframed) value."""
        del frame_num
        return self.float_value("value", 0.0)


class MathNode(FrameNode):
    """Binary arithmetic on two Number inputs (each with a fallback value)."""

    node_type: str = "Math"
    node_category: str = MATH_CATEGORY
    node_description: str = "Combine two numbers with a selected operation"
    node_color: tuple[int, int, int] = (98, 154, 172)

    def _setup_sockets(self) -> None:
        """Register both Number inputs, the result output, and fallbacks."""
        self.add_input("a", NodeSocketType.Number)
        self.add_input("b", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "operation",
            choice_property(
                MathOperation.Add,
                priority=0,
                group="Math",
                label="Operation",
                description="Arithmetic operation applied to A and B.",
            ),
        )
        self.set_property(
            "a_value",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=10,
                group="Math",
                label="A",
                description="Fallback for A when nothing is connected.",
            ),
        )
        self.set_property(
            "b_value",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=11,
                group="Math",
                label="B",
                description="Fallback for B when nothing is connected.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Apply the selected operation to A and B."""
        del frame_num
        a = self.input_number("a", self.float_value("a_value", 0.0))
        b = self.input_number("b", self.float_value("b_value", 0.0))
        operation = self.enum_value("operation", MathOperation, MathOperation.Add)
        return _apply_math_operation(operation, a, b)


class MathFunctionNode(FrameNode):
    """Apply a unary function to a single Number input."""

    node_type: str = "Math Function"
    node_category: str = MATH_CATEGORY
    node_description: str = "Apply a unary function (sine, sqrt, abs, ...) to a number"
    node_color: tuple[int, int, int] = (104, 158, 176)

    def _setup_sockets(self) -> None:
        """Register the Number input/output and fallback value."""
        self.add_input("value", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "function",
            choice_property(
                MathFunction.Sine,
                priority=0,
                group="Math",
                label="Function",
                description="Unary function applied to the input.",
            ),
        )
        self.set_property(
            "value_fallback",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=10,
                group="Math",
                label="Value",
                description="Fallback when nothing is connected.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Apply the selected unary function."""
        del frame_num
        value = self.input_number("value", self.float_value("value_fallback", 0.0))
        function = self.enum_value("function", MathFunction, MathFunction.Sine)
        return _apply_math_function(function, value)


class ClampNode(FrameNode):
    """Clamp a Number input between a minimum and maximum."""

    node_type: str = "Clamp"
    node_category: str = MATH_CATEGORY
    node_description: str = "Restrict a number to a minimum/maximum range"
    node_color: tuple[int, int, int] = (110, 162, 180)

    def _setup_sockets(self) -> None:
        """Register the Number input/output and clamp bounds."""
        self.add_input("value", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "value_fallback",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=0,
                group="Clamp",
                label="Value",
                description="Fallback when nothing is connected.",
            ),
        )
        self.set_property(
            "min_value",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=10,
                group="Clamp",
                label="Min",
                description="Lower bound.",
            ),
        )
        self.set_property(
            "max_value",
            number_property(
                1.0,
                -1_000_000.0,
                1_000_000.0,
                priority=11,
                group="Clamp",
                label="Max",
                description="Upper bound.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Clamp the resolved value into ``[min_value, max_value]``."""
        del frame_num
        value = self.input_number("value", self.float_value("value_fallback", 0.0))
        low = self.float_value("min_value", 0.0)
        high = self.float_value("max_value", 1.0)
        if high < low:
            low, high = high, low
        return max(low, min(high, value))


class RemapNode(FrameNode):
    """Linearly remap a Number input from one range to another."""

    node_type: str = "Remap Range"
    node_category: str = MATH_CATEGORY
    node_description: str = "Linearly rescale a number from one range to another"
    node_color: tuple[int, int, int] = (116, 166, 184)

    def _setup_sockets(self) -> None:
        """Register the Number input/output and both ranges."""
        self.add_input("value", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "value_fallback",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=0,
                group="Remap",
                label="Value",
                description="Fallback when nothing is connected.",
            ),
        )
        self.set_property(
            "in_min",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=10,
                group="Remap",
                label="In Min",
                description="Source range lower bound.",
            ),
        )
        self.set_property(
            "in_max",
            number_property(
                1.0,
                -1_000_000.0,
                1_000_000.0,
                priority=11,
                group="Remap",
                label="In Max",
                description="Source range upper bound.",
            ),
        )
        self.set_property(
            "out_min",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=12,
                group="Remap",
                label="Out Min",
                description="Destination range lower bound.",
            ),
        )
        self.set_property(
            "out_max",
            number_property(
                1.0,
                -1_000_000.0,
                1_000_000.0,
                priority=13,
                group="Remap",
                label="Out Max",
                description="Destination range upper bound.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Rescale the resolved value from the input range to the output range."""
        del frame_num
        value = self.input_number("value", self.float_value("value_fallback", 0.0))
        in_min = self.float_value("in_min", 0.0)
        in_max = self.float_value("in_max", 1.0)
        out_min = self.float_value("out_min", 0.0)
        out_max = self.float_value("out_max", 1.0)
        span = in_max - in_min
        if abs(span) <= 1e-9:
            return out_min
        t = (value - in_min) / span
        return out_min + t * (out_max - out_min)


class PropertyLinkNode(FrameNode):
    """Extract a connected node's property as a Number output.

    Wire any output from the source node into the ``source`` input, then pick
    the property to read from the dropdown. Supports keyframed numeric values.
    """

    node_type: str = "Property Link"
    node_category: str = MATH_CATEGORY
    node_description: str = (
        "Read a numeric property from a connected node as a Number output"
    )
    node_color: tuple[int, int, int] = (122, 148, 190)

    def _setup_sockets(self) -> None:
        """Register the source reference input and Number output."""
        self._legacy_source_node: str = ""
        self.add_input(PROPERTY_LINK_SOURCE_SLOT, NodeSocketType.Node)
        self.add_output("value", NodeSocketType.Number)
        self.set_property(
            PROPERTY_LINK_PROPERTY_KEY,
            node_property_choice_property(
                "",
                priority=0,
                group="Source",
                label="Property",
                description="Numeric property to read from the connected node.",
            ),
        )
        self.set_property(
            "fallback",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=10,
                group="Source",
                label="Fallback",
                description="Used when the source node or property can't be resolved.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Resolve the selected property on the connected source node."""
        del frame_num
        property_key = self.string_value(PROPERTY_LINK_PROPERTY_KEY, "").strip()
        fallback = self.float_value("fallback", 0.0)
        if not property_key:
            return fallback

        def _coerce_numeric(value: Any, default: float) -> float:
            if isinstance(value, (int, float)):
                v = float(value)
                return v if math.isfinite(v) else default
            return default

        source_id = self.get_input_value(PROPERTY_LINK_SOURCE_SLOT)
        if isinstance(source_id, str) and source_id:
            resolved = self.resolve_node_property(source_id, property_key)
            return _coerce_numeric(resolved, fallback)

        # Legacy documents may still store a node name instead of a wire.
        legacy_name = self._legacy_source_node.strip()
        if legacy_name:
            resolved = self.resolve_named_property(legacy_name, property_key)
            return _coerce_numeric(resolved, fallback)

        return fallback

    def apply_document(self, data: dict[str, Any]) -> None:
        """Restore legacy name-based links from older project files."""
        super().apply_document(data)
        raw_props = data.get("properties", {})
        legacy_name = raw_props.get("source_node")
        if legacy_name is not None:
            self._legacy_source_node = str(legacy_name)


class PropertyDriveNode(FrameNode):
    """Drive a numeric property on a connected node during evaluation.

    Wire the target node into ``target``, pick the property, and feed the
    desired value into ``value``. The override applies while the graph is
    evaluated and does not permanently edit the target's keyframes.
    """

    node_type: str = "Property Drive"
    node_category: str = MATH_CATEGORY
    node_description: str = (
        "Override a numeric property on a connected node with a live Number input"
    )
    node_color: tuple[int, int, int] = (128, 154, 198)

    def _setup_sockets(self) -> None:
        """Register target reference, value input, and Number output."""
        self.add_input(PROPERTY_DRIVE_TARGET_SLOT, NodeSocketType.Node)
        self.add_input(PROPERTY_DRIVE_VALUE_SLOT, NodeSocketType.Number)
        self.add_output("value", NodeSocketType.Number)
        self.set_property(
            "enabled",
            toggle_property(
                True,
                priority=0,
                group="Drive",
                label="Enabled",
                description="When off, the target property keeps its normal value.",
            ),
        )
        self.set_property(
            PROPERTY_DRIVE_PROPERTY_KEY,
            node_property_choice_property(
                "",
                priority=1,
                group="Drive",
                label="Property",
                description="Numeric property to override on the connected node.",
            ),
        )
        self.set_property(
            "fallback",
            number_property(
                0.0,
                -1_000_000.0,
                1_000_000.0,
                priority=10,
                group="Drive",
                label="Fallback",
                description="Used when the value input is not connected.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the resolved drive value for debugging and chaining."""
        del frame_num
        value = self.input_number("value", self.float_value("fallback", 0.0))
        if not math.isfinite(value):
            value = self._raw_float_fallback()
        return value

    def drive_target_id(self) -> str | None:
        """Return the wired target node id, if any."""
        source_id = self.get_input_value(PROPERTY_DRIVE_TARGET_SLOT)
        return source_id if isinstance(source_id, str) and source_id else None

    def drive_property_key(self) -> str:
        """Return the selected target property key."""
        return self.string_value(PROPERTY_DRIVE_PROPERTY_KEY, "").strip()

    def is_enabled(self) -> bool:
        """Return whether this drive is active."""
        return self.bool_value("enabled", True)

    def resolved_drive_value(self, frame_num: int) -> float:
        """Resolve the Number fed into this drive at ``frame_num``."""
        del frame_num
        value = self.input_number("value", self._raw_float_fallback())
        if not math.isfinite(value):
            value = self._raw_float_fallback()
        return value

    def _raw_float_fallback(self) -> float:
        """Read the fallback without applying drive overrides to this node."""
        prop = self.get_property("fallback")
        if prop is None or not isinstance(prop.value, (int, float)):
            return 0.0
        v = float(prop.value)
        return v if math.isfinite(v) else 0.0


def _apply_math_operation(operation: MathOperation, a: float, b: float) -> float:
    """Apply one binary ``MathOperation`` to ``a`` and ``b``."""
    if operation == MathOperation.Add:
        return a + b
    if operation == MathOperation.Subtract:
        return a - b
    if operation == MathOperation.Multiply:
        return a * b
    if operation == MathOperation.Divide:
        return a / b if abs(b) > 1e-12 else 0.0
    if operation == MathOperation.Power:
        try:
            return float(math.pow(a, b))
        except (ValueError, OverflowError):
            return 0.0
    if operation == MathOperation.Minimum:
        return min(a, b)
    if operation == MathOperation.Maximum:
        return max(a, b)
    if operation == MathOperation.Average:
        return (a + b) * 0.5
    if operation == MathOperation.Modulo:
        return math.fmod(a, b) if abs(b) > 1e-12 else 0.0
    return a


def _apply_math_function(function: MathFunction, value: float) -> float:
    """Apply one unary ``MathFunction`` to ``value``."""
    if function == MathFunction.Sine:
        return math.sin(value)
    if function == MathFunction.Cosine:
        return math.cos(value)
    if function == MathFunction.AbsoluteValue:
        return abs(value)
    if function == MathFunction.SquareRoot:
        return math.sqrt(value) if value >= 0.0 else 0.0
    if function == MathFunction.Negate:
        return -value
    if function == MathFunction.Reciprocal:
        return 1.0 / value if abs(value) > 1e-12 else 0.0
    return value
