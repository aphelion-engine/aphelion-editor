"""Measure node graph item dimensions from node content."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QFont, QFontMetrics

from core.nodes import Node
from ui.node_graph.constants import (
    BODY_PADDING_PX,
    HEADER_HEIGHT_PX,
    NODE_MAX_WIDTH_PX,
    NODE_MIN_HEIGHT_PX,
    NODE_MIN_WIDTH_PX,
    SOCKET_SPACING_PX,
)


@dataclass(frozen=True, slots=True)
class NodeDimensions:
    """Computed width and height for a node canvas item."""

    width: int
    height: int


def measure_node(node: Node) -> NodeDimensions:
    """Return width/height that fit titles, category, and socket labels."""
    title_font = QFont("Segoe UI", 10)
    title_font.setWeight(QFont.Weight.DemiBold)
    title_metrics = QFontMetrics(title_font)

    meta_font = QFont("Segoe UI", 8)
    meta_metrics = QFontMetrics(meta_font)

    socket_font = QFont("Segoe UI", 8)
    socket_metrics = QFontMetrics(socket_font)

    title_width: int = title_metrics.horizontalAdvance(node.name) + 24
    meta_width: int = meta_metrics.horizontalAdvance(node.node_category) + 24
    socket_names: list[str] = list(node.inputs.keys()) + list(node.outputs.keys())
    longest_socket: int = max(
        (socket_metrics.horizontalAdvance(name) for name in socket_names),
        default=0,
    )
    socket_row_width: int = longest_socket * 2 + 56

    width: int = max(
        NODE_MIN_WIDTH_PX,
        title_width,
        meta_width,
        socket_row_width,
        int(node.width) if node.width > 0 else NODE_MIN_WIDTH_PX,
    )
    width = min(width, NODE_MAX_WIDTH_PX)

    socket_count: int = max(len(node.inputs), len(node.outputs), 1)
    body_height: int = BODY_PADDING_PX * 2 + socket_count * SOCKET_SPACING_PX
    height: int = max(NODE_MIN_HEIGHT_PX, HEADER_HEIGHT_PX + body_height)
    return NodeDimensions(width=width, height=height)
