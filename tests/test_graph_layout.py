"""Tests for dependency-aware graph auto-layout."""

from __future__ import annotations

import unittest

from config.constants import GRAPH_LAYOUT_GRID_PX
from core.events import Connection
from core.graph_layout import compute_graph_layout
from core.nodes import ViewerNode
from core.nodes.generator_nodes import SolidColorNode
from core.project import Project


class GraphLayoutTests(unittest.TestCase):
    """Verify layered layout ordering and grid snapping."""

    def test_linear_chain_flows_left_to_right(self) -> None:
        """Downstream nodes should sit in columns to the right of sources."""
        project = Project(name="layout-linear")
        source_id = project.add_node(SolidColorNode(), "source")
        sink_id = project.add_node(ViewerNode(), "viewer")
        connected = project.connect_nodes(source_id, "frame", sink_id, "frame")
        self.assertTrue(connected, "SolidColorNode.frame -> ViewerNode.frame must link")

        nodes = project.nodes
        sizes = {
            source_id: (180, 100),
            sink_id: (180, 100),
        }
        positions = compute_graph_layout(nodes, project.connections, sizes=sizes)

        self.assertLess(positions[source_id][0], positions[sink_id][0])
        self.assertEqual(positions[source_id][1], positions[sink_id][1])

    def test_positions_snap_to_grid(self) -> None:
        """Every coordinate should land on the configured grid."""
        project = Project(name="layout-grid")
        node_id = project.add_node(SolidColorNode(), "solo")
        positions = compute_graph_layout(
            project.nodes,
            project.connections,
            sizes={node_id: (180, 100)},
        )
        x, y = positions[node_id]
        grid = float(GRAPH_LAYOUT_GRID_PX)
        self.assertEqual(x % grid, 0.0)
        self.assertEqual(y % grid, 0.0)


if __name__ == "__main__":
    unittest.main()
