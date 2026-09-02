"""Node graph view with grid, vignette, and multi-select tools."""

from __future__ import annotations

from typing import Any, ClassVar

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
)

from config.keybinds import KeybindStore
from core.events import Connection, ObserverEvent
from core.history import (
    AddNodeCommand,
    CompositeCommand,
    ConnectCommand,
    DisconnectCommand,
    HistoryStack,
    MoveNodesCommand,
    RemoveNodesCommand,
)
from core.nodes import global_node_registry
from core.project import Project

from ui.node_graph.connection_item import ConnectionItem, PreviewWireItem
from ui.node_graph.constants import GRID_SPACING_PX, SOCKET_SNAP_DISTANCE_PX
from ui.node_graph.theme_state import current_graph_palette
from ui.node_graph.clipboard import GraphClipboard
from ui.node_graph.node_item import NodeItem
from ui.node_graph.search_palette import NodeSearchPalette
import ui.node_graph.operations as node_ops


class NodeGraphView(QGraphicsView):
    """Interactive node graph canvas."""

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
        self.layout_mode = node_ops.GraphLayoutMode.HIERARCHICAL

        self._configure_view()
        self.project.subscribe(self.on_project_changed)
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
        self.node_items.clear()
        self.connection_items.clear()
        self.scene.clear()
        self.project.subscribe(self.on_project_changed)
        for node_id in self.project.nodes:
            self.add_node_to_view(node_id)
        for connection in self.project.connections:
            self.add_connection_to_view(connection)
        QTimer.singleShot(40, self.fit_all_nodes)

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
            if isinstance(item, ConnectionItem):
                super().mousePressEvent(event)
                return
            if item is None:
                self._start_panning(event)
                return
            if not isinstance(item, NodeItem):
                self.selection_start = event.pos()
                self.selection_rect = QRect(self.selection_start, self.selection_start)
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.scene.clearSelection()
                event.accept()
                return
        super().mousePressEvent(event)

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
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.delete_selection():
                event.accept()
                return

        super().keyPressEvent(event)
