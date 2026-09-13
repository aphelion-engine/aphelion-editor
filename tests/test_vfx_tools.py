"""Behavior checks for tracking and compositing tools."""
import unittest
import numpy as np
from core.nodes.vfx_tools import *
from core.nodes.filter_effects import GaussianBlurNode
from core.project import Project
from ui.node_graph.custom_node_ops import build_custom_node_definition
from core.nodes.custom_nodes import make_custom_node_class


class VfxToolsTests(unittest.TestCase):
    def test_unwired_custom_ports_evaluate(self):
        project = Project("ports")
        project.add_node(GaussianBlurNode(), node_id="blur")
        build = build_custom_node_definition(project, ["blur"], name="Blur wrapper")
        node = make_custom_node_class(build.definition)()
        self.assertEqual(len(node.inputs), 1)
        self.assertEqual(len(node.outputs), 1)
        frame = np.full((8, 8, 3), 80, np.uint8)
        node.set_input_value(next(iter(node.inputs)), frame)
        result = node.evaluate(0)
        np.testing.assert_allclose(result[next(iter(node.outputs))], frame, atol=1e-5)

    def test_perspective_identity(self):
        frame = np.arange(8*12*3, dtype=np.uint8).reshape(8,12,3)
        for cls in (PerspectiveTiltNode, KeystoneNode, MatchMoveNode, ChannelShuffleNode):
            with self.subTest(node=cls.node_type):
                np.testing.assert_array_equal(cls().process_frame(frame,0),frame)

    def test_track_distance(self):
        node = TrackDistanceNode()
        node.set_input_value("x2",3.0)
        node.set_input_value("y2",4.0)
        result = node.evaluate(0)
        self.assertEqual(result["distance"],5)
        self.assertEqual(result["mid_x"],1.5)

    def test_match_move_translation(self):
        node = MatchMoveNode()
        node.set_input_value("in_x",60.0)
        frame = np.zeros((10,10,3),np.uint8)
        frame[4,4] = 255
        result = node.process_frame(frame,0)
        np.testing.assert_array_equal(result[4,5], [255]*3)
        self.assertEqual(int(result[4,4].sum()),0)

    def test_directional_blur_spreads_impulse(self):
        frame = np.zeros((31,31,3),np.float32)
        frame[15,15] = 1
        result = DirectionalBlurNode().process_frame(frame,0)
        self.assertGreater(result[15,14,0],0)
        self.assertAlmostEqual(float(result[14,15,0]),0,places=7)
        np.testing.assert_allclose(result.sum(axis=(0,1)),[1,1,1],atol=1e-6)

    def test_socket_refresh_at_same_size(self):
        from PyQt6.QtWidgets import QApplication
        from ui.node_graph.node_item import NodeItem
        app = QApplication.instance() or QApplication([])
        node = TrackOffsetNode()
        item = NodeItem(node,"track")
        old_rect = item.rect()
        node.outputs["z"] = node.outputs.pop("x")
        item.relayout_from_content()
        self.assertEqual(item.rect(),old_rect)
        self.assertIn("z",item.output_sockets)
        self.assertNotIn("x",item.output_sockets)

    def test_registered_nodes_round_trip(self):
        from app_io.node_loader import NodeLoader
        from core.nodes.custom_nodes import build_node_from_blob
        NodeLoader.load_defaults()
        for cls in VFX_NODE_TYPES:
            node = cls()
            restored = build_node_from_blob(node.to_dict())
            self.assertIsInstance(restored,cls)
            self.assertTrue(node.inputs)
            self.assertTrue(node.outputs)
