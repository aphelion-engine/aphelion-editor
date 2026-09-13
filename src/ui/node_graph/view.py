"""Node graph view with grid, vignette, and multi-select tools."""

from __future__ import annotations

from typing import Any, ClassVar

import ui.node_graph.custom_node_ops as custom_node_ops
import ui.node_graph.operations as node_ops
import ui.node_graph.selection_ops as selection_ops
from config.keybinds import KeybindStore
from core.custom_node_store import global_custom_node_store
from core.events import Connection, ObserverEvent
from core.history import (AddNodeCommand, CompositeCommand, ConnectCommand,
                          DisconnectCommand, HistoryStack, MoveNodesCommand,
                          RemoveNodesCommand)
from core.nodes import global_node_registry
from core.project import Project
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QKeyEvent, QLinearGradient, QPainter,
                         QPainterPath, QPen, QRadialGradient, QWheelEvent)
from PyQt6.QtWidgets import (QDialog, QFrame, QGraphicsScene, QGraphicsView,
                             QMenu, QMessageBox)
from ui.node_graph.clipboard import GraphClipboard
from ui.node_graph.connection_item import ConnectionItem, PreviewWireItem
from ui.node_graph.constants import GRID_SPACING_PX, SOCKET_SNAP_DISTANCE_PX
from ui.node_graph.node_item import NodeItem
from ui.node_graph.search_palette import NodeSearchPalette
from ui.node_graph.selection_bar import SelectionActionBar
from ui.node_graph.selection_ops import SelectionTraversal
from ui.node_graph.theme_state import current_graph_palette


