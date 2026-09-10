"""Tests for the Number-socket logic, easing, and procedural nodes."""

from __future__ import annotations

import unittest

import numpy as np
from core.nodes.enums import (ComparisonOperation, EaseMode, LogicOperation,
                              Waveform)
from core.nodes.logic_nodes import (CompareNode, LogicGateNode, OscillatorNode,
                                    RandomNode, RangeCheckNode, SelectNode,
                                    SmoothStepNode)


class CompareNodeTests(unittest.TestCase):
    """Verify relational tests emit clean 1/0 booleans."""

    def test_greater_than(self) -> None:
        node = CompareNode()
        node.set_property("operation", ComparisonOperation.Greater)
        node.set_input_value("a", 2.0)
        node.set_input_value("b", 1.0)
        self.assertEqual(node.evaluate(0), 1.0)

        node.set_input_value("a", 1.0)
        self.assertEqual(node.evaluate(0), 0.0)

    def test_equal_respects_tolerance(self) -> None:
        node = CompareNode()
        node.set_property("operation", ComparisonOperation.Equal)
        node.set_property("tolerance", 0.05)
        node.set_input_value("a", 1.0)
        node.set_input_value("b", 1.03)
        self.assertEqual(node.evaluate(0), 1.0)

        node.set_input_value("b", 1.2)
        self.assertEqual(node.evaluate(0), 0.0)

    def test_not_equal_is_the_exact_inverse(self) -> None:
        node = CompareNode()
        node.set_property("operation", ComparisonOperation.NotEqual)
        node.set_property("tolerance", 0.1)
        node.set_input_value("a", 5.0)
        node.set_input_value("b", 5.05)
        self.assertEqual(node.evaluate(0), 0.0)


class LogicGateNodeTests(unittest.TestCase):
    """Verify boolean combinations of two thresholded numbers."""

    def _gate(self, operation: LogicOperation, a: float, b: float) -> float:
        node = LogicGateNode()
        node.set_property("operation", operation)
        node.set_property("threshold", 0.5)
        node.set_input_value("a", a)
        node.set_input_value("b", b)
        return node.evaluate(0)

    def test_truth_table(self) -> None:
        cases = (
            (LogicOperation.And, 1.0, 0.0, 0.0),
            (LogicOperation.Or, 1.0, 0.0, 1.0),
            (LogicOperation.ExclusiveOr, 1.0, 1.0, 0.0),
            (LogicOperation.ExclusiveOr, 1.0, 0.0, 1.0),
            (LogicOperation.Nand, 1.0, 1.0, 0.0),
            (LogicOperation.Nor, 0.0, 0.0, 1.0),
            (LogicOperation.NotA, 0.0, 1.0, 1.0),
            (LogicOperation.NotB, 1.0, 0.0, 1.0),
        )
        for operation, a, b, expected in cases:
            with self.subTest(operation=operation, a=a, b=b):
                self.assertEqual(self._gate(operation, a, b), expected)


class SelectNodeTests(unittest.TestCase):
    """Verify the If/Else branch selection."""

    def test_selects_branch_by_condition(self) -> None:
        node = SelectNode()
        node.set_property("threshold", 0.5)
        node.set_property("true_value", 10.0)
        node.set_property("false_value", -10.0)
        node.set_input_value("condition", 1.0)
        self.assertEqual(node.evaluate(0), 10.0)
        node.set_input_value("condition", 0.0)
        self.assertEqual(node.evaluate(0), -10.0)

    def test_invert_swaps_branches(self) -> None:
        node = SelectNode()
        node.set_property("invert", True)
        node.set_property("true_value", 10.0)
        node.set_property("false_value", -10.0)
        node.set_input_value("condition", 1.0)
        self.assertEqual(node.evaluate(0), -10.0)


class RangeCheckNodeTests(unittest.TestCase):
    """Verify window membership testing."""

    def test_inside_and_outside(self) -> None:
        node = RangeCheckNode()
        node.set_property("minimum", 0.25)
        node.set_property("maximum", 0.75)
        node.set_input_value("value", 0.5)
        self.assertEqual(node.evaluate(0), 1.0)
        node.set_input_value("value", 0.9)
        self.assertEqual(node.evaluate(0), 0.0)

    def test_swapped_bounds_are_ordered(self) -> None:
        node = RangeCheckNode()
        node.set_property("minimum", 0.75)
        node.set_property("maximum", 0.25)
        node.set_input_value("value", 0.5)
        self.assertEqual(node.evaluate(0), 1.0)

    def test_invert_returns_outside_window(self) -> None:
        node = RangeCheckNode()
        node.set_property("minimum", 0.0)
        node.set_property("maximum", 0.5)
        node.set_property("invert", True)
        node.set_input_value("value", 0.75)
        self.assertEqual(node.evaluate(0), 1.0)


