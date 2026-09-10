"""Logical, comparison, and procedural Number-socket nodes.

These nodes produce or combine scalar values rather than frames, which makes
them the "brain" of a graph: wire a ``Compare`` or ``Logic Gate`` output into
any node's exposed modulation input (see
``FrameNode.expose_modulation_input``) to drive effects conditionally, or use
``Oscillator``/``Random`` to procedurally animate properties over time.

Every node here is stateless: the same ``frame_num`` always yields the same
result, so re-evaluating a frame (scrubbing, preview, then export) can never
drift.
"""

from __future__ import annotations

import math

import numpy as np
from core.nodes.base import NodeProperty, NodeSocketType, NodeValue
from core.nodes.enums import (ComparisonOperation, EaseMode, LogicOperation,
                              Waveform)
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (choice_property, number_property,
                                         toggle_property)

LOGIC_CATEGORY: str = "Logic"

#: Shared bounds for the fallback spin boxes so any realistic scalar fits.
_NUMBER_LIMIT: float = 1_000_000.0


def _scalar_property(
    value: float,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
    suffix: str = "",
) -> NodeProperty:
    """Create a wide-range numeric property used for scalar constants."""
    return number_property(
        value,
        -_NUMBER_LIMIT,
        _NUMBER_LIMIT,
        priority=priority,
        group=group,
        label=label,
        description=description,
        suffix=suffix,
    )