class NodeGraphView(QGraphicsView):
    """Interactive node graph canvas."""

    #: Emitted with the number of selected nodes whenever the selection changes.
    selection_changed = pyqtSignal(int)

    _MIN_ZOOM: ClassVar[float] = 0.2
    _MAX_ZOOM: ClassVar[float] = 3.0
    _ZOOM_IN_FACTOR: ClassVar[float] = 1.15
    _ZOOM_OUT_FACTOR: ClassVar[float] = 1.0 / _ZOOM_IN_FACTOR

    def __init__(
        self,
        project: Project,
        history: HistoryStack,
        keybinds: KeybindStore | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.history = history
        self.keybinds = keybinds or KeybindStore()
        self.clipboard = GraphClipboard()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.node_items: dict[str, NodeItem] = {}
        self.connection_items: dict[Connection, ConnectionItem] = {}
        self.selection_start: QPoint | None = None
        self.selection_rect: QRect | None = None
        self._panning: bool = False
        self._pan_anchor: QPointF = QPointF()
        self._pan_button: Qt.MouseButton | None = None
        self._context_menu: QMenu | None = None
        self._preview_wire: PreviewWireItem | None = None
        self._show_grid: bool = True
        self._drag_source: tuple[str, str, bool] | None = None
        self._snap_target: tuple[str, str, bool] | None = None
        self._cursor_scene_pos: QPointF = QPointF(0.0, 0.0)
        self._paste_generation: int = 0
        self._search_palette: NodeSearchPalette | None = None
        self._selection_bar: SelectionActionBar | None = None
        self._spotlight: bool = False
        self.layout_mode = node_ops.GraphLayoutMode.HIERARCHICAL

        self._configure_view()
        self.project.subscribe(self.on_project_changed)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        for node_id in self.project.nodes:
            self.add_node_to_view(node_id)
        for connection in self.project.connections:
            self.add_connection_to_view(connection)
        QTimer.singleShot(80, self.fit_all_nodes)

    def set_project(self, project: Project, history: HistoryStack) -> None:
        """Rebuild the graph view for a newly loaded project document."""
        self.cancel_connection_drag()
        self.project.unsubscribe(self.on_project_changed)
        self.project = project
        self.history = history
        self.clipboard.clear()
        self._paste_generation = 0
        self._spotlight = False
        if self._selection_bar is not None:
            self._selection_bar.hide()
        self.node_items.clear()
        self.connection_items.clear()
        self.scene.clear()
        self.project.subscribe(self.on_project_changed)
        for node_id in self.project.nodes:
            self.add_node_to_view(node_id)
        for connection in self.project.connections:
            self.add_connection_to_view(connection)
        QTimer.singleShot(40, self.fit_all_nodes)

    def resizeEvent(self, event: Any) -> None:
        """Keep the selection quick-action bar pinned to the viewport top."""
        super().resizeEvent(event)
        if self._selection_bar is not None:
            self._selection_bar.reposition()

    # ==================================================================
    # Selection highlight / quick actions
    # ==================================================================

    def notify(self, text: str, timeout: int = 2000) -> None:
        """Show a transient message on the editor status bar, if present."""
        window = self.window()
        status_bar = getattr(window, "statusBar", None)
        if not callable(status_bar):
            return
        status = status_bar()
        if status is not None:
            status.showMessage(text, timeout)

    def selection_count(self) -> int:
        """Return how many nodes are currently selected."""
        return len(self.selected_nodes())

    def is_spotlight_enabled(self) -> bool:
        """Whether unselected nodes are dimmed to highlight the selection."""
        return self._spotlight

    def set_spotlight(self, enabled: bool) -> None:
        """Dim everything outside the selection (or restore full brightness)."""
        enabled = bool(enabled)
        if enabled == self._spotlight:
            return
        self._spotlight = enabled
        self._sync_selection_visuals()

    def toggle_spotlight(self) -> bool:
        """Flip spotlight mode and return the new state."""
        self.set_spotlight(not self._spotlight)
        return self._spotlight

    def invert_selection(self) -> None:
        """Select every node that was not selected."""
        count = selection_ops.invert_selection(self)
        self.notify(f"Inverted selection — {count} node(s) selected")

    def select_connected(self) -> None:
        """Add every node connected to the selection through the graph."""
        self._report_expansion(
            selection_ops.select_related(self, SelectionTraversal.CONNECTED),
            "connected",
        )

    def select_upstream(self) -> None:
        """Add every node that feeds the selection."""
        self._report_expansion(
            selection_ops.select_related(self, SelectionTraversal.UPSTREAM),
            "upstream",
        )

    def select_downstream(self) -> None:
        """Add every node the selection feeds into."""
        self._report_expansion(
            selection_ops.select_related(self, SelectionTraversal.DOWNSTREAM),
            "downstream",
        )

    def select_same_type(self) -> None:
        """Add every node sharing a type with the selection."""
        self._report_expansion(
            selection_ops.select_same_type(self),
            "same type",
        )

    def fit_selection(self) -> None:
        """Frame just the selected nodes."""
        items = self.selected_nodes()
        if not items:
            self.notify("Select at least one node to frame it")
            return
        selection_ops.fit_selection(self, items)

    def tidy_selection(self) -> None:
        """Pack the selected nodes into a compact grid."""
        items = self.selected_nodes()
        if len(items) < 2:
            self.notify("Select two or more nodes to tidy them")
            return
        if selection_ops.tidy_selection(self, items):
            self.notify(f"Tidied {len(items)} nodes")

    def tidy_all_nodes(self) -> None:
        """Pack every node in the graph into a compact grid."""
        items = list(self.node_items.values())
        if len(items) < 2:
            return
        if selection_ops.tidy_selection(self, items):
            self.notify(f"Tidied {len(items)} nodes")

    def toggle_selection_bypass(self) -> None:
        """Bypass or re-enable every selected effect node."""
        items = self.selected_nodes()
        if not items:
            self.notify("Select at least one effect node to bypass")
            return
        count = selection_ops.toggle_selection_bypass(self, items)
        if count == 0:
            self.notify("None of the selected nodes can be bypassed")
            return
        self.notify(f"Toggled {count} node(s)")

    def remove_selection_wires(self) -> None:
        """Disconnect every wire attached to the selection."""
        items = self.selected_nodes()
        if not items:
            return
        count = selection_ops.remove_selection_wires(self, items)
        self.notify(
            f"Disconnected {count} wire(s)" if count else "No wires attached"
        )

    def _report_expansion(self, count: int, label: str) -> None:
        """Report the result of a selection-expansion action."""
        if count == 0:
            self.notify("Select a node first")
            return
        self.notify(f"Selected {count} {label} node(s)")

    def _on_scene_selection_changed(self) -> None:
        """Keep visuals and the quick-action bar in sync with the selection."""
        self._sync_selection_visuals()
        self._update_selection_bar()
        self.selection_changed.emit(self.selection_count())

    def _sync_selection_visuals(self) -> None:
        """Apply (or clear) spotlight dimming across nodes and wires."""
        selected_ids = {
            item.node_id
            for item in self.scene.selectedItems()
            if isinstance(item, NodeItem)
        }
        for node_id, item in self.node_items.items():
            item.set_dimmed(self._spotlight and node_id not in selected_ids)
        for connection, item in self.connection_items.items():
            touches_selection = (
                connection.output_node_id in selected_ids
                or connection.input_node_id in selected_ids
            )
            item.set_dimmed(self._spotlight and not touches_selection)

    def _update_selection_bar(self) -> None:
        """Show, refresh, or hide the floating selection action bar."""
        items = self.selected_nodes()
        if not items:
            if self._selection_bar is not None:
                self._selection_bar.hide()
            return
        if self._selection_bar is None:
            self._selection_bar = SelectionActionBar(self, self.viewport())
        self._selection_bar.refresh(items)
        self._selection_bar.reposition()
        self._selection_bar.show()
        self._selection_bar.raise_()

    @property
    def is_connection_dragging(self) -> bool:
        return self._drag_source is not None

    def _configure_view(self) -> None:
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate
        )
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontSavePainterState,
            True,
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        palette = current_graph_palette()
        self.setBackgroundBrush(QBrush(palette.graph_bg))
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)
        self.scene.setSceneRect(-10000, -10000, 20000, 20000)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_show_grid(self, enabled: bool) -> None:
        """Toggle background grid rendering."""
        self._show_grid = enabled
        self.viewport().update()

    def refresh_theme(self) -> None:
        """Repaint the canvas after theme palette changes."""
        palette = current_graph_palette()
        self.setBackgroundBrush(QBrush(palette.graph_bg))
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()
        for item in self.node_items.values():
            item.update()

    def drawBackground(self, painter: QPainter | None, rect: QRectF) -> None:
        if painter is None:
            return
        palette = current_graph_palette()
        painter.fillRect(rect, palette.graph_bg)
        if self._show_grid:
            self._draw_grid(painter, rect, palette)

    def drawForeground(self, painter: QPainter | None, _rect: QRectF) -> None:
        if painter is None:
            return
        self._draw_vignette(painter, current_graph_palette())
        if self.selection_rect is not None:
            self._draw_marquee(painter, current_graph_palette())

    def _draw_grid(self, painter: QPainter, rect: QRectF, palette: object) -> None:
        left = int(rect.left()) - (int(rect.left()) % GRID_SPACING_PX)
        top = int(rect.top()) - (int(rect.top()) % GRID_SPACING_PX)
        painter.setPen(QPen(palette.grid_minor, 1))  # type: ignore[attr-defined]
        x = left
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += GRID_SPACING_PX
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += GRID_SPACING_PX

        major = GRID_SPACING_PX * 4
        left_m = int(rect.left()) - (int(rect.left()) % major)
        top_m = int(rect.top()) - (int(rect.top()) % major)
        painter.setPen(QPen(palette.grid_major, 1))  # type: ignore[attr-defined]
        x = left_m
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += major
        y = top_m
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += major

    def _draw_vignette(self, painter: QPainter, palette: object) -> None:
        painter.save()
        painter.resetTransform()
        viewport = self.viewport()
        if viewport is None:
            painter.restore()
            return
        width = viewport.width()
        height = viewport.height()
        gradient = QRadialGradient(width / 2, height / 2, max(width, height) * 0.72)
        gradient.setColorAt(0.55, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, palette.vignette)  # type: ignore[attr-defined]
        painter.fillRect(0, 0, width, height, QBrush(gradient))

        edge = QLinearGradient(0, 0, 0, 28)
        edge.setColorAt(0.0, QColor(0, 0, 0, 90))
        edge.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, width, 28, QBrush(edge))
        painter.restore()

    def _draw_marquee(self, painter: QPainter, palette: object) -> None:
        if self.selection_rect is None:
            return
        painter.save()
        painter.resetTransform()
        painter.setBrush(palette.marquee)  # type: ignore[attr-defined]
        painter.setPen(QPen(palette.marquee_border, 1.0))  # type: ignore[attr-defined]
        painter.drawRect(self.selection_rect)
        painter.restore()

    def fit_all_nodes(self) -> None:
        """Fit all nodes into the viewport."""
        if not self.scene.items():
            return
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isValid():
            return
        padded = bounds.adjusted(-140, -140, 140, 140)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)
        scale = self.transform().m11()
        if scale < 0.35:
            self.scale(0.35 / scale, 0.35 / scale)
        elif scale > 1.4:
            self.scale(1.4 / scale, 1.4 / scale)

    def organize_graph(self) -> bool:
        """Clean up node positions using dependency-aware auto layout."""
        return node_ops.organize_graph(self)

    def on_project_changed(self, event: ObserverEvent, data: Any) -> None:
        if event == ObserverEvent.NodeAdded and isinstance(data, str):
            self.add_node_to_view(data)
        elif event == ObserverEvent.NodeRemoved and isinstance(data, str):
            self.remove_node_from_view(data)
        elif event == ObserverEvent.ConnectionCreated and isinstance(data, Connection):
            self.add_connection_to_view(data)
        elif event == ObserverEvent.ConnectionRemoved and isinstance(data, Connection):
            self.remove_connection_from_view(data)
        elif event == ObserverEvent.NodesMoved and isinstance(data, dict):
            self._apply_nodes_moved(data)

    def _apply_nodes_moved(self, positions: dict[str, tuple[float, float]]) -> None:
        """Sync item transforms after undo/redo or programmatic moves."""
        for node_id, (x, y) in positions.items():
            item = self.node_items.get(node_id)
            if item is None:
                continue
            item.setPos(float(x), float(y))
            self.refresh_connections_for_node(node_id)

    def add_node_to_view(self, node_id: str) -> None:
        if node_id in self.node_items:
            return
        node = self.project.nodes.get(node_id)
        if node is None:
            return
        item = NodeItem(node, node_id)
        item.graph_view = self
        self.scene.addItem(item)
        self.node_items[node_id] = item

    def remove_node_from_view(self, node_id: str) -> None:
        stale = [
            conn
            for conn in self.connection_items
            if conn.output_node_id == node_id or conn.input_node_id == node_id
        ]
        for conn in stale:
            self.remove_connection_from_view(conn)
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.scene.removeItem(item)

    def add_connection_to_view(self, connection: Connection) -> None:
        if connection in self.connection_items:
            return
        item = ConnectionItem(connection, self)
        self.scene.addItem(item)
        self.connection_items[connection] = item

    def remove_connection_from_view(self, connection: Connection) -> None:
        item = self.connection_items.pop(connection, None)
        if item is not None:
            self.scene.removeItem(item)

    def socket_scene_pos(
        self,
        node_id: str,
        socket_name: str,
        *,
        is_input: bool,
    ) -> QPointF | None:
        item = self.node_items.get(node_id)
        if item is None:
            return None
        return item.get_socket_position(socket_name, is_input)

    def refresh_connections_for_node(self, node_id: str) -> None:
        for conn, item in self.connection_items.items():
            if conn.output_node_id == node_id or conn.input_node_id == node_id:
                item.update_path()

    def begin_connection_drag(
        self,
        node_id: str,
        socket_name: str,
        is_input: bool,
        scene_pos: QPointF,
    ) -> None:
        """Start a view-owned wire drag (no mouse grab — avoids UI freezes)."""
        start = self.socket_scene_pos(node_id, socket_name, is_input=is_input)
        if start is None:
            return
        self._drag_source = (node_id, socket_name, is_input)
        self._snap_target = None
        if self._preview_wire is not None:
            self.scene.removeItem(self._preview_wire)
        self._preview_wire = PreviewWireItem()
        self.scene.addItem(self._preview_wire)
        self._set_preview_endpoints(start, scene_pos, snapped=False)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.setCursor(Qt.CursorShape.CrossCursor)
        # Track moves even if the cursor briefly leaves an item; view owns the drag.
        self.setMouseTracking(True)

    def update_connection_drag(self, scene_pos: QPointF) -> None:
        if self._preview_wire is None or self._drag_source is None:
            return
        node_id, socket_name, is_input = self._drag_source
        start = self.socket_scene_pos(node_id, socket_name, is_input=is_input)
        if start is None:
            return
        snap = self._nearest_compatible_socket(scene_pos, node_id, is_input)
        self._snap_target = None if snap is None else (snap[0], snap[1], snap[2])
        end = scene_pos if snap is None else snap[3]
        self._set_preview_endpoints(start, end, snapped=snap is not None)

    def finish_connection_drag(self, scene_pos: QPointF) -> None:
        source = self._drag_source
        target = self._snap_target
        if target is None:
            nearest = (
                self._nearest_compatible_socket(
                    scene_pos,
                    source[0],
                    source[2],
                )
                if source is not None
                else None
            )
            if nearest is not None:
                target = (nearest[0], nearest[1], nearest[2])
        self._clear_connection_drag()
        if source is None or target is None:
            return
        src_node, src_slot, src_is_input = source
        dst_node, dst_slot, dst_is_input = target
        if src_node == dst_node or src_is_input == dst_is_input:
            return
        if src_is_input:
            out_node, out_slot = dst_node, dst_slot
            in_node, in_slot = src_node, src_slot
        else:
            out_node, out_slot = src_node, src_slot
            in_node, in_slot = dst_node, dst_slot
        self.history.push(
            ConnectCommand(out_node, out_slot, in_node, in_slot)
        )

    def cancel_connection_drag(self) -> None:
        """Abort an in-progress wire drag without creating a connection."""
        self._clear_connection_drag()

    def _clear_connection_drag(self) -> None:
        self._drag_source = None
        self._snap_target = None
        if self._preview_wire is not None:
            self.scene.removeItem(self._preview_wire)
            self._preview_wire = None
        self.setMouseTracking(False)
        self.unsetCursor()

    def _set_preview_endpoints(
        self,
        fixed: QPointF,
        free: QPointF,
        *,
        snapped: bool,
    ) -> None:
        if self._preview_wire is None or self._drag_source is None:
            return
        _, _, is_input = self._drag_source
        # Always draw visually from output toward input.
        if is_input:
            self._preview_wire.set_endpoints(free, fixed, snapped=snapped)
        else:
            self._preview_wire.set_endpoints(fixed, free, snapped=snapped)

    def _event_scene_pos(self, event: Any) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def _try_begin_socket_drag(self, event: Any) -> bool:
        """If press hits a socket, start a connection drag and return True."""
        scene_pos = self._event_scene_pos(event)
        for item in self.scene.items(scene_pos):
            if not isinstance(item, NodeItem):
                continue
            local = item.mapFromScene(scene_pos)
            hit = item.socket_at(local)
            if hit is None:
                continue
            socket_name, is_input = hit
            self.begin_connection_drag(
                item.node_id,
                socket_name,
                is_input,
                scene_pos,
            )
            return True
        return False

    def _nearest_compatible_socket(
        self,
        scene_pos: QPointF,
        source_node_id: str,
        source_is_input: bool,
    ) -> tuple[str, str, bool, QPointF] | None:
        """Return nearest opposite-side socket within snap distance, if any."""
        best: tuple[str, str, bool, QPointF] | None = None
        best_dist_sq = SOCKET_SNAP_DISTANCE_PX * SOCKET_SNAP_DISTANCE_PX
        want_input = not source_is_input
        for node_id, item in self.node_items.items():
            if node_id == source_node_id:
                continue
            sockets = item.input_sockets if want_input else item.output_sockets
            for socket_name in sockets:
                pos = item.get_socket_position(socket_name, want_input)
                dx = pos.x() - scene_pos.x()
                dy = pos.y() - scene_pos.y()
                dist_sq = dx * dx + dy * dy
                if dist_sq <= best_dist_sq:
                    best_dist_sq = dist_sq
                    best = (node_id, socket_name, want_input, pos)
        return best

    def delete_node(self, node_id: str) -> None:
        self.history.push(RemoveNodesCommand([node_id]))

    def duplicate_node(
        self,
        node_id: str,
        offset_x: float = 36,
        offset_y: float = 36,
    ) -> str | None:
        return node_ops.create_node_copy(self, node_id, offset_x, offset_y)

    def commit_node_move(
        self,
        before: dict[str, tuple[float, float]],
        after: dict[str, tuple[float, float]],
    ) -> None:
        """Record a completed interactive node drag as one undo step."""
        self.history.push(MoveNodesCommand(before, after))

    def selected_nodes(self) -> list[NodeItem]:
        return node_ops.selected_node_items(self)

    def show_context_menu(self, position: QPoint) -> None:
        from ui.node_graph.menus import GraphContextMenu

        item = self.itemAt(position)
        if isinstance(item, NodeItem):
            return
        scene_pos = self.mapToScene(position)
        self._cursor_scene_pos = scene_pos
        # Keep a strong reference until exec finishes so actions stay alive.
        self._context_menu = GraphContextMenu(
            scene_pos,
            on_add_node=self.insert_node,
            on_paste=lambda: node_ops.paste_items(self, scene_pos),
            can_paste=not self.clipboard.is_empty,
            on_select_all=self.select_all_nodes,
            on_fit_view=self.fit_all_nodes,
            on_organize_graph=self.organize_graph,
            on_invert_selection=self.invert_selection,
            on_select_connected=self.select_connected,
            on_toggle_spotlight=self.toggle_spotlight,
            spotlight_enabled=self._spotlight,
            can_select_related=bool(self.selected_nodes()),
            keybinds=self.keybinds,
            parent=self,
        )
        self._context_menu.exec(self.mapToGlobal(position))
        self._context_menu = None

    def show_node_context_menu(self, global_pos: QPoint) -> None:
        from ui.node_graph.menus import NodeOperationsMenu

        self._context_menu = NodeOperationsMenu(self, self)
        self._context_menu.exec(global_pos)
        self._context_menu = None

    # ==================================================================
    # Custom nodes
    # ==================================================================

    def create_custom_node_from_selection(self) -> str | None:
        """Collapse the selected nodes into a reusable custom node."""
        from ui.dialogs.custom_node_dialog import CustomNodeCreateDialog

        node_ids = [
            item.node_id
            for item in self.selected_nodes()
            if item.node_id in self.project.nodes
        ]
        collapsible = [
            node_id
            for node_id in node_ids
            if custom_node_ops.is_collapsible(self.project.nodes[node_id])
        ]
        if not collapsible:
            QMessageBox.information(
                self,
                "Create Custom Node",
                "Select one or more processing nodes first.\n\n"
                "Viewers cannot be part of a custom node; wires leaving the "
                "selection become exposed outputs instead.",
            )
            return None

        dialog = CustomNodeCreateDialog(
            self,
            project=self.project,
            node_ids=node_ids,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        node_id = custom_node_ops.collapse_to_custom_node(
            self,
            node_ids,
            name=dialog.node_name,
            description=dialog.description,
            color=dialog.color,
        )
        if node_id is None:
            QMessageBox.warning(
                self,
                "Create Custom Node",
                "Could not create the custom node from this selection.",
            )
            return None

        if dialog.edit_after:
            self.edit_custom_node(node_id)

        status = self.window().statusBar() if self.window() is not None else None
        if status is not None:
            status.showMessage(
                f"Created custom node: {dialog.node_name}", 2500)
        return node_id

    def edit_custom_node(self, node_id: str) -> bool:
        """Open the definition editor for a custom node instance."""
        from core.nodes.custom_nodes import CustomNode
        from ui.dialogs.custom_node_dialog import CustomNodeEditorDialog

        node = self.project.nodes.get(node_id)
        if not isinstance(node, CustomNode):
            return False

        previous_name = node.definition_name
        dialog = CustomNodeEditorDialog(
            node.definition,
            self,
            keybinds=self.keybinds,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        definition = dialog.definition
        if definition is None:
            return False

        if (
            previous_name != definition.name
            and global_custom_node_store.has(previous_name)
        ):
            global_custom_node_store.remove(previous_name, persist=False)
        global_custom_node_store.upsert(definition)
        custom_node_ops.apply_definition_to_project(
            self,
            definition,
            previous_name=previous_name,
        )
        return True

    def edit_selected_custom_node(self) -> bool:
        items = self.selected_nodes()
        if len(items) != 1:
            return False
        return self.edit_custom_node(items[0].node_id)

    def expand_selected_custom_node(self) -> bool:
        """Dissolve the selected custom node into its underlying nodes."""
        items = self.selected_nodes()
        if len(items) != 1:
            QMessageBox.information(
                self,
                "Expand Custom Node",
                "Select a single custom node to expand.",
            )
            return False
        if not custom_node_ops.expand_custom_node(self, items[0].node_id):
            QMessageBox.information(
                self,
                "Expand Custom Node",
                "The selected node is not a custom node.",
            )
            return False
        return True

    def copy_selection(self) -> None:
        """Copy selected nodes into the graph clipboard."""
        items = self.selected_nodes()
        if items and node_ops.copy_items(self, items):
            self._paste_generation = 0

    @property
    def cursor_scene_pos(self) -> QPointF:
        """Last known cursor position in scene coordinates."""
        return QPointF(self._cursor_scene_pos)

    def paste_clipboard(self) -> None:
        """Paste clipboard nodes near the last cursor / view center."""
        node_ops.paste_items(self, self._cursor_scene_pos)

    def consume_paste_generation(self) -> int:
        """Return the current paste stack index and advance it."""
        generation = self._paste_generation
        self._paste_generation += 1
        return generation

    def open_node_search(self) -> None:
        """Open the Tab search palette for creating a node at the cursor."""
        if self._search_palette is None:
            self._search_palette = NodeSearchPalette(
                self,
                on_chosen=self._create_from_search,
                keybinds=self.keybinds,
            )
        self._search_palette.open_palette()

    def _create_from_search(self, name: str, category: str) -> None:
        self.insert_node(name, category, self._cursor_scene_pos)

    def insert_node(
        self,
        name: str,
        category: str,
        position: QPointF | None = None,
    ) -> str | None:
        """Create a registry node at ``position`` (or view center) and select it."""
        node = global_node_registry.create_node(name, category=category)
        if node is None:
            return None

        if position is None:
            position = self.view_center_scene_pos()
        node.x = position.x()
        node.y = position.y()
        command = AddNodeCommand(node)
        if not self.history.push(command):
            return None
        node_id = command.node_id
        if node_id is None:
            return None

        # Ensure the item exists even if an observer failed to run.
        self.add_node_to_view(node_id)
        self.scene.clearSelection()
        item = self.node_items.get(node_id)
        if item is not None:
            item.setSelected(True)
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()
        return node_id

    def view_center_scene_pos(self) -> QPointF:
        """Return the scene coordinate at the center of the viewport."""
        viewport = self.viewport()
        if viewport is None:
            return QPointF(0.0, 0.0)
        return self.mapToScene(viewport.rect().center())

    def select_all_nodes(self) -> None:
        for item in self.node_items.values():
            item.setSelected(True)

    def _start_panning(self, event: Any) -> None:
        self._panning = True
        self._pan_button = event.button()
        self._pan_anchor = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._start_panning(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            # Own socket drags at the view so move/release keep tracking the cursor.
            if self._try_begin_socket_drag(event):
                event.accept()
                return

            item = self.itemAt(event.pos())
            if isinstance(item, NodeItem):
                super().mousePressEvent(event)
                return
            if isinstance(item, ConnectionItem):
                super().mousePressEvent(event)
                return
            # Empty canvas: rubber-band select. Ctrl keeps the existing
            # selection so several sweeps can be accumulated; middle-drag
            # (handled above) remains the way to pan.
            self._begin_marquee(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def _begin_marquee(self, event: Any) -> None:
        """Start a rubber-band selection over empty canvas."""
        self.selection_start = event.pos()
        self.selection_rect = QRect(self.selection_start, self.selection_start)
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.scene.clearSelection()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._update_selection_bar()

    def mouseMoveEvent(self, event: Any) -> None:
        self._cursor_scene_pos = self._event_scene_pos(event)

        if self.is_connection_dragging:
            self.update_connection_drag(self._cursor_scene_pos)
            event.accept()
            return

        if self._panning:
            delta = event.position() - self._pan_anchor
            self._pan_anchor = event.position()
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            if h_bar is not None:
                h_bar.setValue(h_bar.value() - int(delta.x()))
            if v_bar is not None:
                v_bar.setValue(v_bar.value() - int(delta.y()))
            event.accept()
            return

        if self.selection_start is not None:
            self.selection_rect = QRect(self.selection_start, event.pos()).normalized()
            polygon = self.mapToScene(self.selection_rect)
            path = QPainterPath()
            path.addPolygon(polygon)
            mode = (
                Qt.ItemSelectionOperation.AddToSelection
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier
                else Qt.ItemSelectionOperation.ReplaceSelection
            )
            self.scene.setSelectionArea(
                path,
                mode,
                Qt.ItemSelectionMode.IntersectsItemShape,
            )
            viewport = self.viewport()
            if viewport is not None:
                viewport.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self.is_connection_dragging and event.button() == Qt.MouseButton.LeftButton:
            self.finish_connection_drag(self._event_scene_pos(event))
            event.accept()
            return
        if self._panning and event.button() == self._pan_button:
            self._panning = False
            self._pan_button = None
            self.unsetCursor()
            event.accept()
            return
        if self.selection_start is not None:
            self.selection_start = None
            self.selection_rect = None
            viewport = self.viewport()
            if viewport is not None:
                viewport.update()
            event.accept()
            return
        if self._panning:
            self._panning = False
            self._pan_button = None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            super().wheelEvent(event)
            return

        current_scale = self.transform().m11()
        zoom_factor = self._ZOOM_IN_FACTOR if delta_y > 0 else self._ZOOM_OUT_FACTOR
        target_scale = max(
            self._MIN_ZOOM,
            min(self._MAX_ZOOM, current_scale * zoom_factor),
        )
        applied_factor = target_scale / current_scale if current_scale != 0 else 1.0
        if abs(applied_factor - 1.0) < 1e-6:
            event.accept()
            return

        cursor_view_pos = event.position().toPoint()
        before = self.mapToScene(cursor_view_pos)
        self.scale(applied_factor, applied_factor)
        after = self.mapToScene(cursor_view_pos)
        delta = after - before
        self.translate(delta.x(), delta.y())
        event.accept()

    def delete_selection(self) -> bool:
        """Delete selected wires or nodes. Returns whether something was removed."""
        selected_wires = [
            item
            for item in self.scene.selectedItems()
            if isinstance(item, ConnectionItem)
        ]
        if selected_wires:
            commands = [
                DisconnectCommand(wire.connection) for wire in selected_wires
            ]
            if len(commands) == 1:
                return self.history.push(commands[0])
            return self.history.push(
                CompositeCommand(commands, f"Disconnect {len(commands)} Wires")
            )
        items = self.selected_nodes()
        if items:
            node_ops.delete_items(self, items)
            return True
        return False

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        key = event.key()
        palette = self._search_palette

        # Document shortcuts live on EditorActions; keep graph-local escapes here.
        if key == Qt.Key.Key_Escape:
            if palette is not None and palette.isVisible():
                palette.close_palette()
            elif self.is_connection_dragging:
                self.cancel_connection_drag()
            elif self.scene.selectedItems():
                self.scene.clearSelection()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.delete_selection():
                event.accept()
                return

        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            if self._nudge_from_key(event, key):
                event.accept()
                return

        super().keyPressEvent(event)

    def _nudge_from_key(self, event: QKeyEvent, key: int) -> bool:
        """Move the selection with Shift+Arrow keys (+Ctrl for big steps)."""
        modifiers = event.modifiers()
        if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
            return False
        items = self.selected_nodes()
        if not items:
            return False
        step = (
            selection_ops.NUDGE_STEP_COARSE_PX
            if modifiers & Qt.KeyboardModifier.ControlModifier
            else selection_ops.NUDGE_STEP_PX
        )
        dx = (
            -step
            if key == Qt.Key.Key_Left
            else step
            if key == Qt.Key.Key_Right
            else 0.0
        )
        dy = (
            -step if key == Qt.Key.Key_Up else step if key == Qt.Key.Key_Down else 0.0
        )
        return selection_ops.nudge_selection(self, items, dx, dy)
