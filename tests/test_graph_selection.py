"""Tests for multi-node selection and the graph quick actions."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.history import HistoryStack
from core.nodes.filter_effects import GaussianBlurNode
from core.nodes.generator_nodes import SolidColorNode
from core.nodes.viewer import ViewerNode
from core.project import Project
from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication
from ui.node_graph import selection_ops
from ui.node_graph.selection_ops import SelectionTraversal


def _application() -> QApplication:
    """Return the process QApplication required by QWidget tests."""
    current: object | None = QApplication.instance()
    if isinstance(current, QApplication):
        return current
    return QApplication([])


class _FakeItem:
    """Minimal stand-in for ``NodeItem`` (duck-typed for selection ops)."""

    def __init__(self, project: Project, node_id: str) -> None:
        self.project = project
        self.node_id = node_id
        self.selected = False

    def pos(self) -> QPointF:
        node = self.project.nodes[self.node_id]
        return QPointF(float(node.x), float(node.y))

    def rect(self) -> QRectF:
        return QRectF(0, 0, 160, 92)

    def sceneBoundingRect(self) -> QRectF:
        return self.rect().translated(self.pos())

    def isSelected(self) -> bool:
        return self.selected

    def setSelected(self, selected: bool) -> None:
        self.selected = bool(selected)


class _FakeScene:
    """Scene stub that clears the fake items it is told about."""

    def __init__(self) -> None:
        self.cleared = 0
        self.items: dict[str, _FakeItem] = {}

    def clearSelection(self) -> None:
        self.cleared += 1
        for item in self.items.values():
            item.setSelected(False)


class _FakeView:
    """Minimal stand-in for ``NodeGraphView`` (no Qt widgets needed)."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.history = HistoryStack(project)
        self.node_items: dict[str, _FakeItem] = {}
        self.scene = _FakeScene()
        for node_id in project.nodes:
            self.node_items[node_id] = _FakeItem(project, node_id)
        self.scene.items = self.node_items

    def selected_nodes(self) -> list[_FakeItem]:
        return [item for item in self.node_items.values() if item.isSelected()]

    def view_center_scene_pos(self) -> QPointF:
        return QPointF(0.0, 0.0)


class TraversalTests(unittest.TestCase):
    """Verify graph-walking selection expansion."""

    def _chain(self) -> tuple[Project, list[str]]:
        project = Project(name="traversal")
        a = project.add_node(SolidColorNode(), "a")
        b = project.add_node(GaussianBlurNode(), "b")
        c = project.add_node(GaussianBlurNode(), "c")
        d = project.add_node(ViewerNode(), "d")
        self.assertTrue(project.connect_nodes(a, "frame", b, "frame"))
        self.assertTrue(project.connect_nodes(b, "frame", c, "frame"))
        self.assertTrue(project.connect_nodes(c, "frame", d, "frame"))
        return project, [a, b, c, d]

    def test_upstream_walks_against_the_flow(self) -> None:
        """Selecting the third node also grabs its two ancestors."""
        project, (a, b, c, _d) = self._chain()
        found = selection_ops.traversal_ids(
            project.connections, {c}, SelectionTraversal.UPSTREAM
        )
        self.assertEqual(found, {a, b, c})

    def test_downstream_walks_with_the_flow(self) -> None:
        """Selecting the third node also grabs the viewer."""
        project, (_a, _b, c, d) = self._chain()
        found = selection_ops.traversal_ids(
            project.connections, {c}, SelectionTraversal.DOWNSTREAM
        )
        self.assertEqual(found, {c, d})

    def test_connected_walks_both_ways(self) -> None:
        """Connected expansion reaches the whole tree."""
        project, (a, b, c, d) = self._chain()
        found = selection_ops.traversal_ids(
            project.connections, {b}, SelectionTraversal.CONNECTED
        )
        self.assertEqual(found, {a, b, c, d})

    def test_seed_survives_cycles(self) -> None:
        """An unconnected seed is still part of the result."""
        project = Project(name="traversal-solo")
        solo = project.add_node(SolidColorNode(), "solo")
        found = selection_ops.traversal_ids(
            project.connections, {solo}, SelectionTraversal.CONNECTED
        )
        self.assertEqual(found, {solo})