class CompareNode(FrameNode):
    """Compare two numbers and emit 1 (true) or 0 (false)."""

    node_type: str = "Compare"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Relational test on two numbers; outputs 1 or 0"
    node_color: tuple[int, int, int] = (96, 128, 176)

    def _setup_sockets(self) -> None:
        """Register both operands, the boolean output, and their fallbacks."""
        self.add_input("a", NodeSocketType.Number)
        self.add_input("b", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "operation",
            choice_property(
                ComparisonOperation.Greater,
                priority=0,
                group="Compare",
                label="Test",
                description="Relational test applied to A and B.",
            ),
        )
        self.set_property(
            "tolerance",
            _scalar_property(
                0.0,
                priority=1,
                group="Compare",
                label="Tolerance",
                description="Slack used by the Equal and NotEqual tests.",
            ),
        )
        self.set_property(
            "a_value",
            _scalar_property(
                0.0,
                priority=10,
                group="Compare",
                label="A",
                description="Fallback for A when nothing is connected.",
            ),
        )
        self.set_property(
            "b_value",
            _scalar_property(
                1.0,
                priority=11,
                group="Compare",
                label="B",
                description="Fallback for B when nothing is connected.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return 1.0 when the test passes, otherwise 0.0."""
        del frame_num
        a = self.input_number("a", self.float_value("a_value", 0.0))
        b = self.input_number("b", self.float_value("b_value", 1.0))
        operation = self.enum_value(
            "operation", ComparisonOperation, ComparisonOperation.Greater
        )
        tolerance = abs(self.float_value("tolerance", 0.0))
        return 1.0 if _apply_comparison(operation, a, b, tolerance) else 0.0


class LogicGateNode(FrameNode):
    """Combine two numbers with a boolean operation."""

    node_type: str = "Logic Gate"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Combine two truthy numbers with AND, OR, XOR, NOT"
    node_color: tuple[int, int, int] = (88, 132, 168)

    def _setup_sockets(self) -> None:
        """Register the two operands, the boolean output, and their fallbacks."""
        self.add_input("a", NodeSocketType.Number)
        self.add_input("b", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "operation",
            choice_property(
                LogicOperation.And,
                priority=0,
                group="Logic",
                label="Operation",
                description="Boolean operation applied to A and B.",
            ),
        )
        self.set_property(
            "threshold",
            _scalar_property(
                0.5,
                priority=1,
                group="Logic",
                label="Truth Threshold",
                description="A value at or above this counts as true.",
            ),
        )
        self.set_property(
            "a_value",
            _scalar_property(
                0.0,
                priority=10,
                group="Logic",
                label="A",
                description="Fallback for A when nothing is connected.",
            ),
        )
        self.set_property(
            "b_value",
            _scalar_property(
                0.0,
                priority=11,
                group="Logic",
                label="B",
                description="Fallback for B when nothing is connected.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return 1.0 or 0.0 for the selected boolean operation."""
        del frame_num
        a = self.input_number("a", self.float_value("a_value", 0.0))
        b = self.input_number("b", self.float_value("b_value", 0.0))
        threshold = self.float_value("threshold", 0.5)
        operation = self.enum_value("operation", LogicOperation, LogicOperation.And)
        return 1.0 if _apply_logic(operation, a, b, threshold) else 0.0


class SelectNode(FrameNode):
    """Choose between two numbers based on a condition (If / Else)."""

    node_type: str = "If Else"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Output True Value or False Value based on a condition"
    node_color: tuple[int, int, int] = (104, 120, 188)

    def _setup_sockets(self) -> None:
        """Register the condition, both branches, and their fallbacks."""
        self.add_input("condition", NodeSocketType.Number)
        self.add_input("if_true", NodeSocketType.Number)
        self.add_input("if_false", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "threshold",
            _scalar_property(
                0.5,
                priority=0,
                group="Condition",
                label="Truth Threshold",
                description="Condition at or above this selects the true branch.",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=1,
                group="Condition",
                label="Invert",
                description="Swap which branch is selected.",
            ),
        )
        self.set_property(
            "condition_value",
            _scalar_property(
                0.0,
                priority=10,
                group="Condition",
                label="Condition",
                description="Fallback condition when nothing is connected.",
            ),
        )
        self.set_property(
            "true_value",
            _scalar_property(
                1.0,
                priority=11,
                group="Branches",
                label="If True",
                description="Fallback for the true branch.",
            ),
        )
        self.set_property(
            "false_value",
            _scalar_property(
                0.0,
                priority=12,
                group="Branches",
                label="If False",
                description="Fallback for the false branch.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the selected branch value."""
        del frame_num
        condition = self.input_number(
            "condition", self.float_value("condition_value", 0.0)
        )
        if_true = self.input_number("if_true", self.float_value("true_value", 1.0))
        if_false = self.input_number(
            "if_false", self.float_value("false_value", 0.0)
        )
        threshold = self.float_value("threshold", 0.5)
        passed = condition >= threshold
        if self.bool_value("invert", False):
            passed = not passed
        return if_true if passed else if_false


class RangeCheckNode(FrameNode):
    """Test whether a number falls inside a range."""

    node_type: str = "Range Check"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Output 1 when a number is inside a min/max window"
    node_color: tuple[int, int, int] = (110, 140, 172)

    def _setup_sockets(self) -> None:
        """Register the value input, boolean output, and window bounds."""
        self.add_input("value", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "value_fallback",
            _scalar_property(
                0.0,
                priority=0,
                group="Range",
                label="Value",
                description="Fallback when nothing is connected.",
            ),
        )
        self.set_property(
            "minimum",
            _scalar_property(
                0.0,
                priority=10,
                group="Range",
                label="Min",
                description="Lower bound of the window.",
            ),
        )
        self.set_property(
            "maximum",
            _scalar_property(
                1.0,
                priority=11,
                group="Range",
                label="Max",
                description="Upper bound of the window.",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=12,
                group="Range",
                label="Invert",
                description="Output 1 when the value is outside the window.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return 1.0 when the value is inside the (ordered) window."""
        del frame_num
        value = self.input_number("value", self.float_value("value_fallback", 0.0))
        low = self.float_value("minimum", 0.0)
        high = self.float_value("maximum", 1.0)
        if high < low:
            low, high = high, low
        inside = low <= value <= high
        if self.bool_value("invert", False):
            inside = not inside
        return 1.0 if inside else 0.0


class SmoothStepNode(FrameNode):
    """Reshape a number with an easing curve."""

    node_type: str = "Ease"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Remap a number through a smooth interpolation curve"
    node_color: tuple[int, int, int] = (120, 116, 196)

    def _setup_sockets(self) -> None:
        """Register the value input, eased output, and curve controls."""
        self.add_input("value", NodeSocketType.Number)
        self.add_output("result", NodeSocketType.Number)
        self.set_property(
            "mode",
            choice_property(
                EaseMode.SmoothStep,
                priority=0,
                group="Curve",
                label="Curve",
                description="Interpolation curve applied to the normalized value.",
            ),
        )
        self.set_property(
            "value_fallback",
            _scalar_property(
                0.0,
                priority=10,
                group="Curve",
                label="Value",
                description="Fallback when nothing is connected.",
            ),
        )
        self.set_property(
            "edge_start",
            _scalar_property(
                0.0,
                priority=11,
                group="Curve",
                label="Edge Start",
                description="Input value mapped to 0.",
            ),
        )
        self.set_property(
            "edge_end",
            _scalar_property(
                1.0,
                priority=12,
                group="Curve",
                label="Edge End",
                description="Input value mapped to 1.",
            ),
        )
        self.set_property(
            "clamp",
            toggle_property(
                True,
                priority=13,
                group="Curve",
                label="Clamp",
                description="Restrict the result to 0-1.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the eased value."""
        del frame_num
        value = self.input_number("value", self.float_value("value_fallback", 0.0))
        start = self.float_value("edge_start", 0.0)
        end = self.float_value("edge_end", 1.0)
        span = end - start
        if abs(span) <= 1e-12:
            return 0.0
        t = (value - start) / span
        mode = self.enum_value("mode", EaseMode, EaseMode.SmoothStep)
        if self.bool_value("clamp", True):
            t = min(1.0, max(0.0, t))
        return _apply_ease(mode, t)


class OscillatorNode(FrameNode):
    """Generate a periodic value over time to animate other properties."""

    node_type: str = "Oscillator"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Periodic sine/triangle/square/saw wave for animating properties"
    node_color: tuple[int, int, int] = (126, 126, 190)

    def _setup_sockets(self) -> None:
        """Register the wave output and its shape controls."""
        self.add_output("value", NodeSocketType.Number)
        self.set_property(
            "waveform",
            choice_property(
                Waveform.Sine,
                priority=0,
                group="Wave",
                label="Waveform",
                description="Shape of the periodic signal.",
            ),
        )
        self.set_property(
            "frequency",
            number_property(
                1.0,
                0.0,
                240.0,
                priority=10,
                group="Wave",
                label="Frequency",
                description="Cycles per second.",
                suffix=" Hz",
            ),
        )
        self.set_property(
            "amplitude",
            _scalar_property(
                1.0,
                priority=11,
                group="Wave",
                label="Amplitude",
                description="Peak deviation from the offset.",
            ),
        )
        self.set_property(
            "offset",
            _scalar_property(
                0.0,
                priority=12,
                group="Wave",
                label="Offset",
                description="Center value of the wave.",
            ),
        )
        self.set_property(
            "phase",
            number_property(
                0.0,
                -360.0,
                360.0,
                priority=13,
                group="Wave",
                label="Phase",
                description="Phase shift in degrees.",
                suffix="°",
            ),
        )
        self.set_property(
            "duty",
            number_property(
                0.5,
                0.0,
                1.0,
                priority=14,
                group="Wave",
                label="Duty",
                description="High fraction of the square waveform.",
            ),
        )
        self.set_property(
            "seed",
            number_property(
                0.0,
                0.0,
                99999.0,
                priority=15,
                group="Wave",
                label="Seed",
                description="Random waveform sequence seed.",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the wave value at ``frame_num``."""
        fps = max(1.0, float(self._project_fps))
        cycle = (float(frame_num) / fps) * self.float_value("frequency", 1.0)
        phase = self.float_value("phase", 0.0) / 360.0
        duty = min(1.0, max(0.0, self.float_value("duty", 0.5)))
        waveform = self.enum_value("waveform", Waveform, Waveform.Sine)
        unit = _wave_value(
            waveform,
            cycle,
            phase,
            duty,
            int(self.float_value("seed", 0.0)),
        )
        amplitude = self.float_value("amplitude", 1.0)
        offset = self.float_value("offset", 0.0)
        return offset + unit * amplitude


class RandomNode(FrameNode):
    """Emit a deterministic pseudo-random number, optionally per frame."""

    node_type: str = "Random"
    node_category: str = LOGIC_CATEGORY
    node_description: str = "Deterministic random value for shake, jitter, and variation"
    node_color: tuple[int, int, int] = (134, 122, 178)

    def _setup_sockets(self) -> None:
        """Register the value output and randomness controls."""
        self.add_output("value", NodeSocketType.Number)
        self.set_property(
            "seed",
            number_property(
                0.0,
                0.0,
                99999.0,
                priority=0,
                group="Random",
                label="Seed",
                description="Sequence seed; change it for a different result.",
            ),
        )
        self.set_property(
            "minimum",
            _scalar_property(
                0.0,
                priority=10,
                group="Random",
                label="Min",
                description="Lower bound of the generated value.",
            ),
        )
        self.set_property(
            "maximum",
            _scalar_property(
                1.0,
                priority=11,
                group="Random",
                label="Max",
                description="Upper bound of the generated value.",
            ),
        )
        self.set_property(
            "per_frame",
            toggle_property(
                True,
                priority=12,
                group="Random",
                label="Per Frame",
                description="Draw a new value every frame instead of one constant.",
            ),
        )
        self.set_property(
            "interval",
            number_property(
                1.0,
                1.0,
                240.0,
                priority=13,
                group="Random",
                label="Interval",
                description="Hold each value for this many frames.",
                suffix=" f",
            ),
        )

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return a reproducible random value for the current frame."""
        low = self.float_value("minimum", 0.0)
        high = self.float_value("maximum", 1.0)
        if high < low:
            low, high = high, low
        seed = int(self.float_value("seed", 0.0))
        if not self.bool_value("per_frame", True):
            return _sample_random(seed, 0, low, high)
        interval = max(1, round(self.float_value("interval", 1.0)))
        index = int(frame_num) // interval
        return _sample_random(seed, index, low, high)


def _apply_comparison(
    operation: ComparisonOperation, a: float, b: float, tolerance: float
) -> bool:
    """Evaluate one relational test with an equality tolerance."""
    if operation == ComparisonOperation.Greater:
        return a > b
    if operation == ComparisonOperation.GreaterOrEqual:
        return a >= b
    if operation == ComparisonOperation.Less:
        return a < b
    if operation == ComparisonOperation.LessOrEqual:
        return a <= b
    if operation == ComparisonOperation.Equal:
        return abs(a - b) <= tolerance
    if operation == ComparisonOperation.NotEqual:
        return abs(a - b) > tolerance
    return False


def _apply_logic(
    operation: LogicOperation, a: float, b: float, threshold: float
) -> bool:
    """Evaluate one boolean operation on two thresholded numbers."""
    left = a >= threshold
    right = b >= threshold
    if operation == LogicOperation.And:
        return left and right
    if operation == LogicOperation.Or:
        return left or right
    if operation == LogicOperation.ExclusiveOr:
        return left != right
    if operation == LogicOperation.Nand:
        return not (left and right)
    if operation == LogicOperation.Nor:
        return not (left or right)
    if operation == LogicOperation.NotA:
        return not left
    if operation == LogicOperation.NotB:
        return not right
    return left


def _apply_ease(mode: EaseMode, t: float) -> float:
    """Apply one easing curve to ``t``."""
    if mode == EaseMode.SmoothStep:
        return t * t * (3.0 - 2.0 * t)
    if mode == EaseMode.SmootherStep:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    if mode == EaseMode.EaseIn:
        return t * t
    if mode == EaseMode.EaseOut:
        return 1.0 - (1.0 - t) * (1.0 - t)
    if mode == EaseMode.EaseInOut:
        if t < 0.5:
            return 2.0 * t * t
        return 1.0 - ((-2.0 * t + 2.0) ** 2) * 0.5
    return t


def _wave_value(
    waveform: Waveform,
    cycle: float,
    phase: float,
    duty: float,
    seed: int,
) -> float:
    """Return a unit-amplitude waveform sample in ``[-1, 1]``."""
    position = cycle + phase
    t = position % 1.0
    if waveform == Waveform.Sine:
        return math.sin(math.tau * t)
    if waveform == Waveform.Triangle:
        return 1.0 - 4.0 * abs(t - 0.5)
    if waveform == Waveform.Square:
        return 1.0 if t < duty else -1.0
    if waveform == Waveform.Sawtooth:
        return 2.0 * t - 1.0
    if waveform == Waveform.Random:
        index = int(math.floor(position))
        return _sample_random(seed, index, -1.0, 1.0)
    return 0.0


def _sample_random(seed: int, index: int, low: float, high: float) -> float:
    """Return a reproducible value in ``[low, high]`` for a seed + index pair."""
    mixed = (int(seed) * 2654435761 + int(index) * 40503) & 0xFFFFFFFF
    unit = float(np.random.default_rng(mixed).random())
    return low + unit * (high - low)
