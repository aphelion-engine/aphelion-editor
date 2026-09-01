"""Interactive viewport overlay for editing ``RotoNode`` shape documents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from core.history import EditRotoDocumentCommand
from core.nodes.roto_nodes import RotoNode
from core.nodes.roto.interpolation import interpolate_points
from core.nodes.roto.model import RotoDocument, RotoPoint, RotoShape

if TYPE_CHECKING:
    from core.history import HistoryStack
    from core.project import Project

# Visual sizing, in overlay-widget pixels.
_POINT_RADIUS: float = 4.0
_HIT_RADIUS_SQUARED: float = 8.0 * 8.0

_ACTIVE_COLOR: QColor = QColor(255, 200, 60)
_SHAPE_COLOR: QColor = QColor(0, 200, 255)


def _clone_document(document: RotoDocument) -> RotoDocument:
    """Deep-copy a document via its own JSON-native round-trip."""
    return RotoDocument.from_dict(document.to_dict())


class _RotoToolbar(QWidget):
    """Small floating control strip: add/close, smooth, auto-key, delete."""

    def __init__(
        self,
        *,
        on_add_shape: Callable[[], None],
        on_toggle_smooth: Callable[[], None],
        on_toggle_auto_key: Callable[[], None],
        on_delete_shape: Callable[[], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RotoOverlayToolbar")
        self.setStyleSheet(
            "QWidget#RotoOverlayToolbar { background-color: rgba(20, 20, 20, 200);"
            " border-radius: 4px; }"
            "QPushButton { color: #e0e0e0; background-color: rgba(255, 255, 255, 20);"
            " border: 1px solid #555555; border-radius: 3px; padding: 3px 8px;"
            " font-size: 11px; }"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 40); }"
            "QPushButton:checked { background-color: #2b6ea8; border-color: #347ebc; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.add_shape_button = QPushButton("Add Shape")
        self.add_shape_button.clicked.connect(on_add_shape)
        layout.addWidget(self.add_shape_button)

        self.smooth_button = QPushButton("Smooth")
        self.smooth_button.setCheckable(True)
        self.smooth_button.clicked.connect(on_toggle_smooth)
        layout.addWidget(self.smooth_button)

        self.auto_key_button = QPushButton("Auto-Key")
        self.auto_key_button.setCheckable(True)
        self.auto_key_button.clicked.connect(on_toggle_auto_key)
        layout.addWidget(self.auto_key_button)

        self.delete_shape_button = QPushButton("Delete Shape")
        self.delete_shape_button.clicked.connect(on_delete_shape)
        layout.addWidget(self.delete_shape_button)

        self.adjustSize()


class RotoOverlayWidget(QWidget):
    """Transparent overlay drawing/editing a ``RotoNode``'s shapes in place.

    Coordinate mapping: normalized (0-1) shape points are mapped to overlay
    pixels via ``image_rect_provider``, which returns the rectangle the
    displayed frame currently occupies inside the viewport label (see
    ``ViewportWidget.displayed_image_rect``).
    """

    def __init__(
        self,
        project: "Project",
        history: "HistoryStack | None",
        image_rect_provider: Callable[[], QRect],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RotoOverlay")
        self.project = project
        self.history = history
        self._image_rect_provider = image_rect_provider
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._node_id: str | None = None
        self._selected_shape_id: str | None = None
        self._auto_key: bool = False
        self._smooth_default: bool = False

        self._drawing_shape: RotoShape | None = None
        self._drawing_points: list[RotoPoint] = []

        self._drag_shape_id: str | None = None
        self._drag_point_index: int | None = None
        self._drag_frame: int = 0
        self._drag_old_document: RotoDocument | None = None

        self._toolbar = _RotoToolbar(
            on_add_shape=self._on_add_shape_clicked,
            on_toggle_smooth=self._on_toggle_smooth_clicked,
            on_toggle_auto_key=self._on_toggle_auto_key_clicked,
            on_delete_shape=self._on_delete_shape_clicked,
            parent=self,
        )
        self._toolbar.move(8, 8)

        self.hide()

    def set_edit_target(self, node_id: str | None) -> None:
        """Arm (``node_id`` set) or disarm (``None``) interactive editing."""
        self._node_id = node_id
        self._selected_shape_id = None
        self._cancel_drawing_shape()
        self.setVisible(node_id is not None)
        if node_id is not None:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def sync_geometry(self, label_rect: QRect) -> None:
        """Resize to cover the viewport label so mapping stays pixel-accurate."""
        self.setGeometry(label_rect)

    def _node(self) -> RotoNode | None:
        if self._node_id is None:
            return None
        node = self.project.nodes.get(self._node_id)
        return node if isinstance(node, RotoNode) else None

    def _edit_frame(self) -> int:
        return self.project.current_frame if self._auto_key else 0

    def _to_widget_pos(self, point: RotoPoint) -> QPointF:
        rect = self._image_rect_provider()
        return QPointF(
            rect.x() + point.x * rect.width(),
            rect.y() + point.y * rect.height(),
        )

    def _to_normalized(self, pos: QPointF) -> tuple[float, float]:
        rect = self._image_rect_provider()
        if rect.width() <= 0 or rect.height() <= 0:
            return 0.0, 0.0
        x = (pos.x() - rect.x()) / rect.width()
        y = (pos.y() - rect.y()) / rect.height()
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))

    def _hit_test_point(self, pos: QPointF) -> tuple[str, int] | None:
        node = self._node()
        if node is None:
            return None
        frame = self.project.current_frame
        for shape in node.document.shapes:
            for index, point in enumerate(interpolate_points(shape.keyframes, frame)):
                widget_pos = self._to_widget_pos(point)
                dx = widget_pos.x() - pos.x()
                dy = widget_pos.y() - pos.y()
                if dx * dx + dy * dy <= _HIT_RADIUS_SQUARED:
                    return shape.shape_id, index
        return None

    def _find_shape(self, document: RotoDocument, shape_id: str) -> RotoShape | None:
        for shape in document.shapes:
            if shape.shape_id == shape_id:
                return shape
        return None

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or self._node_id is None:
            return
        pos = a0.position()
        if a0.button() == Qt.MouseButton.RightButton:
            self._cancel_drawing_shape()
            return
        if a0.button() != Qt.MouseButton.LeftButton:
            return

        hit = self._hit_test_point(pos)
        if hit is not None:
            self._selected_shape_id = hit[0]
            self._begin_drag(hit[0], hit[1])
            return

        if self._drawing_shape is not None:
            x, y = self._to_normalized(pos)
            self._drawing_points.append(RotoPoint(x=x, y=y))
        else:
            self._start_new_shape(pos)
        self.update()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or self._drag_shape_id is None or self._drag_point_index is None:
            return
        node = self._node()
        if node is None:
            return
        shape = self._find_shape(node.document, self._drag_shape_id)
        if shape is None:
            return
        points = shape.keyframes.get(self._drag_frame)
        if points is None or self._drag_point_index >= len(points):
            return
        x, y = self._to_normalized(a0.position())
        points[self._drag_point_index].x = x
        points[self._drag_point_index].y = y
        if self._node_id is not None:
            self.project.invalidate_cache(self._node_id)
        self.update()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        del a0
        if self._drag_shape_id is None:
            return
        self._commit_document_change(self._drag_old_document)
        self._drag_shape_id = None
        self._drag_point_index = None
        self._drag_old_document = None

    def mouseDoubleClickEvent(self, a0: QMouseEvent | None) -> None:
        del a0
        self._finalize_drawing_shape()

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        if a0 is None:
            return
        if a0.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finalize_drawing_shape()
            return
        if a0.key() == Qt.Key.Key_Escape:
            self._cancel_drawing_shape()
            return
        if a0.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._on_delete_shape_clicked()
            return
        super().keyPressEvent(a0)

    def _begin_drag(self, shape_id: str, point_index: int) -> None:
        node = self._node()
        if node is None:
            return
        shape = self._find_shape(node.document, shape_id)
        if shape is None:
            return
        self._drag_old_document = _clone_document(node.document)
        frame = self._edit_frame()
        current_points = interpolate_points(shape.keyframes, frame)
        working_points = [
            RotoPoint(x=p.x, y=p.y, handle_in=p.handle_in, handle_out=p.handle_out)
            for p in current_points
        ]
        shape.keyframes[frame] = working_points
        self._drag_shape_id = shape_id
        self._drag_point_index = point_index
        self._drag_frame = frame

    def _start_new_shape(self, pos: QPointF) -> None:
        x, y = self._to_normalized(pos)
        shape_id = f"shape_{uuid4().hex[:8]}"
        self._drawing_shape = RotoShape(
            shape_id=shape_id, closed=False, smooth=self._smooth_default
        )
        self._drawing_points = [RotoPoint(x=x, y=y)]

    def _finalize_drawing_shape(self) -> None:
        if self._drawing_shape is None or len(self._drawing_points) < 3:
            self._cancel_drawing_shape()
            return
        node = self._node()
        if node is None:
            self._cancel_drawing_shape()
            return
        old_document = _clone_document(node.document)
        shape = self._drawing_shape
        shape.closed = True
        shape.keyframes[self._edit_frame()] = self._drawing_points
        node.document.shapes.append(shape)
        self._selected_shape_id = shape.shape_id
        self._drawing_shape = None
        self._drawing_points = []
        self._commit_document_change(old_document)

    def _cancel_drawing_shape(self) -> None:
        self._drawing_shape = None
        self._drawing_points = []
        self.update()

    def _commit_document_change(self, old_document: RotoDocument | None) -> None:
        node = self._node()
        if node is None or self._node_id is None:
            return
        new_document = _clone_document(node.document)
        if self.history is not None and old_document is not None:
            self.history.push(
                EditRotoDocumentCommand(
                    self._node_id, new_document, old_document=old_document
                )
            )
        else:
            self.project.invalidate_cache(self._node_id)
        self.update()

    def _on_add_shape_clicked(self) -> None:
        self._cancel_drawing_shape()
        self._selected_shape_id = None

    def _on_toggle_smooth_clicked(self) -> None:
        self._smooth_default = self._toolbar.smooth_button.isChecked()
        if self._drawing_shape is not None:
            self._drawing_shape.smooth = self._smooth_default
            self.update()
            return
        node = self._node()
        if node is None or self._selected_shape_id is None:
            return
        shape = self._find_shape(node.document, self._selected_shape_id)
        if shape is None:
            return
        old_document = _clone_document(node.document)
        shape.smooth = self._smooth_default
        self._commit_document_change(old_document)

    def _on_toggle_auto_key_clicked(self) -> None:
        self._auto_key = self._toolbar.auto_key_button.isChecked()

    def _on_delete_shape_clicked(self) -> None:
        node = self._node()
        if node is None or self._selected_shape_id is None:
            return
        shape = self._find_shape(node.document, self._selected_shape_id)
        if shape is None:
            return
        old_document = _clone_document(node.document)
        node.document.shapes.remove(shape)
        self._selected_shape_id = None
        self._commit_document_change(old_document)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        del a0
        node = self._node()
        if node is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        frame = self.project.current_frame
        for shape in node.document.shapes:
            points = interpolate_points(shape.keyframes, frame)
            self._draw_shape(
                painter,
                points,
                shape.closed,
                selected=shape.shape_id == self._selected_shape_id,
            )
        if self._drawing_shape is not None:
            self._draw_shape(painter, self._drawing_points, False, selected=True)
        painter.end()

    def _draw_shape(
        self,
        painter: QPainter,
        points: list[RotoPoint],
        closed: bool,
        *,
        selected: bool,
    ) -> None:
        if not points:
            return
        color = _ACTIVE_COLOR if selected else _SHAPE_COLOR
        pen = QPen(color)
        pen.setWidth(2)
        painter.setPen(pen)
        widget_points = [self._to_widget_pos(p) for p in points]
        for i in range(len(widget_points) - 1):
            painter.drawLine(widget_points[i], widget_points[i + 1])
        if closed and len(widget_points) > 2:
            painter.drawLine(widget_points[-1], widget_points[0])
        painter.setBrush(color)
        for widget_point in widget_points:
            painter.drawEllipse(widget_point, _POINT_RADIUS, _POINT_RADIUS)
