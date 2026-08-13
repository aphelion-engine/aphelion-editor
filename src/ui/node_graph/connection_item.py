"""Bezier connection wires between node sockets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QPainter, QPainterPath, QPainterPathStroker, QPen
from PyQt6.QtWidgets import (
    QGraphicsPathItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from core.events import Connection
from ui.node_graph.constants import WIRE_CURVE_OFFSET_PX, WIRE_WIDTH_PX
from ui.node_graph.theme_state import current_graph_palette

if TYPE_CHECKING:
    from ui.node_graph.view import NodeGraphView


def build_wire_path(start: QPointF, end: QPointF) -> QPainterPath:
    """Build a horizontal cubic bezier between two socket centers."""
    path = QPainterPath(start)
    dx = max(WIRE_CURVE_OFFSET_PX, abs(end.x() - start.x()) * 0.5)
    c1 = QPointF(start.x() + dx, start.y())
    c2 = QPointF(end.x() - dx, end.y())
    path.cubicTo(c1, c2, end)
    return path


class ConnectionItem(QGraphicsPathItem):
    """Rendered wire tied to a project ``Connection``."""

    def __init__(
        self,
        connection: Connection,
        graph_view: NodeGraphView,
    ) -> None:
        super().__init__()
        self.connection = connection
        self.graph_view = graph_view
        self.setZValue(0.0)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setPen(QPen(current_graph_palette().wire, WIRE_WIDTH_PX))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.update_path()

    def update_path(self) -> None:
        """Recompute geometry from current socket positions."""
        start = self.graph_view.socket_scene_pos(
            self.connection.output_node_id,
            self.connection.output_slot,
            is_input=False,
        )
        end = self.graph_view.socket_scene_pos(
            self.connection.input_node_id,
            self.connection.input_slot,
            is_input=True,
        )
        if start is None or end is None:
            self.setPath(QPainterPath())
            return
        self.setPath(build_wire_path(start, end))

    def shape(self) -> QPainterPath:
        """Widen hit area so thin wires are easy to select."""
        stroker = QPainterPathStroker()
        stroker.setWidth(WIRE_WIDTH_PX + 10.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        return stroker.createStroke(self.path())

    def paint(
        self,
        painter: QPainter | None,
        _option: QStyleOptionGraphicsItem | None,
        _widget: QWidget | None,
    ) -> None:
        if painter is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = current_graph_palette()
        color = palette.wire_active if self.isSelected() else palette.wire
        painter.setPen(
            QPen(
                color,
                WIRE_WIDTH_PX,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPath(self.path())


class PreviewWireItem(QGraphicsPathItem):
    """Temporary wire shown while dragging a new connection."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(100.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._snapped = False
        self._apply_style()

    def set_endpoints(
        self,
        start: QPointF,
        end: QPointF,
        *,
        snapped: bool = False,
    ) -> None:
        """Update the preview path; ``snapped`` switches to a solid stroke."""
        if snapped != self._snapped:
            self._snapped = snapped
            self._apply_style()
        self.setPath(build_wire_path(start, end))

    def _apply_style(self) -> None:
        style = Qt.PenStyle.SolidLine if self._snapped else Qt.PenStyle.DashLine
        self.setPen(
            QPen(
                current_graph_palette().wire_preview,
                WIRE_WIDTH_PX + (0.6 if self._snapped else 0.0),
                style,
                Qt.PenCapStyle.RoundCap,
            )
        )
