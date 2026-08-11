"""Monochrome, minimal icon factory for consistent UI chrome."""

from __future__ import annotations

from enum import Enum, auto

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

DEFAULT_ICON_SIZE_PX: int = 16
DEFAULT_ICON_COLOR = QColor(208, 208, 208)
ACTIVE_ICON_COLOR = QColor(126, 200, 255)
LOOP_ACTIVE_COLOR = QColor(143, 209, 154)


class AppIcon(Enum):
    """Named application icons."""

    TO_START = auto()
    STEP_BACK = auto()
    PLAY = auto()
    PAUSE = auto()
    STEP_FORWARD = auto()
    TO_END = auto()
    MARK_IN = auto()
    MARK_OUT = auto()
    GO_IN = auto()
    GO_OUT = auto()
    CLEAR_RANGE = auto()
    LOOP = auto()
    NEW_FILE = auto()
    OPEN_FILE = auto()
    SAVE_FILE = auto()
    UNDO = auto()
    REDO = auto()
    DELETE = auto()
    FIT_VIEW = auto()
    DUPLICATE = auto()
    ALIGN_LEFT = auto()
    ALIGN_RIGHT = auto()
    ALIGN_TOP = auto()
    ALIGN_BOTTOM = auto()
    ALIGN_CENTER_H = auto()
    ALIGN_CENTER_V = auto()
    DISTRIBUTE_H = auto()
    DISTRIBUTE_V = auto()
    SELECT_ALL = auto()
    ADD_NODE = auto()


def make_dot_icon(
    color: QColor | tuple[int, int, int],
    *,
    size: int = 12,
) -> QIcon:
    """Create a small filled circular color swatch icon."""
    if isinstance(color, tuple):
        paint_color = QColor(color[0], color[1], color[2])
    else:
        paint_color = color
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(0, 0, 0, 160), 1.0))
    painter.setBrush(paint_color)
    inset = 1.5
    painter.drawEllipse(QRectF(inset, inset, size - inset * 2, size - inset * 2))
    painter.end()
    return QIcon(pixmap)