class BypassStateTests(unittest.TestCase):
    """Verify the shared bypass target state."""

    def test_all_live_nodes_get_bypassed(self) -> None:
        """A fully enabled selection turns off."""
        self.assertFalse(selection_ops.next_bypass_state([True, True]))

    def test_mixed_selection_turns_on(self) -> None:
        """A partially bypassed selection turns back on."""
        self.assertTrue(selection_ops.next_bypass_state([True, False]))

    def test_fully_bypassed_selection_turns_on(self) -> None:
        """An already bypassed selection is re-enabled."""
        self.assertTrue(selection_ops.next_bypass_state([False, False]))

    def test_empty_selection_defaults_to_enabled(self) -> None:
        """Nothing selected never asks to bypass."""
        self.assertTrue(selection_ops.next_bypass_state([]))


class GridLayoutTests(unittest.TestCase):
    """Verify the tidy-selection grid math."""

    def test_column_count_adapts_to_selection_size(self) -> None:
        """Small selections stay on one row; large ones wrap."""
        self.assertEqual(selection_ops.tidy_columns(1), 1)
        self.assertEqual(selection_ops.tidy_columns(3), 3)
        self.assertEqual(selection_ops.tidy_columns(4), 2)
        self.assertEqual(selection_ops.tidy_columns(9), 3)
        self.assertEqual(selection_ops.tidy_columns(100), 6)

    def test_grid_positions_never_overlap(self) -> None:
        """Mixed node sizes are packed without collisions."""
        sizes = [(160.0, 92.0), (240.0, 120.0), (160.0, 92.0), (180.0, 100.0)]
        rects = [
            QRectF(x, y, w, h)
            for (x, y), (w, h) in zip(
                selection_ops.grid_positions(
                    sizes, columns=2, column_gap=40.0, row_gap=30.0
                ),
                sizes,
            )
        ]
        for index, rect in enumerate(rects):
            for other in rects[index + 1:]:
                self.assertFalse(rect.intersects(other))

    def test_grid_positions_are_empty_without_items(self) -> None:
        """No sizes means no offsets."""
        self.assertEqual(
            selection_ops.grid_positions(
                [], columns=3, column_gap=10.0, row_gap=10.0
            ),
            [],
        )


