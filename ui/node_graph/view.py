"""Node graph view with grid, vignette, and multi-select tools."""

from __future__ import annotations

from typing import Any

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
)

from core.events import ObserverEvent
from core.nodes import global_node_registry
from core.project import Project
from ui.node_graph.constants import (
    COLOR_GRAPH_BG,
    COLOR_GRID_MAJOR,
    COLOR_GRID_MINOR,
    COLOR_MARQUEE,
    COLOR_MARQUEE_BORDER,
    COLOR_VIGNETTE,
    GRID_SPACING_PX,
)
from ui.node_graph.node_item import NodeItem
import ui.node_graph.operations as node_ops


class NodeGraphView(QGraphicsView):
    """Interactive node graph canvas."""

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.node_items: dict[str, NodeItem] = {}
        self.selection_start: QPoint | None = None
        self.selection_rect: QRect | None = None
        self._panning: bool = False
        self._pan_anchor: QPointF = QPointF()

        self._configure_view()
        self.project.subscribe(self.on_project_changed)
        for node_id in self.project.nodes:
            self.add_node_to_view(node_id)
        QTimer.singleShot(80, self.fit_all_nodes)

    def _configure_view(self) -> None:
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
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
        self.setBackgroundBrush(QBrush(COLOR_GRAPH_BG))
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)
        self.scene.setSceneRect(-10000, -10000, 20000, 20000)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def drawBackground(self, painter: QPainter | None, rect: QRectF) -> None:
        if painter is None:
            return
        painter.fillRect(rect, COLOR_GRAPH_BG)
        self._draw_grid(painter, rect)

    def drawForeground(self, painter: QPainter | None, _rect: QRectF) -> None:
        if painter is None:
            return
        self._draw_vignette(painter)
        if self.selection_rect is not None:
            self._draw_marquee(painter)

    def _draw_grid(self, painter: QPainter, rect: QRectF) -> None:
        left = int(rect.left()) - (int(rect.left()) % GRID_SPACING_PX)
        top = int(rect.top()) - (int(rect.top()) % GRID_SPACING_PX)
        painter.setPen(QPen(COLOR_GRID_MINOR, 1))
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
        painter.setPen(QPen(COLOR_GRID_MAJOR, 1))
        x = left_m
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += major
        y = top_m
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += major

    def _draw_vignette(self, painter: QPainter) -> None:
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
        gradient.setColorAt(1.0, COLOR_VIGNETTE)
        painter.fillRect(0, 0, width, height, QBrush(gradient))

        edge = QLinearGradient(0, 0, 0, 28)
        edge.setColorAt(0.0, QColor(0, 0, 0, 90))
        edge.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, width, 28, QBrush(edge))
        painter.restore()

    def _draw_marquee(self, painter: QPainter) -> None:
        if self.selection_rect is None:
            return
        painter.save()
        painter.resetTransform()
        painter.setBrush(COLOR_MARQUEE)
        painter.setPen(QPen(COLOR_MARQUEE_BORDER, 1.0))
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

    def on_project_changed(self, event: ObserverEvent, data: Any) -> None:
        if event == ObserverEvent.NodeAdded and isinstance(data, str):
            self.add_node_to_view(data)
        elif event == ObserverEvent.NodeRemoved and isinstance(data, str):
            self.remove_node_from_view(data)

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
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.scene.removeItem(item)

    def delete_node(self, node_id: str) -> None:
        self.project.remove_node(node_id)

    def duplicate_node(
        self,
        node_id: str,
        offset_x: float = 36,
        offset_y: float = 36,
    ) -> str | None:
        return node_ops.create_node_copy(self, node_id, offset_x, offset_y)

    def selected_nodes(self) -> list[NodeItem]:
        return node_ops.selected_node_items(self)

    def show_context_menu(self, position: QPoint) -> None:
        from ui.node_graph.menus import GraphContextMenu

        item = self.itemAt(position)
        if isinstance(item, NodeItem):
            return
        scene_pos = self.mapToScene(position)
        menu = GraphContextMenu(self.project, scene_pos, self)
        menu.node_selected.connect(self.on_node_selected)
        menu.select_all_requested.connect(self.select_all_nodes)
        menu.fit_view_requested.connect(self.fit_all_nodes)
        menu.exec(self.mapToGlobal(position))

    def show_node_context_menu(self, global_pos: QPoint) -> None:
        from ui.node_graph.menus import NodeOperationsMenu

        menu = NodeOperationsMenu(self, self)
        menu.exec(global_pos)

    def on_node_selected(self, name: str, category: str, position: QPointF) -> None:
        node = global_node_registry.create_node(name, category=category)
        if node is None:
            return
        node.x = position.x()
        node.y = position.y()
        self.project.add_node(node)

    def select_all_nodes(self) -> None:
        for item in self.node_items.values():
            item.setSelected(True)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_anchor = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item is None or not isinstance(item, NodeItem):
                self.selection_start = event.pos()
                self.selection_rect = QRect(self.selection_start, self.selection_start)
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.scene.clearSelection()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
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
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
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
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        factor = 1.12 if event.angleDelta().y() > 0 else 0.9
        scale = self.transform().m11() * factor
        if 0.2 <= scale <= 3.0:
            self.scale(factor, factor)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        key = event.key()
        mods = event.modifiers()
        items = self.selected_nodes()

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and items:
            node_ops.delete_items(self, items)
        elif key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self.select_all_nodes()
        elif key == Qt.Key.Key_D and mods & Qt.KeyboardModifier.ControlModifier and items:
            node_ops.duplicate_items(self, items)
        elif key == Qt.Key.Key_F:
            self.fit_all_nodes()
        else:
            super().keyPressEvent(event)
            return
        event.accept()
