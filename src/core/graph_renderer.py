"""Headless deterministic graph image renderer shared by GUI and CLI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen
from core.nodes import global_node_registry
from core.nodes.catalog import BUILTIN_NODE_TYPES

_QT_APP: QGuiApplication | None = None


@dataclass(frozen=True)
class GraphRenderOptions:
    scale: float = 1.0
    padding: int = 48
    background: str = "dark"  # dark, light, transparent, custom
    custom_background: tuple[int, int, int, int] = (24, 26, 32, 255)
    watermark: bool = True
    watermark_style: str = "name"
    max_width: int = 12000
    max_height: int = 12000
    selected_only: bool = False
    selected_ids: tuple[str, ...] = ()
    highlight_ids: tuple[str, ...] = ()


def _node_size(node: dict[str, Any]) -> tuple[float, float]:
    inputs = node.get("inputs") or []
    outputs = node.get("outputs") or []
    raw_ports = max(len(inputs), len(outputs), len(node.get("properties", {})), 1)
    labels = [str(item) for item in inputs + outputs]
    width = max(210, min(420, 150 + max((len(item) for item in labels), default=8) * 5.2))
    return width, 66 + raw_ports * 24


def _layout_if_needed(data: dict[str, Any]) -> None:
    nodes = data.get("nodes", [])
    missing = [item for item in nodes if not isinstance(item.get("position"), list)]
    if not missing:
        return
    incoming = {item["id"]: 0 for item in nodes}
    outgoing: dict[str, list[str]] = {item["id"]: [] for item in nodes}
    for connection in data.get("connections", []):
        source, target = connection.get("from", [None, None]), connection.get("to", [None, None])
        if source[0] in outgoing and target[0] in incoming:
            outgoing[source[0]].append(target[0]); incoming[target[0]] += 1
    layers: dict[str, int] = {}
    queue = sorted(node_id for node_id, count in incoming.items() if count == 0)
    while queue:
        node_id = queue.pop(0)
        for child in sorted(outgoing[node_id]):
            layers[child] = max(layers.get(child, 0), layers.get(node_id, 0) + 1)
            incoming[child] -= 1
            if incoming[child] == 0: queue.append(child)
    buckets: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        buckets.setdefault(layers.get(node["id"], 0), []).append(node)
    for layer, bucket in sorted(buckets.items()):
        for row, node in enumerate(sorted(bucket, key=lambda item: item["id"])):
            if not isinstance(node.get("position"), list):
                node["position"] = [100 + layer * 300, 100 + row * 160]


def _background(options: GraphRenderOptions) -> QColor | None:
    if options.background == "transparent":
        return None
    if options.background == "light":
        return QColor(245, 246, 249, 255)
    if options.background == "custom":
        return QColor(*options.custom_background)
    return QColor(22, 24, 30, 255)


def _ensure_qt_application() -> None:
    """Make font/QPainter rendering safe for headless CLI processes."""
    global _QT_APP
    if QGuiApplication.instance() is None:
        _QT_APP = QGuiApplication([])


def render_graph_image(data: dict[str, Any], options: GraphRenderOptions | None = None) -> QImage:
    """Render graph data without relying on a visible ``QGraphicsView``."""
    _ensure_qt_application()
    options = options or GraphRenderOptions()
    if not global_node_registry.get_all_nodes():
        for node_class in BUILTIN_NODE_TYPES:
            global_node_registry.register(node_class, node_class.node_category,
                                          node_class.node_type, node_class.node_description,
                                          node_class.node_color)
    for node in data.get("nodes", []):
        if "inputs" not in node or "outputs" not in node:
            instance = global_node_registry.create_node(node.get("type", ""), node.get("category"))
            if instance is not None:
                node.setdefault("inputs", list(instance.inputs)); node.setdefault("outputs", list(instance.outputs))
                node.setdefault("color", list(instance.node_color))
    _layout_if_needed(data)
    selected = set(options.selected_ids)
    nodes = [node for node in data.get("nodes", []) if not options.selected_only or node.get("id") in selected]
    included = {node.get("id") for node in nodes}
    if not nodes:
        width, height = 640, 360
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(_background(options) or Qt.GlobalColor.transparent)
        return image
    bounds = []
    sizes = {}
    for node in nodes:
        x, y = node.get("position", [0, 0]); size = _node_size(node); sizes[node["id"]] = size
        bounds.append((float(x), float(y), float(x) + size[0], float(y) + size[1]))
    for group in data.get("groups", []):
        rect = group.get("rect", [])
        if isinstance(rect, list) and len(rect) == 4:
            bounds.append((float(rect[0]), float(rect[1]), float(rect[0]) + float(rect[2]), float(rect[1]) + float(rect[3])))
    for annotation in data.get("annotations", []):
        position = annotation.get("position", [])
        if isinstance(position, list) and len(position) >= 2:
            bounds.append((float(position[0]), float(position[1]), float(position[0]) + 300, float(position[1]) + 24))
    left = min(item[0] for item in bounds) - options.padding
    top = min(item[1] for item in bounds) - options.padding
    right = max(item[2] for item in bounds) + options.padding
    bottom = max(item[3] for item in bounds) + options.padding
    scale = max(.05, float(options.scale))
    raw_width, raw_height = max(1, int((right - left) * scale)), max(1, int((bottom - top) * scale))
    scale = min(scale, options.max_width / raw_width if raw_width > options.max_width else scale,
                options.max_height / raw_height if raw_height > options.max_height else scale)
    width, height = max(1, int((right - left) * scale)), max(1, int((bottom - top) * scale))
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    background = _background(options)
    image.fill(background if background is not None else Qt.GlobalColor.transparent)
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale); painter.translate(-left, -top)
    dark = options.background != "light"
    text = QColor(235, 237, 242) if dark else QColor(35, 38, 45)
    secondary = QColor(165, 171, 184) if dark else QColor(95, 100, 110)
    # Groups are data, not viewport items, so they render consistently in CLI.
    for group in data.get("groups", []):
        rect = group.get("rect", [0, 0, 0, 0]); painter.setPen(QPen(QColor(100, 130, 190, 180), 2)); painter.setBrush(QColor(80, 110, 170, 35))
        painter.drawRoundedRect(QRectF(*rect), 10, 10); painter.setPen(secondary); painter.drawText(QRectF(rect[0] + 10, rect[1] + 8, rect[2], 20), str(group.get("label", "")))
    positions: dict[tuple[str, str, bool], tuple[float, float]] = {}
    for node in nodes:
        x, y = node.get("position", [0, 0]); w, h = sizes[node["id"]]
        count = max(len(node.get("inputs", [])), len(node.get("outputs", [])), len(node.get("properties", {})), 1)
        for index, port in enumerate(node.get("inputs", [])):
            positions[(node["id"], str(port), True)] = (x, y + 66 + index * 24)
        for index, port in enumerate(node.get("outputs", [])):
            positions[(node["id"], str(port), False)] = (x + w, y + 66 + index * 24)
    painter.setPen(QPen(QColor(125, 145, 180, 210), 2))
    for connection in data.get("connections", []):
        source, target = connection.get("from", []), connection.get("to", [])
        if len(source) != 2 or len(target) != 2 or source[0] not in included or target[0] not in included:
            continue
        a = positions.get((source[0], source[1], False)); b = positions.get((target[0], target[1], True))
        if not a or not b: continue
        path = QPainterPath(); path.moveTo(*a); distance = max(40.0, (b[0] - a[0]) * .45)
        path.cubicTo(a[0] + distance, a[1], b[0] - distance, b[1], *b); painter.drawPath(path)
    painter.setFont(QFont("Segoe UI", 10))
    for node in nodes:
        x, y = node.get("position", [0, 0]); w, h = sizes[node["id"]]
        color = QColor(*node.get("color", (86, 110, 160)))
        highlighted = not options.highlight_ids or node.get("id") in options.highlight_ids
        painter.setPen(QPen(QColor(255, 210, 90) if highlighted and options.highlight_ids else color.darker(140), 2 if highlighted and options.highlight_ids else 1))
        painter.setBrush(QColor(42, 46, 56, 245 if highlighted else 105) if dark else QColor(255, 255, 255, 245 if highlighted else 125)); painter.drawRoundedRect(QRectF(x, y, w, h), 8, 8)
        painter.setBrush(color if highlighted else color.darker(180)); painter.drawRoundedRect(QRectF(x, y, w, 28), 8, 8); painter.drawRect(QRectF(x, y + 18, w, 10))
        painter.setPen(Qt.GlobalColor.white); painter.drawText(QRectF(x + 10, y + 4, w - 20, 20), str(node.get("name", node.get("type", "Node"))))
        painter.setPen(secondary); painter.setFont(QFont("Segoe UI", 8)); painter.drawText(QRectF(x + 10, y + 34, w - 20, 16), str(node.get("type", "")))
        painter.setPen(text); painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor(15, 17, 22), 1)); painter.setBrush(QColor(90, 170, 220))
        for index, _ in enumerate(node.get("inputs", [])):
            painter.drawEllipse(QRectF(x - 5, y + 66 + index * 24 - 5, 10, 10))
        painter.setBrush(QColor(220, 150, 90))
        for index, _ in enumerate(node.get("outputs", [])):
            painter.drawEllipse(QRectF(x + w - 5, y + 66 + index * 24 - 5, 10, 10))
        for index, port in enumerate(node.get("inputs", [])):
            painter.drawText(QRectF(x + 14, y + 61 + index * 24, w / 2 - 20, 18), str(port))
        for index, port in enumerate(node.get("outputs", [])):
            painter.drawText(QRectF(x + w / 2, y + 61 + index * 24, w / 2 - 14, 18), Qt.AlignmentFlag.AlignRight, str(port))
    for annotation in data.get("annotations", []):
        if annotation.get("type") in ("label", "callout"):
            pos = annotation.get("position", [left + 10, top + 10]); painter.setPen(QColor(245, 205, 100)); painter.setFont(QFont("Segoe UI", 10)); painter.drawText(QPointF(float(pos[0]), float(pos[1])), str(annotation.get("text", "")))
    painter.resetTransform()
    if options.watermark:
        painter.setPen(QColor(170, 176, 188, 175)); painter.setFont(QFont("Segoe UI", max(9, int(11 * scale))))
        watermark = "Aphelion" if options.watermark_style == "minimal" else "Aphelion • aphelion-editor"
        painter.drawText(QRectF(0, height / scale - 28, width / scale - 16, 20), Qt.AlignmentFlag.AlignRight, watermark)
    painter.end()
    image.setText("Software", "Aphelion Editor")
    image.setText("GraphFormat", "aphelion-graph/1")
    return image


def save_graph_image(data: dict[str, Any], path: str | Path, options: GraphRenderOptions | None = None) -> None:
    image = render_graph_image(data, options)
    if not image.save(str(path), "PNG"):
        raise OSError(f"Could not write graph image: {path}")