class SmoothStepNodeTests(unittest.TestCase):
    """Verify easing endpoints and midpoints."""

    def test_smoothstep_endpoints_and_midpoint(self) -> None:
        node = SmoothStepNode()
        node.set_property("mode", EaseMode.SmoothStep)
        node.set_property("edge_start", 0.0)
        node.set_property("edge_end", 1.0)
        node.set_input_value("value", 0.0)
        self.assertAlmostEqual(node.evaluate(0), 0.0, places=6)
        node.set_input_value("value", 1.0)
        self.assertAlmostEqual(node.evaluate(0), 1.0, places=6)
        node.set_input_value("value", 0.5)
        self.assertAlmostEqual(node.evaluate(0), 0.5, places=6)

    def test_clamp_restricts_out_of_range_input(self) -> None:
        node = SmoothStepNode()
        node.set_property("clamp", True)
        node.set_input_value("value", 5.0)
        self.assertAlmostEqual(node.evaluate(0), 1.0, places=6)

    def test_ease_in_is_quadratic(self) -> None:
        node = SmoothStepNode()
        node.set_property("mode", EaseMode.EaseIn)
        node.set_input_value("value", 0.5)
        self.assertAlmostEqual(node.evaluate(0), 0.25, places=6)


class OscillatorNodeTests(unittest.TestCase):
    """Verify waveform sampling and time behavior."""

    def test_sine_phase_quarter_peaks(self) -> None:
        node = OscillatorNode()
        node.set_property("waveform", Waveform.Sine)
        node.set_property("frequency", 1.0)
        node.set_property("amplitude", 1.0)
        node.set_property("offset", 0.0)
        node.set_property("phase", 90.0)
        self.assertAlmostEqual(node.evaluate(0), 1.0, places=6)

    def test_square_and_sawtooth_shapes(self) -> None:
        node = OscillatorNode()
        node.set_property("waveform", Waveform.Square)
        node.set_property("duty", 0.5)
        node.set_property("phase", 0.0)
        self.assertAlmostEqual(node.evaluate(0), 1.0, places=6)

        node.set_property("waveform", Waveform.Sawtooth)
        self.assertAlmostEqual(node.evaluate(0), -1.0, places=6)

    def test_amplitude_and_offset_scale_the_wave(self) -> None:
        node = OscillatorNode()
        node.set_property("waveform", Waveform.Sine)
        node.set_property("amplitude", 4.0)
        node.set_property("offset", 10.0)
        node.set_property("phase", 90.0)
        self.assertAlmostEqual(node.evaluate(0), 14.0, places=6)

    def test_random_waveform_is_deterministic(self) -> None:
        node = OscillatorNode()
        node.set_property("waveform", Waveform.Random)
        node.set_property("seed", 7.0)
        self.assertEqual(node.evaluate(3), node.evaluate(3))


class RandomNodeTests(unittest.TestCase):
    """Verify reproducibility, bounds, and frame stepping."""

    def test_values_are_reproducible(self) -> None:
        node = RandomNode()
        node.set_property("seed", 123.0)
        node.set_property("minimum", 0.0)
        node.set_property("maximum", 100.0)
        self.assertEqual(node.evaluate(11), node.evaluate(11))

    def test_values_stay_within_bounds(self) -> None:
        node = RandomNode()
        node.set_property("seed", 5.0)
        node.set_property("minimum", 2.0)
        node.set_property("maximum", 3.0)
        for frame in range(20):
            value = float(node.evaluate(frame))
            self.assertGreaterEqual(value, 2.0)
            self.assertLessEqual(value, 3.0)

    def test_static_mode_ignores_frame_number(self) -> None:
        node = RandomNode()
        node.set_property("per_frame", False)
        self.assertEqual(node.evaluate(0), node.evaluate(50))

    def test_interval_holds_each_value(self) -> None:
        node = RandomNode()
        node.set_property("per_frame", True)
        node.set_property("interval", 10.0)
        self.assertEqual(node.evaluate(0), node.evaluate(9))
        self.assertNotEqual(node.evaluate(0), node.evaluate(10))

    def test_output_is_a_plain_float(self) -> None:
        node = RandomNode()
        self.assertIsInstance(node.evaluate(0), float)
        self.assertTrue(np.isfinite(node.evaluate(0)))


if __name__ == "__main__":
    unittest.main()
