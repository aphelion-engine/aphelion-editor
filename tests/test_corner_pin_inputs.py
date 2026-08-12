"""Tests for Corner Pin modulation inputs and tracker output scaling."""

from __future__ import annotations

import unittest

import numpy as np

from core.nodes.generator_nodes import SolidColorNode
from core.nodes.math_nodes import ValueNode
from core.nodes.tracking_nodes import PlanarTrackerNode, TrackerNode
from core.nodes.transform_nodes import CornerPinNode
from core.project import Project


class CornerPinInputTests(unittest.TestCase):
    """Verify corner coordinates resolve correctly from wires and properties."""

    def test_value_node_wires_use_percent_scale(self) -> None:
        """Number inputs on ``in_*`` sockets are treated as 0–100 percents."""
        project = Project()
        source_id = project.add_node(SolidColorNode())
        value_id = project.add_node(ValueNode())
        pin_id = project.add_node(CornerPinNode())

        value_node = project.nodes[value_id]
        value_node.set_property("value", 25.0)

        project.connect_nodes(source_id, "frame", pin_id, "frame")
        project.connect_nodes(value_id, "value", pin_id, "in_top_left_x")
        project.connect_nodes(value_id, "value", pin_id, "in_top_left_y")

        pin_node = project.nodes[pin_id]
        pin_node.clear_input_values()
        pin_node.set_input_value("in_top_left_x", 25.0)
        pin_node.set_input_value("in_top_left_y", 75.0)

        self.assertAlmostEqual(pin_node._corner_axis("top_left_x", 0.0), 0.25)
        self.assertAlmostEqual(pin_node._corner_axis("top_left_y", 0.0), 0.75)

    def test_static_corner_properties_use_percent_scale(self) -> None:
        """Unwired corners still read the 0–100 property sliders."""
        project = Project()
        pin_id = project.add_node(CornerPinNode())
        pin_node = project.nodes[pin_id]
        pin_node.set_property("top_right_x", 100.0)
        pin_node.set_property("top_right_y", 0.0)

        x, y = pin_node._corner("top_right")
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 0.0)

    def test_tracker_outputs_match_corner_pin_percent_scale(self) -> None:
        """Tracker Number sockets must land on the same scale as corner props."""
        tracker = TrackerNode()
        tracker.set_property("center_x", 40.0)
        tracker.set_property("center_y", 60.0)
        result = tracker.evaluate(0)
        assert isinstance(result, dict)
        self.assertAlmostEqual(result["x"], 40.0)
        self.assertAlmostEqual(result["y"], 60.0)

    def test_planar_tracker_outputs_match_corner_pin_percent_scale(self) -> None:
        """Planar tracker corners must use percent units for direct wiring."""
        tracker = PlanarTrackerNode()
        result = tracker.evaluate(0)
        assert isinstance(result, dict)
        self.assertAlmostEqual(result["top_left_x"], 0.0)
        self.assertAlmostEqual(result["top_left_y"], 0.0)
        self.assertAlmostEqual(result["bottom_right_x"], 100.0)
        self.assertAlmostEqual(result["bottom_right_y"], 100.0)

    def test_corner_pin_evaluates_with_planar_tracker_wires(self) -> None:
        """End-to-end: tracker percents drive a corner pin without 100x shrink."""
        project = Project()
        project.width = 100
        project.height = 100

        source_id = project.add_node(SolidColorNode())
        # SolidColorNode defaults to a dark gray fill (32, 32, 32) — force
        # white so "left intact" is checkable against a known-bright value.
        project.nodes[source_id].set_property("color", (255, 255, 255))
        tracker_id = project.add_node(PlanarTrackerNode())
        pin_id = project.add_node(CornerPinNode())

        for corner in ("top_left", "top_right", "bottom_right", "bottom_left"):
            project.connect_nodes(tracker_id, f"{corner}_x", pin_id, f"in_{corner}_x")
            project.connect_nodes(tracker_id, f"{corner}_y", pin_id, f"in_{corner}_y")
        project.connect_nodes(source_id, "frame", pin_id, "frame")

        frame = project.evaluate_node(pin_id, 0, "frame")
        self.assertIsInstance(frame, np.ndarray)
        assert isinstance(frame, np.ndarray)
        # Identity corner pin at default seeds should leave the solid frame intact.
        self.assertGreater(float(np.mean(frame)), 0.9)


if __name__ == "__main__":
    unittest.main()
