"""Visual node item for the graph editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
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
    CORNER_RADIUS_PX,
    HEADER_HEIGHT_PX,
    SHADOW_OFFSET_X_PX,
    SHADOW_OFFSET_Y_PX,
    SOCKET_EDGE_GAP_PX,
    SOCKET_HIT_PAD_PX,
    SOCKET_SIZE_PX,
    SOCKET_SPACING_PX,
)
from ui.node_graph.node_layout import measure_node
from ui.node_graph.theme_state import GraphThemePalette, current_graph_palette

if TYPE_CHECKING:
    from ui.node_graph.view import NodeGraphView


def _distance_squared(point: QPointF, other: QPoint) -> float:
    """Return the squared Euclidean distance between a float and int point."""
    dx = point.x() - other.x()
    dy = point.y() - other.y()
    return dx * dx + dy * dy


class NodeItem(QGraphicsRectItem):
    """Painted node with header accent, depth, and large sockets."""

    def __init__(self, node: Node, node_id: str) -> None:
        dimensions = measure_node(node)
        node.width = float(dimensions.width)
        node.height = float(dimensions.height)
        super().__init__(0, 0, dimensions.width, dimensions.height)

        self.node = node
        self.node_id = node_id
        self.graph_view: NodeGraphView | None = None
        self.is_hovered: bool = False
        self._drag_origins: dict[int, QPointF] = {}
        self._drag_before_positions: dict[str, tuple[float, float]] = {}
        self._node_width: int = dimensions.width

        r, g, b = node.node_color
        self.accent_color = QColor(r, g, b)

        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(1.0)

        self.input_sockets: dict[str, QRect] = {}
        self.output_sockets: dict[str, QRect] = {}
        self._calculate_socket_positions()
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    @property
    def node_width(self) -> int:
        """Current painted node width in pixels."""
        return self._node_width

    def relayout_from_content(self) -> None:
        """Resize the item when node labels or sockets change."""
        dimensions = measure_node(self.node)
        if dimensions.width == self._node_width and dimensions.height == int(self.rect().height()):
            return
        self.prepareGeometryChange()
        self._node_width = dimensions.width
        self.node.width = float(dimensions.width)
        self.node.height = float(dimensions.height)
        self.setRect(0, 0, dimensions.width, dimensions.height)
        self._calculate_socket_positions()
        self.update()

    def _calculate_socket_positions(self) -> None:
        """Lay out socket hit targets from the current node width."""
        width = self._node_width
        self.input_sockets.clear()
        self.output_sockets.clear()
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
                width - SOCKET_SIZE_PX // 2 + SOCKET_EDGE_GAP_PX,
                y - SOCKET_SIZE_PX // 2,
                SOCKET_SIZE_PX,
                SOCKET_SIZE_PX,
            )
            y += SOCKET_SPACING_PX

    def boundingRect(self) -> QRectF:
        # Must fully cover the enlarged socket hit-circles (see ``socket_at``)
        # or Qt will never deliver press/hover events near their outer edge.
        pad = SOCKET_SIZE_PX + SOCKET_HIT_PAD_PX + 4
        return self.rect().adjusted(-pad, -6, pad + SHADOW_OFFSET_X_PX, pad + SHADOW_OFFSET_Y_PX)

    def paint(
        self,
        painter: QPainter | None,
        _option: QStyleOptionGraphicsItem | None,
        _widget: QWidget | None,
    ) -> None:
        if painter is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        palette = current_graph_palette()
        body = self.rect()
        selected = self.isSelected()
        self._paint_shadow(painter, body)
        self._paint_body(painter, body, selected, palette)
        self._paint_header(painter, body, palette)
        self._paint_labels(painter, body, palette)
        self._paint_sockets(painter, palette)

    def _paint_shadow(self, painter: QPainter, body: QRectF) -> None:
        shadow = body.translated(SHADOW_OFFSET_X_PX, SHADOW_OFFSET_Y_PX)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 72))
        painter.drawRoundedRect(shadow, CORNER_RADIUS_PX + 1, CORNER_RADIUS_PX + 1)

    def _paint_body(
        self,
        painter: QPainter,
        body: QRectF,
        selected: bool,
        palette: GraphThemePalette,
    ) -> None:
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.selection_soft)
            painter.drawRoundedRect(
                body.adjusted(-3, -3, 3, 3),
                CORNER_RADIUS_PX + 2,
                CORNER_RADIUS_PX + 2,
            )
            border = palette.selection
            width = 2.0
        else:
            border = palette.node_border_hover if self.is_hovered else palette.node_border
            width = 1.4 if self.is_hovered else 1.0

        body_top = QColor(palette.node_body)
        body_bottom = QColor(palette.node_body)
        body_top.setRed(min(255, body_top.red() + 6))
        body_top.setGreen(min(255, body_top.green() + 6))
        body_top.setBlue(min(255, body_top.blue() + 6))
        body_bottom.setRed(max(0, body_bottom.red() - 8))
        body_bottom.setGreen(max(0, body_bottom.green() - 8))
        body_bottom.setBlue(max(0, body_bottom.blue() - 8))
        if self.is_hovered:
            hover = palette.node_body_hover
            body_top = QColor(hover)
            body_bottom = QColor(hover)
            body_bottom.setRed(max(0, body_bottom.red() - 6))
            body_bottom.setGreen(max(0, body_bottom.green() - 6))
            body_bottom.setBlue(max(0, body_bottom.blue() - 6))

        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        gradient.setColorAt(0.0, body_top)
        gradient.setColorAt(1.0, body_bottom)
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(border, width))
        painter.drawRoundedRect(body, CORNER_RADIUS_PX, CORNER_RADIUS_PX)

        highlight = QLinearGradient(body.topLeft(), QPointF(body.right(), body.top()))
        highlight.setColorAt(0.0, QColor(255, 255, 255, 22))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(highlight))
        painter.drawRoundedRect(
            QRectF(body.x() + 1, body.y() + 1, body.width() - 2, body.height() * 0.45),
            CORNER_RADIUS_PX - 1,
            CORNER_RADIUS_PX - 1,
        )

    def _paint_header(self, painter: QPainter, body: QRectF, palette: GraphThemePalette) -> None:
        header = QRectF(body.x(), body.y(), body.width(), HEADER_HEIGHT_PX)
        accent = QColor(self.accent_color)
        accent_dark = QColor(accent)
        accent_dark.setRed(max(0, accent_dark.red() - 36))
        accent_dark.setGreen(max(0, accent_dark.green() - 36))
        accent_dark.setBlue(max(0, accent_dark.blue() - 36))
        header_gradient = QLinearGradient(header.topLeft(), header.bottomLeft())
        header_gradient.setColorAt(0.0, accent.lighter(112))
        header_gradient.setColorAt(0.55, accent)
        header_gradient.setColorAt(1.0, accent_dark)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(header_gradient))
        painter.drawRoundedRect(
            QRectF(header.x(), header.y(), header.width(), HEADER_HEIGHT_PX + 6),
            CORNER_RADIUS_PX,
            CORNER_RADIUS_PX,
        )
        painter.setBrush(
            palette.node_body if not self.is_hovered else palette.node_body_hover
        )
        painter.drawRect(
            QRectF(
                body.x(),
                body.y() + HEADER_HEIGHT_PX,
                body.width(),
                body.height() - HEADER_HEIGHT_PX,
            )
        )
        painter.setBrush(QColor(255, 255, 255, 36))
        painter.drawRect(QRectF(header.x() + 1, header.y() + 1, header.width() - 2, 1.5))
        painter.setPen(QPen(QColor(0, 0, 0, 48), 1.0))
        painter.drawLine(
            QPointF(header.x() + 8, header.bottom()),
            QPointF(header.right() - 8, header.bottom()),
        )

    def _paint_labels(self, painter: QPainter, body: QRectF, palette: GraphThemePalette) -> None:
        title_font = QFont("Segoe UI", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(palette.text_primary)
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
        self._paint_socket_labels(painter, palette)

    def _paint_socket_labels(self, painter: QPainter, palette: GraphThemePalette) -> None:
        width = self._node_width
        half = width // 2
        painter.setPen(palette.text_secondary)
        for name, rect in self.input_sockets.items():
            text_rect = QRect(
                SOCKET_SIZE_PX,
                rect.center().y() - 7,
                half - 8,
                14,
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                name,
            )
        for name, rect in self.output_sockets.items():
            text_rect = QRect(
                half,
                rect.center().y() - 7,
                half - SOCKET_SIZE_PX,
                14,
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                name,
            )

    def _paint_sockets(self, painter: QPainter, palette: GraphThemePalette) -> None:
        for rect in self.input_sockets.values():
            self._paint_socket(painter, rect, palette.socket_input, palette)
        for rect in self.output_sockets.values():
            self._paint_socket(painter, rect, palette.socket_output, palette)

    def _paint_socket(
        self,
        painter: QPainter,
        rect: QRect,
        fill: QColor,
        palette: GraphThemePalette,
    ) -> None:
        painter.setPen(QPen(palette.socket_ring, 1.8))
        socket_gradient = QLinearGradient(
            QPointF(float(rect.left()), float(rect.top())),
            QPointF(float(rect.right()), float(rect.bottom())),
        )
        socket_gradient.setColorAt(0.0, fill.lighter(118))
        socket_gradient.setColorAt(1.0, fill.darker(118))
        painter.setBrush(QBrush(socket_gradient))
        painter.drawEllipse(rect)
        inner = rect.adjusted(4, 4, -4, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 80)))
        painter.drawEllipse(inner)

    def socket_at(self, local_pos: QPointF) -> tuple[str, bool] | None:
        """Return ``(socket_name, is_input)`` if ``local_pos`` hits a socket.

        Uses a circular hit-test radiating from each socket's true center
        (matching its drawn ellipse) rather than an axis-aligned square, so
        corners of the padded hit zone don't feel harder to hit than the
        center — and picks the *closest* socket when hit zones overlap on
        tightly stacked sockets.
        """
        hit_radius = SOCKET_SIZE_PX / 2.0 + SOCKET_HIT_PAD_PX
        hit_radius_sq = hit_radius * hit_radius
        best: tuple[str, bool] | None = None
        best_distance_sq = hit_radius_sq
        for name, rect in self.input_sockets.items():
            distance_sq = _distance_squared(local_pos, rect.center())
            if distance_sq <= best_distance_sq:
                best = (name, True)
                best_distance_sq = distance_sq
        for name, rect in self.output_sockets.items():
            distance_sq = _distance_squared(local_pos, rect.center())
            if distance_sq <= best_distance_sq:
                best = (name, False)
                best_distance_sq = distance_sq
        return best

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
        if self.graph_view is not None:
            self.graph_view.refresh_connections_for_node(self.node_id)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        super().mouseReleaseEvent(event)
        moved_items = self._selected_node_items()
        after: dict[str, tuple[float, float]] = {}
        for item in moved_items:
            item._sync_node_position()
            after[item.node_id] = (float(item.node.x), float(item.node.y))
            if self.graph_view is not None:
                self.graph_view.refresh_connections_for_node(item.node_id)
        before = self._drag_before_positions
        if self.graph_view is not None and before and after and before != after:
            self.graph_view.commit_node_move(before, after)
        self._drag_origins.clear()
        self._drag_before_positions.clear()

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def _capture_drag_origins(self) -> None:
        selected = self._selected_node_items()
        self._drag_origins = {id(item): item.pos() for item in selected}
        if id(self) not in self._drag_origins:
            self._drag_origins[id(self)] = self.pos()
        self._drag_before_positions = {
            item.node_id: (float(item.node.x), float(item.node.y)) for item in selected
        }
        if self.node_id not in self._drag_before_positions:
            self._drag_before_positions[self.node_id] = (
                float(self.node.x),
                float(self.node.y),
            )

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
        center = rect.center()
        return self.mapToScene(QPointF(float(center.x()), float(center.y())))
