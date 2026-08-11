"""Visual node item for the graph editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from core.nodes import Node
from ui.node_graph.constants import (
    BODY_PADDING_PX,
    COLOR_NODE_BODY,
    COLOR_NODE_BODY_HOVER,
    COLOR_NODE_BORDER,
    COLOR_NODE_BORDER_HOVER,
    COLOR_SELECTION,
    COLOR_SELECTION_SOFT,
    COLOR_SOCKET_INPUT,
    COLOR_SOCKET_OUTPUT,
    COLOR_SOCKET_RING,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    CORNER_RADIUS_PX,
    HEADER_HEIGHT_PX,
    NODE_MIN_HEIGHT_PX,
    NODE_WIDTH_PX,
    SOCKET_EDGE_GAP_PX,
    SOCKET_SIZE_PX,
    SOCKET_SPACING_PX,
)

if TYPE_CHECKING:
    from ui.node_graph.view import NodeGraphView


class NodeItem(QGraphicsRectItem):
    """Painted node with header accent and large sockets."""

    def __init__(self, node: Node, node_id: str) -> None:
        height = self._compute_height(node)
        node.width = NODE_WIDTH_PX
        node.height = height
        super().__init__(0, 0, NODE_WIDTH_PX, height)

        self.node = node
        self.node_id = node_id
        self.graph_view: NodeGraphView | None = None
        self.is_hovered: bool = False
        self._drag_origins: dict[int, QPointF] = {}

        r, g, b = node.node_color
        self.accent_color = QColor(r, g, b)

        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setCacheMode(QGraphicsItem.CacheMode.ItemCoordinateCache)
        self.setAcceptHoverEvents(True)
        self.setZValue(1.0)

        self.input_sockets: dict[str, QRect] = {}
        self.output_sockets: dict[str, QRect] = {}
        self._calculate_socket_positions()
        self.setPen(Qt.PenStyle.NoPen)
        self.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def _compute_height(node: Node) -> int:
        socket_count = max(len(node.inputs), len(node.outputs), 1)
        body = BODY_PADDING_PX * 2 + socket_count * SOCKET_SPACING_PX
        return max(NODE_MIN_HEIGHT_PX, HEADER_HEIGHT_PX + body)

    def _calculate_socket_positions(self) -> None:
        start_y = HEADER_HEIGHT_PX + BODY_PADDING_PX + SOCKET_SIZE_PX // 2
        y = start_y
        for name in self.node.inputs:
            self.input_sockets[name] = QRect(
                -SOCKET_SIZE_PX // 2 - SOCKET_EDGE_GAP_PX,
                y - SOCKET_SIZE_PX // 2,
                SOCKET_SIZE_PX,
                SOCKET_SIZE_PX,
            )
            y += SOCKET_SPACING_PX

        y = start_y
        for name in self.node.outputs:
            self.output_sockets[name] = QRect(
                NODE_WIDTH_PX - SOCKET_SIZE_PX // 2 + SOCKET_EDGE_GAP_PX,
                y - SOCKET_SIZE_PX // 2,
                SOCKET_SIZE_PX,
                SOCKET_SIZE_PX,
            )
            y += SOCKET_SPACING_PX

    def boundingRect(self) -> QRectF:
        pad = SOCKET_SIZE_PX
        return self.rect().adjusted(-pad, -4, pad, 4)

    def paint(
        self,
        painter: QPainter | None,
        _option: QStyleOptionGraphicsItem | None,
        _widget: QWidget | None,
    ) -> None:
        if painter is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = self.rect()
        selected = self.isSelected()
        self._paint_body(painter, body, selected)
        self._paint_header(painter, body)
        self._paint_labels(painter, body)
        self._paint_sockets(painter)

    def _paint_body(self, painter: QPainter, body: QRectF, selected: bool) -> None:
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(COLOR_SELECTION_SOFT)
            painter.drawRoundedRect(
                body.adjusted(-3, -3, 3, 3),
                CORNER_RADIUS_PX + 2,
                CORNER_RADIUS_PX + 2,
            )
            border = COLOR_SELECTION
            fill = COLOR_NODE_BODY_HOVER
            width = 2.0
        else:
            border = COLOR_NODE_BORDER_HOVER if self.is_hovered else COLOR_NODE_BORDER
            fill = COLOR_NODE_BODY_HOVER if self.is_hovered else COLOR_NODE_BODY
            width = 1.2

        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(border, width))
        painter.drawRoundedRect(body, CORNER_RADIUS_PX, CORNER_RADIUS_PX)

    def _paint_header(self, painter: QPainter, body: QRectF) -> None:
        header = QRectF(body.x(), body.y(), body.width(), HEADER_HEIGHT_PX)
        path_clip = body
        painter.setPen(Qt.PenStyle.NoPen)
        accent = QColor(self.accent_color)
        accent.setAlpha(220)
        painter.setBrush(accent)
        painter.drawRoundedRect(
            QRectF(header.x(), header.y(), header.width(), HEADER_HEIGHT_PX + 6),
            CORNER_RADIUS_PX,
            CORNER_RADIUS_PX,
        )
        painter.setBrush(COLOR_NODE_BODY if not self.is_hovered else COLOR_NODE_BODY_HOVER)
        painter.drawRect(
            QRectF(
                path_clip.x(),
                path_clip.y() + HEADER_HEIGHT_PX,
                path_clip.width(),
                path_clip.height() - HEADER_HEIGHT_PX,
            )
        )
        painter.setBrush(QColor(255, 255, 255, 28))
        painter.drawRect(QRectF(header.x(), header.y(), header.width(), 1.5))

    def _paint_labels(self, painter: QPainter, body: QRectF) -> None:
        title_font = QFont("Segoe UI", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(COLOR_TEXT_PRIMARY)
        title_rect = QRect(
            int(body.x()) + 10,
            int(body.y()) + 2,
            int(body.width()) - 20,
            16,
        )
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.node.name,
        )

        meta_font = QFont("Segoe UI", 8)
        painter.setFont(meta_font)
        painter.setPen(QColor(255, 255, 255, 180))
        meta_rect = QRect(
            int(body.x()) + 10,
            int(body.y()) + 16,
            int(body.width()) - 20,
            12,
        )
        painter.drawText(
            meta_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.node.node_category,
        )

        label_font = QFont("Segoe UI", 8)
        painter.setFont(label_font)
        self._paint_socket_labels(painter)

    def _paint_socket_labels(self, painter: QPainter) -> None:
        painter.setPen(COLOR_TEXT_SECONDARY)
        for name, rect in self.input_sockets.items():
            text_rect = QRect(
                SOCKET_SIZE_PX,
                rect.center().y() - 7,
                NODE_WIDTH_PX // 2 - 8,
                14,
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                name,
            )
        for name, rect in self.output_sockets.items():
            text_rect = QRect(
                NODE_WIDTH_PX // 2,
                rect.center().y() - 7,
                NODE_WIDTH_PX // 2 - SOCKET_SIZE_PX,
                14,
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                name,
            )

    def _paint_sockets(self, painter: QPainter) -> None:
        for rect in self.input_sockets.values():
            self._paint_socket(painter, rect, COLOR_SOCKET_INPUT)
        for rect in self.output_sockets.values():
            self._paint_socket(painter, rect, COLOR_SOCKET_OUTPUT)

    def _paint_socket(self, painter: QPainter, rect: QRect, fill: QColor) -> None:
        painter.setPen(QPen(COLOR_SOCKET_RING, 2.0))
        painter.setBrush(QBrush(fill))
        painter.drawEllipse(rect)
        inner = rect.adjusted(4, 4, -4, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 70)))
        painter.drawEllipse(inner)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            if not self.isSelected():
                scene = self.scene()
                if scene is not None and not (
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier
                ):
                    scene.clearSelection()
                self.setSelected(True)
            if self.graph_view is not None:
                self.graph_view.show_node_context_menu(event.screenPos())
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            scene = self.scene()
            if ctrl:
                self.setSelected(not self.isSelected())
                event.accept()
                return
            if scene is not None and not self.isSelected():
                scene.clearSelection()
                self.setSelected(True)
            self._capture_drag_origins()
            super().mousePressEvent(event)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        origin = self._drag_origins.get(id(self), self.pos())
        super().mouseMoveEvent(event)
        delta = self.pos() - origin
        for item_id, start in self._drag_origins.items():
            if item_id == id(self):
                continue
            for item in self._selected_node_items():
                if id(item) == item_id:
                    item.setPos(start + delta)
                    item._sync_node_position()
        self._sync_node_position()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        super().mouseReleaseEvent(event)
        for item in self._selected_node_items():
            item._sync_node_position()
        self._drag_origins.clear()

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def _capture_drag_origins(self) -> None:
        self._drag_origins = {
            id(item): item.pos() for item in self._selected_node_items()
        }
        if id(self) not in self._drag_origins:
            self._drag_origins[id(self)] = self.pos()

    def _selected_node_items(self) -> list[NodeItem]:
        scene = self.scene()
        if scene is None:
            return [self]
        return [item for item in scene.selectedItems() if isinstance(item, NodeItem)]

    def _sync_node_position(self) -> None:
        self.node.x = self.pos().x()
        self.node.y = self.pos().y()

    def get_socket_position(self, socket_name: str, is_input: bool) -> QPointF:
        """Return scene position of a socket center."""
        sockets = self.input_sockets if is_input else self.output_sockets
        rect = sockets.get(socket_name)
        if rect is None:
            return self.pos()
        return self.mapToScene(QPoint(rect.center().x(), rect.center().y()))