class SelectionQuickActionTests(unittest.TestCase):
    """Exercise the document-level quick actions against a fake view."""

    def _view(self) -> tuple[_FakeView, str, str, str]:
        project = Project(name="selection-ops")
        source = project.add_node(SolidColorNode(), "source")
        blur = project.add_node(GaussianBlurNode(), "blur")
        other = project.add_node(GaussianBlurNode(), "other")
        self.assertTrue(project.connect_nodes(source, "frame", blur, "frame"))
        return _FakeView(project), source, blur, other

    def test_invert_selection_flips_membership(self) -> None:
        """Inverting selects the complement of the current selection."""
        view, source, blur, other = self._view()
        view.node_items[source].setSelected(True)
        self.assertEqual(selection_ops.invert_selection(view), 2)
        self.assertFalse(view.node_items[source].isSelected())
        self.assertTrue(view.node_items[blur].isSelected())
        self.assertTrue(view.node_items[other].isSelected())

    def test_select_related_expands_along_wires(self) -> None:
        """Downstream expansion selects the wired blur node."""
        view, source, blur, _other = self._view()
        view.node_items[source].setSelected(True)
        count = selection_ops.select_related(view, SelectionTraversal.DOWNSTREAM)
        self.assertEqual(count, 2)
        self.assertTrue(view.node_items[blur].isSelected())

    def test_select_same_type_matches_node_type(self) -> None:
        """Both blur nodes share a type and get selected together."""
        view, source, blur, other = self._view()
        view.node_items[blur].setSelected(True)
        self.assertEqual(selection_ops.select_same_type(view), 2)
        self.assertTrue(view.node_items[other].isSelected())
        self.assertFalse(view.node_items[source].isSelected())

    def test_toggle_bypass_updates_every_effect_node(self) -> None:
        """Bypassing writes the shared ``enabled`` property and undoes cleanly."""
        view, _source, blur, other = self._view()
        view.node_items[blur].setSelected(True)
        view.node_items[other].setSelected(True)
        items = view.selected_nodes()

        self.assertEqual(selection_ops.toggle_selection_bypass(view, items), 2)
        self.assertFalse(view.project.nodes[blur].get_property("enabled").value)  # type: ignore[union-attr]
        self.assertFalse(view.project.nodes[other].get_property("enabled").value)  # type: ignore[union-attr]

        view.history.undo()
        self.assertTrue(view.project.nodes[blur].get_property("enabled").value)  # type: ignore[union-attr]

    def test_toggle_bypass_ignores_nodes_without_the_property(self) -> None:
        """Nodes that cannot be bypassed are skipped rather than failing."""
        view, source, _blur, _other = self._view()
        view.node_items[source].setSelected(True)
        self.assertEqual(
            selection_ops.toggle_selection_bypass(view, view.selected_nodes()),
            0,
        )

    def test_remove_selection_wires_only_touches_selection(self) -> None:
        """Wires are removed for the selection and restored on undo."""
        view, source, blur, _other = self._view()
        view.node_items[source].setSelected(True)
        self.assertEqual(
            selection_ops.remove_selection_wires(view, view.selected_nodes()), 1
        )
        self.assertEqual(len(view.project.connections), 0)

        view.history.undo()
        self.assertEqual(len(view.project.connections), 1)
        self.assertTrue(view.project.connections)

    def test_nudge_coalesces_into_one_undo_step(self) -> None:
        """Repeated nudges merge so undo returns to the original position."""
        view, _source, blur, _other = self._view()
        view.node_items[blur].setSelected(True)
        items = view.selected_nodes()
        start_x = view.project.nodes[blur].x

        self.assertTrue(selection_ops.nudge_selection(view, items, 12.0, 0.0))
        self.assertTrue(selection_ops.nudge_selection(view, items, 12.0, 0.0))
        self.assertAlmostEqual(view.project.nodes[blur].x, start_x + 24.0)

        view.history.undo()
        self.assertAlmostEqual(view.project.nodes[blur].x, start_x)

    def test_tidy_selection_aligns_into_rows(self) -> None:
        """Tidying moves nodes onto a shared column origin."""
        project = Project(name="tidy")
        ids = [
            project.add_node(SolidColorNode(), f"n{index}") for index in range(3)
        ]
        for offset, node_id in enumerate(ids):
            project.nodes[node_id].x = 500.0 + offset * 13.0
            project.nodes[node_id].y = 700.0 + offset * 29.0
        view = _FakeView(project)
        for node_id in ids:
            view.node_items[node_id].setSelected(True)

        self.assertTrue(
            selection_ops.tidy_selection(view, view.selected_nodes())
        )
        ys = {round(project.nodes[node_id].y) for node_id in ids}
        self.assertEqual(len(ys), 1, "a single row should share one y origin")

        view.history.undo()
        self.assertAlmostEqual(project.nodes[ids[0]].x, 500.0)

    def test_selection_bounds_unions_every_item(self) -> None:
        """Bounds cover the whole selection."""
        view, source, blur, other = self._view()
        for index, node_id in enumerate((source, blur, other)):
            view.project.nodes[node_id].x = float(index * 200)
            view.project.nodes[node_id].y = 0.0
            view.node_items[node_id].setSelected(True)

        bounds = selection_ops.selection_bounds(view.selected_nodes())
        assert bounds is not None
        self.assertAlmostEqual(bounds.left(), 0.0)
        self.assertAlmostEqual(bounds.right(), 400.0 + 160.0)

    def test_selection_bounds_is_none_when_empty(self) -> None:
        """An empty selection has no bounds."""
        self.assertIsNone(selection_ops.selection_bounds([]))


