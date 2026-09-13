"""Shape masks, serialization, editing, and tracker toolbar layout."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import unittest
import numpy as np
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QPushButton
from core.nodes.shape_tracker import ShapeTrackerNode
from core.nodes.enums import TrackerShape
from core.nodes.custom_nodes import build_node_from_blob
from core.nodes import ViewerNode
from core.project import Project
from core.history import HistoryStack
from app_io.node_loader import NodeLoader
from ui.widgets.viewport import ViewportWidget


class ShapeTrackerTests(unittest.TestCase):
    def test_all_shape_masks_and_tracked_translation(self):
        for shape in TrackerShape:
            node = ShapeTrackerNode()
            node.set_input_value("frame",np.zeros((101,101,3),np.float32))
            node.set_property("shape",shape)
            node.set_property("vertices","[[-10,-10],[10,-10],[10,10],[-10,10]]")
            seed = node.evaluate(0)["mask"]
            self.assertEqual(seed[50,50],1)
            self.assertEqual(seed[0,0],0)
            node.track_x.set_keyframe(1,0.7)
            node.track_y.set_keyframe(1,0.5)
            result = node.evaluate(1)
            self.assertEqual(result["x"],70)
            np.testing.assert_array_equal(result["mask"][:,20:],seed[:,:-20])

    def test_polygon_round_trip_retains_shape_and_motion(self):
        NodeLoader.load_defaults()
        node = ShapeTrackerNode()
        node.set_property("shape",TrackerShape.Polygon)
        node.set_property("vertices","[[-10,-5],[15,0],[0,10]]")
        node.track_x.set_keyframe(3,0.6)
        node.track_y.set_keyframe(3,0.4)
        restored = build_node_from_blob(node.to_dict())
        self.assertIsInstance(restored,ShapeTrackerNode)
        self.assertEqual(restored.get_property("shape").value,TrackerShape.Polygon)
        np.testing.assert_array_equal(restored.outline(3),node.outline(3))

    def test_invalid_or_incomplete_polygons_produce_empty_masks(self):
        for value in ('bad','{}','[[0,0],[1,1]]','[[NaN,0],[1,1],[2,0]]'):
            node = ShapeTrackerNode()
            node.set_input_value("frame",np.zeros((10,10,3),np.float32))
            node.set_property("shape",TrackerShape.Polygon)
            node.set_property("vertices",value)
            self.assertEqual(node.evaluate(0)["mask"].sum(),0)


class TrackerLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.project = Project("tracker-layout")
        self.project.add_node(ViewerNode(),"viewer")
        self.node = ShapeTrackerNode()
        self.project.add_node(self.node,"shape")
        self.history = HistoryStack(self.project)
        self.viewport = ViewportWidget(self.project,self.history)
        self.viewport._worker.stop()

    def tearDown(self):
        self.viewport.close()

    def test_toolbar_avoids_image_hud_at_multiple_sizes(self):
        self.viewport.set_edit_target("shape")
        self.viewport._overlay.show()
        for width in (320,640,1200):
            self.viewport.resize(width,400)
            self.viewport.show()
            self.app.processEvents()
            toolbar = self.viewport._tracker_overlay._toolbar
            self.assertLess(toolbar.geometry().bottom(),self.viewport.label.geometry().top())
            self.assertLessEqual(toolbar.height(),90)
            buttons = [b for b in toolbar.findChildren(QPushButton) if b.isVisible()]
            for i,button in enumerate(buttons):
                self.assertGreaterEqual(button.width(),button.minimumSizeHint().width())
                for other in buttons[i+1:]:
                    self.assertFalse(button.geometry().intersects(other.geometry()))
            self.assertEqual(self.viewport._tracker_overlay.geometry(),self.viewport.label.rect())
        self.viewport.set_edit_target(None)
        self.assertFalse(toolbar.isVisible())

    def test_polygon_edits_are_undoable_and_leave_track_intact(self):
        self.viewport.set_edit_target("shape")
        overlay = self.viewport._tracker_overlay
        self.node.track_x.set_keyframe(0,0.6)
        self.node.track_y.set_keyframe(0,0.5)
        for point in ((0.4,0.4),(0.8,0.4),(0.6,0.7)):
            overlay._edit_polygon(point=point)
        self.assertEqual(len(self.node.polygon_vertices()),3)
        outline = self.node.outline(0)
        np.testing.assert_allclose(outline,[[0.4,0.4],[0.8,0.4],[0.6,0.7]],atol=1e-6)
        overlay._edit_polygon(clear=True)
        self.assertEqual(self.node.polygon_vertices(),[])
        self.history.undo()
        self.assertEqual(len(self.node.polygon_vertices()),3)
        self.assertEqual(self.node.track_x.value_at(0),0.6)