def make_icon(
    name: AppIcon,
    *,
    color: QColor | None = None,
    size: int = DEFAULT_ICON_SIZE_PX,
) -> QIcon:
    """Create a monochrome icon.

    Parameters:
        name: Which glyph to draw.
        color: Fill/stroke color. Defaults to light gray.
        size: Pixel size of the icon pixmap.

    Returns:
        A QIcon suitable for buttons and menu actions.
    """
    paint_color = color if color is not None else DEFAULT_ICON_COLOR
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(paint_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(paint_color)

    inset = QRectF(2.0, 2.0, size - 4.0, size - 4.0)
    _draw_icon(painter, name, inset, paint_color)
    painter.end()
    return QIcon(pixmap)


def _draw_icon(
    painter: QPainter,
    name: AppIcon,
    rect: QRectF,
    color: QColor,
) -> None:
    match name:
        case AppIcon.TO_START:
            _draw_to_start(painter, rect, color)
        case AppIcon.STEP_BACK:
            _draw_step_back(painter, rect, color)
        case AppIcon.PLAY:
            _draw_play(painter, rect, color)
        case AppIcon.PAUSE:
            _draw_pause(painter, rect, color)
        case AppIcon.STEP_FORWARD:
            _draw_step_forward(painter, rect, color)
        case AppIcon.TO_END:
            _draw_to_end(painter, rect, color)
        case AppIcon.MARK_IN:
            _draw_mark_in(painter, rect, color)
        case AppIcon.MARK_OUT:
            _draw_mark_out(painter, rect, color)
        case AppIcon.GO_IN:
            _draw_go_in(painter, rect, color)
        case AppIcon.GO_OUT:
            _draw_go_out(painter, rect, color)
        case AppIcon.CLEAR_RANGE:
            _draw_clear(painter, rect, color)
        case AppIcon.LOOP:
            _draw_loop(painter, rect, color)
        case AppIcon.NEW_FILE:
            _draw_new_file(painter, rect, color)
        case AppIcon.OPEN_FILE:
            _draw_open_file(painter, rect, color)
        case AppIcon.SAVE_FILE:
            _draw_save_file(painter, rect, color)
        case AppIcon.UNDO:
            _draw_undo(painter, rect, color)
        case AppIcon.REDO:
            _draw_redo(painter, rect, color)
        case AppIcon.DELETE:
            _draw_delete(painter, rect, color)
        case AppIcon.FIT_VIEW:
            _draw_fit_view(painter, rect, color)
        case AppIcon.DUPLICATE:
            _draw_duplicate(painter, rect, color)
        case AppIcon.ALIGN_LEFT:
            _draw_align_left(painter, rect, color)
        case AppIcon.ALIGN_RIGHT:
            _draw_align_right(painter, rect, color)
        case AppIcon.ALIGN_TOP:
            _draw_align_top(painter, rect, color)
        case AppIcon.ALIGN_BOTTOM:
            _draw_align_bottom(painter, rect, color)
        case AppIcon.ALIGN_CENTER_H:
            _draw_align_center_h(painter, rect, color)
        case AppIcon.ALIGN_CENTER_V:
            _draw_align_center_v(painter, rect, color)
        case AppIcon.DISTRIBUTE_H:
            _draw_distribute_h(painter, rect, color)
        case AppIcon.DISTRIBUTE_V:
            _draw_distribute_v(painter, rect, color)
        case AppIcon.SELECT_ALL:
            _draw_select_all(painter, rect, color)
        case AppIcon.ADD_NODE:
            _draw_add_node(painter, rect, color)


def _draw_play(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    points = QPolygonF(
        [
            QPointF(rect.left() + 2, rect.top()),
            QPointF(rect.right(), rect.center().y()),
            QPointF(rect.left() + 2, rect.bottom()),
        ]
    )
    painter.drawPolygon(points)


def _draw_pause(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    bar_w = rect.width() * 0.28
    gap = rect.width() * 0.18
    left = QRectF(rect.left() + 1, rect.top(), bar_w, rect.height())
    right = QRectF(rect.left() + 1 + bar_w + gap, rect.top(), bar_w, rect.height())
    painter.drawRoundedRect(left, 1.0, 1.0)
    painter.drawRoundedRect(right, 1.0, 1.0)


def _draw_step_back(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    mid = rect.center()
    points = QPolygonF(
        [
            QPointF(rect.right() - 1, rect.top()),
            QPointF(rect.left() + 3, mid.y()),
            QPointF(rect.right() - 1, rect.bottom()),
        ]
    )
    painter.drawPolygon(points)
    painter.drawRect(QRectF(rect.left(), rect.top(), 2.0, rect.height()))


def _draw_step_forward(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    mid = rect.center()
    points = QPolygonF(
        [
            QPointF(rect.left() + 1, rect.top()),
            QPointF(rect.right() - 3, mid.y()),
            QPointF(rect.left() + 1, rect.bottom()),
        ]
    )
    painter.drawPolygon(points)
    painter.drawRect(QRectF(rect.right() - 2, rect.top(), 2.0, rect.height()))


def _draw_to_start(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.left(), rect.top(), 2.0, rect.height()))
    tip = QPolygonF(
        [
            QPointF(rect.right() - 1, rect.top()),
            QPointF(rect.left() + 4, rect.center().y()),
            QPointF(rect.right() - 1, rect.bottom()),
        ]
    )
    painter.drawPolygon(tip)


def _draw_to_end(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    tip = QPolygonF(
        [
            QPointF(rect.left() + 1, rect.top()),
            QPointF(rect.right() - 4, rect.center().y()),
            QPointF(rect.left() + 1, rect.bottom()),
        ]
    )
    painter.drawPolygon(tip)
    painter.drawRect(QRectF(rect.right() - 2, rect.top(), 2.0, rect.height()))


def _draw_mark_in(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(rect.topLeft(), rect.bottomLeft())
    painter.drawLine(rect.topLeft(), QPointF(rect.left() + 5, rect.top()))
    painter.drawLine(rect.bottomLeft(), QPointF(rect.left() + 5, rect.bottom()))
    x = rect.center().x() - 1
    painter.drawLine(
        QPointF(x, rect.top() + 3),
        QPointF(x, rect.bottom() - 3),
    )


def _draw_mark_out(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(rect.topRight(), rect.bottomRight())
    painter.drawLine(rect.topRight(), QPointF(rect.right() - 5, rect.top()))
    painter.drawLine(rect.bottomRight(), QPointF(rect.right() - 5, rect.bottom()))
    x = rect.center().x() + 1
    painter.drawLine(
        QPointF(x, rect.top() + 3),
        QPointF(x, rect.bottom() - 3),
    )


def _draw_go_in(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(
        QPointF(rect.left() + 1, rect.top()),
        QPointF(rect.left() + 1, rect.bottom()),
    )
    tip = QPolygonF(
        [
            QPointF(rect.right() - 1, rect.top() + 2),
            QPointF(rect.left() + 4, rect.center().y()),
            QPointF(rect.right() - 1, rect.bottom() - 2),
        ]
    )
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(tip)


def _draw_go_out(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(
        QPointF(rect.right() - 1, rect.top()),
        QPointF(rect.right() - 1, rect.bottom()),
    )
    tip = QPolygonF(
        [
            QPointF(rect.left() + 1, rect.top() + 2),
            QPointF(rect.right() - 4, rect.center().y()),
            QPointF(rect.left() + 1, rect.bottom() - 2),
        ]
    )
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(tip)


def _draw_clear(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = rect.adjusted(2, 2, -2, -2)
    painter.drawLine(inset.topLeft(), inset.bottomRight())
    painter.drawLine(inset.topRight(), inset.bottomLeft())


def _draw_loop(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    arc = rect.adjusted(1, 1, -1, -1)
    painter.drawArc(arc, 40 * 16, 280 * 16)
    tip = QPolygonF(
        [
            QPointF(arc.right() - 1, arc.center().y() - 1),
            QPointF(arc.right() - 5, arc.center().y() - 5),
            QPointF(arc.right() + 1, arc.center().y() - 5),
        ]
    )
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(tip)


def _draw_new_file(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    body = rect.adjusted(2, 1, -2, -1)
    painter.drawRect(body)
    painter.drawLine(
        QPointF(body.right() - 4, body.top()),
        QPointF(body.right(), body.top() + 4),
    )


def _draw_open_file(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(1, 4, -1, -1))
    painter.drawLine(
        QPointF(rect.left() + 1, rect.top() + 4),
        QPointF(rect.left() + 4, rect.top() + 1),
    )
    painter.drawLine(
        QPointF(rect.left() + 4, rect.top() + 1),
        QPointF(rect.center().x(), rect.top() + 1),
    )


def _draw_save_file(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 1.5, 1.5)
    painter.drawRect(rect.adjusted(4, 1, -4, -8))
    painter.drawRect(rect.adjusted(3, 8, -3, -2))


def _draw_undo(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(rect.adjusted(1, 2, -1, -2), 40 * 16, 200 * 16)
    tip = QPolygonF(
        [
            QPointF(rect.left() + 1, rect.center().y() - 1),
            QPointF(rect.left() + 5, rect.center().y() - 5),
            QPointF(rect.left() + 5, rect.center().y() + 2),
        ]
    )
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(tip)


def _draw_redo(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(rect.adjusted(1, 2, -1, -2), 140 * 16, -200 * 16)
    tip = QPolygonF(
        [
            QPointF(rect.right() - 1, rect.center().y() - 1),
            QPointF(rect.right() - 5, rect.center().y() - 5),
            QPointF(rect.right() - 5, rect.center().y() + 2),
        ]
    )
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(tip)


def _draw_delete(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(
        QPointF(rect.left() + 2, rect.top() + 3),
        QPointF(rect.right() - 2, rect.top() + 3),
    )
    painter.drawLine(
        QPointF(rect.left() + 4, rect.top() + 1),
        QPointF(rect.right() - 4, rect.top() + 1),
    )
    body = QRectF(rect.left() + 3, rect.top() + 3, rect.width() - 6, rect.height() - 4)
    painter.drawRect(body)
    painter.drawLine(
        QPointF(body.center().x(), body.top() + 2),
        QPointF(body.center().x(), body.bottom() - 2),
    )


def _draw_fit_view(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(3, 3, -3, -3))
    painter.drawLine(rect.topLeft(), QPointF(rect.left() + 4, rect.top()))
    painter.drawLine(rect.topLeft(), QPointF(rect.left(), rect.top() + 4))
    painter.drawLine(rect.topRight(), QPointF(rect.right() - 4, rect.top()))
    painter.drawLine(rect.topRight(), QPointF(rect.right(), rect.top() + 4))
    painter.drawLine(rect.bottomLeft(), QPointF(rect.left() + 4, rect.bottom()))
    painter.drawLine(rect.bottomLeft(), QPointF(rect.left(), rect.bottom() - 4))
    painter.drawLine(rect.bottomRight(), QPointF(rect.right() - 4, rect.bottom()))
    painter.drawLine(rect.bottomRight(), QPointF(rect.right(), rect.bottom() - 4))


def _draw_duplicate(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(0, 0, -4, -4))
    painter.drawRect(rect.adjusted(4, 4, 0, 0))


def _draw_align_left(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.left(), rect.top() + 1, 2, rect.height() - 2))
    painter.drawRect(QRectF(rect.left() + 4, rect.top() + 2, 5, 3))
    painter.drawRect(QRectF(rect.left() + 4, rect.bottom() - 5, 7, 3))


def _draw_align_right(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.right() - 2, rect.top() + 1, 2, rect.height() - 2))
    painter.drawRect(QRectF(rect.right() - 9, rect.top() + 2, 5, 3))
    painter.drawRect(QRectF(rect.right() - 11, rect.bottom() - 5, 7, 3))


def _draw_align_top(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.left() + 1, rect.top(), rect.width() - 2, 2))
    painter.drawRect(QRectF(rect.left() + 2, rect.top() + 4, 3, 5))
    painter.drawRect(QRectF(rect.right() - 5, rect.top() + 4, 3, 7))


def _draw_align_bottom(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.left() + 1, rect.bottom() - 2, rect.width() - 2, 2))
    painter.drawRect(QRectF(rect.left() + 2, rect.bottom() - 9, 3, 5))
    painter.drawRect(QRectF(rect.right() - 5, rect.bottom() - 11, 3, 7))


def _draw_align_center_h(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    cx = rect.center().x()
    painter.drawRect(QRectF(cx - 1, rect.top(), 2, rect.height()))
    painter.drawRect(QRectF(cx - 4, rect.top() + 2, 8, 3))
    painter.drawRect(QRectF(cx - 3, rect.bottom() - 5, 6, 3))


def _draw_align_center_v(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    cy = rect.center().y()
    painter.drawRect(QRectF(rect.left(), cy - 1, rect.width(), 2))
    painter.drawRect(QRectF(rect.left() + 2, cy - 4, 3, 8))
    painter.drawRect(QRectF(rect.right() - 5, cy - 3, 3, 6))


def _draw_distribute_h(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.left(), rect.top() + 3, 2, rect.height() - 6))
    painter.drawRect(QRectF(rect.center().x() - 1, rect.top() + 3, 2, rect.height() - 6))
    painter.drawRect(QRectF(rect.right() - 2, rect.top() + 3, 2, rect.height() - 6))


def _draw_distribute_v(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.drawRect(QRectF(rect.left() + 3, rect.top(), rect.width() - 6, 2))
    painter.drawRect(QRectF(rect.left() + 3, rect.center().y() - 1, rect.width() - 6, 2))
    painter.drawRect(QRectF(rect.left() + 3, rect.bottom() - 2, rect.width() - 6, 2))


def _draw_select_all(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(0, 0, -5, -5))
    painter.drawRect(rect.adjusted(5, 5, 0, 0))


def _draw_add_node(painter: QPainter, rect: QRectF, _color: QColor) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(1, 2, -1, -2), 2, 2)
    cx = rect.center().x()
    cy = rect.center().y()
    painter.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy + 3))
    painter.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))


def icon_size() -> QSize:
    """Default icon size used by toolbar buttons."""
    return QSize(DEFAULT_ICON_SIZE_PX, DEFAULT_ICON_SIZE_PX)