class NodeGraphMultiSelectTests(unittest.TestCase):
    """Drive the real graph view to verify multi-select highlighting."""

    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        """Keep one QApplication alive for the test class."""
        cls.app = _application()

    def setUp(self) -> None:
        """Build a three-node graph in a live view."""
        from config.keybinds import KeybindStore
        from ui.node_graph.view import NodeGraphView

        self.project = Project(name="multi-select")
        self.project.width = 320
        self.project.height = 240
        self.source_id = self.project.add_node(SolidColorNode(), "source")
        self.blur_id = self.project.add_node(GaussianBlurNode(), "blur")
        self.viewer_id = self.project.add_node(ViewerNode(), "viewer")
        self.project.nodes[self.source_id].x = 40.0
        self.project.nodes[self.source_id].y = 40.0
        self.project.nodes[self.blur_id].x = 260.0
        self.project.nodes[self.blur_id].y = 40.0
        self.project.nodes[self.viewer_id].x = 500.0
        self.project.nodes[self.viewer_id].y = 40.0

        self.view = NodeGraphView(
            self.project, HistoryStack(self.project), KeybindStore()
        )
        self.view.resize(900, 600)

    def tearDown(self) -> None:
        """Release the graph view."""
        self.view.close()

    def _press_drag_release(
        self,
        start: QPointF,
        end: QPointF,
        *,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        """Simulate a left-button marquee drag between two scene points."""
        start_view = QPointF(self.view.mapFromScene(start))
        end_view = QPointF(self.view.mapFromScene(end))
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            start_view,
            start_view,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            end_view,
            end_view,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            end_view,
            end_view,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            modifiers,
        )
        self.view.mousePressEvent(press)
        self.view.mouseMoveEvent(move)
        self.view.mouseReleaseEvent(release)

    def test_dragging_empty_canvas_highlights_multiple_nodes(self) -> None:
        """A rubber-band drag over the canvas selects every enclosed node."""
        self._press_drag_release(QPointF(10.0, 10.0), QPointF(430.0, 220.0))
        self.assertEqual(self.view.selection_count(), 2)
        self.assertTrue(self.view.node_items[self.source_id].isSelected())
        self.assertTrue(self.view.node_items[self.blur_id].isSelected())
        self.assertFalse(self.view.node_items[self.viewer_id].isSelected())

    def test_ctrl_marquee_adds_to_the_existing_selection(self) -> None:
        """Holding Ctrl while dragging keeps what was already selected."""
        self.view.node_items[self.viewer_id].setSelected(True)
        self._press_drag_release(
            QPointF(10.0, 10.0),
            QPointF(430.0, 220.0),
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(self.view.selection_count(), 3)

    def test_escape_clears_the_selection(self) -> None:
        """Escape empties the current selection."""
        self.view.node_items[self.source_id].setSelected(True)
        self.view.node_items[self.blur_id].setSelected(True)
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        self.view.keyPressEvent(event)
        self.assertEqual(self.view.selection_count(), 0)

    def test_spotlight_dims_unselected_nodes(self) -> None:
        """Spotlight emphasis fades everything outside the selection."""
        self.view.node_items[self.source_id].setSelected(True)
        self.view.set_spotlight(True)
        self.assertLess(self.view.node_items[self.blur_id].opacity(), 1.0)
        self.assertAlmostEqual(
            self.view.node_items[self.source_id].opacity(), 1.0
        )

        self.view.set_spotlight(False)
        self.assertAlmostEqual(self.view.node_items[self.blur_id].opacity(), 1.0)

    def test_quick_action_bar_tracks_the_selection(self) -> None:
        """The floating bar appears with the selection and reflects its size."""
        self.view.node_items[self.source_id].setSelected(True)
        bar = self.view._selection_bar
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertFalse(bar.isHidden())

        states = bar.enabled_states()
        self.assertFalse(states["align_left"])
        self.assertFalse(states["distribute_h"])
        self.assertTrue(states["fit"])
        self.assertTrue(states["delete"])

        self.view.node_items[self.blur_id].setSelected(True)
        states = bar.enabled_states()
        self.assertTrue(states["align_left"])
        self.assertFalse(states["distribute_h"])

        self.view.node_items[self.viewer_id].setSelected(True)
        self.assertTrue(bar.enabled_states()["distribute_h"])

    def test_select_all_and_invert_through_the_view(self) -> None:
        """The view-level helpers select all nodes and then invert them."""
        self.view.select_all_nodes()
        self.assertEqual(self.view.selection_count(), 3)
        self.view.invert_selection()
        self.assertEqual(self.view.selection_count(), 0)


class SelectionMenuWiringTests(unittest.TestCase):
    """Verify the new selection entries exist and their handlers run."""

    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        """Keep one QApplication alive for the test class."""
        cls.app = _application()

    def setUp(self) -> None:
        """Build a two-node graph with everything selected."""
        from config.keybinds import KeybindStore
        from ui.node_graph.view import NodeGraphView

        self.project = Project(name="menu-wiring")
        self.source_id = self.project.add_node(SolidColorNode(), "source")
        self.blur_id = self.project.add_node(GaussianBlurNode(), "blur")
        self.assertTrue(
            self.project.connect_nodes(
                self.source_id, "frame", self.blur_id, "frame"
            )
        )
        self.view = NodeGraphView(
            self.project, HistoryStack(self.project), KeybindStore()
        )
        self.view.select_all_nodes()

    def tearDown(self) -> None:
        """Release the graph view."""
        self.view.close()

    def test_node_menu_exposes_selection_actions(self) -> None:
        """The node context menu lists the new quick actions."""
        from PyQt6.QtWidgets import QMenu
        from ui.node_graph.menus import NodeOperationsMenu

        menu = NodeOperationsMenu(self.view)
        texts = [action.text() for action in menu.actions()]
        self.assertIn("Toggle Bypass", texts)
        self.assertIn("Remove Attached Wires", texts)
        self.assertIn("Selection", texts)

        selection_menu = next(
            action.menu()
            for action in menu.actions()
            if action.menu() is not None and action.text() == "Selection"
        )
        assert isinstance(selection_menu, QMenu)
        submenu_texts = [action.text() for action in selection_menu.actions()]
        for expected in (
            "Invert Selection",
            "Select Connected",
            "Select Upstream",
            "Select Downstream",
            "Select Same Type",
            "Tidy Selection",
            "Fit Selection",
            "Spotlight Selection",
        ):
            self.assertIn(expected, submenu_texts)

    def test_triggering_selection_actions_is_safe(self) -> None:
        """Every non-dialog quick action runs without raising."""
        from PyQt6.QtGui import QAction
        from ui.node_graph.menus import NodeOperationsMenu

        # Dialog-opening entries (custom nodes, insert-after, delete) are
        # covered elsewhere; triggering them here would block on a modal.
        safe_labels = {
            "Toggle Bypass",
            "Remove Attached Wires",
            "Invert Selection",
            "Select Connected",
            "Select Upstream",
            "Select Downstream",
            "Select Same Type",
            "Tidy Selection",
            "Fit Selection",
            "Spotlight Selection",
            "Align Left",
            "Distribute Horizontally",
            "Fit to View",
            "Organize Graph",
        }
        menu = NodeOperationsMenu(self.view)
        triggered: set[str] = set()
        for action in menu.findChildren(QAction):
            if action.text() not in safe_labels or not action.isEnabled():
                continue
            action.trigger()
            triggered.add(action.text())

        self.assertIn("Toggle Bypass", triggered)
        self.assertIn("Tidy Selection", triggered)
        self.assertEqual(len(self.project.nodes), 2)

    def test_empty_canvas_menu_includes_selection_tools(self) -> None:
        """The canvas menu offers invert, expansion, and spotlight."""
        from ui.node_graph.menus import GraphContextMenu

        queued: list[str] = []
        menu = GraphContextMenu(
            QPointF(0.0, 0.0),
            on_add_node=lambda *_args: None,
            on_paste=lambda: queued.append("paste"),
            can_paste=False,
            on_select_all=lambda: queued.append("all"),
            on_fit_view=lambda: queued.append("fit"),
            on_organize_graph=lambda: queued.append("organize"),
            on_invert_selection=lambda: queued.append("invert"),
            on_select_connected=lambda: queued.append("connected"),
            on_toggle_spotlight=lambda: queued.append("spotlight"),
            spotlight_enabled=False,
            can_select_related=True,
            keybinds=self.view.keybinds,
            parent=self.view,
        )
        texts = [action.text() for action in menu.actions()]
        self.assertIn("Invert Selection", texts)
        self.assertIn("Select Connected", texts)
        self.assertIn("Spotlight Selection", texts)
        self.assertTrue(not queued)


if __name__ == "__main__":
    unittest.main()
