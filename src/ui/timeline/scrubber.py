"""Interactive timeline scrubber with ruler, playhead, and in/out range."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPolygon
from PyQt6.QtWidgets import QWidget

RULER_HEIGHT_PX: int = 16
TRACK_HEIGHT_PX: int = 22
LEFT_GUTTER_PX: int = 8
RIGHT_GUTTER_PX: int = 8
PLAYHEAD_WIDTH_PX: int = 2
MARKER_WIDTH_PX: int = 2
MIN_MAJOR_TICK_SPACING_PX: int = 64
MINOR_TICKS_PER_MAJOR: int = 4

COLOR_BACKGROUND = QColor(22, 22, 22)
COLOR_RULER_BG = QColor(28, 28, 28)
COLOR_TRACK_BG = QColor(32, 32, 32)
COLOR_TRACK_BORDER = QColor(18, 18, 18)
COLOR_TICK_MAJOR = QColor(90, 90, 90)
COLOR_TICK_MINOR = QColor(55, 55, 55)
COLOR_TICK_TEXT = QColor(140, 140, 140)
COLOR_RANGE_FILL = QColor(43, 110, 168, 48)
COLOR_RANGE_EDGE = QColor(43, 110, 168, 180)
COLOR_PLAYHEAD = QColor(0, 150, 255)
COLOR_PLAYHEAD_GLOW = QColor(0, 150, 255, 60)


class TimelineScrubber(QWidget):
    """Clickable/draggable scrubber that emits frame seeks."""

    frame_scrubbed = pyqtSignal(int)
    in_point_changed = pyqtSignal(int)
    out_point_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_frame: int = 0
        self._current_frame: int = 0
        self._in_point: int = 0
        self._out_point: int = 0
        self._dragging_playhead: bool = False
        self._dragging_in: bool = False
        self._dragging_out: bool = False
        scrubber_height = RULER_HEIGHT_PX + TRACK_HEIGHT_PX
        self.setMinimumHeight(scrubber_height)
        self.setMaximumHeight(scrubber_height)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_range(self, max_frame: int) -> None:
        """Update timeline length and clamp markers.

        Parameters:
            max_frame: Inclusive last frame index.
        """
        self._max_frame = max(0, max_frame)
        self._current_frame = min(self._current_frame, self._max_frame)
        self._in_point = min(self._in_point, self._max_frame)
        self._out_point = max(self._in_point, min(self._out_point, self._max_frame))
        self.update()

    def set_frame(self, frame: int) -> None:
        """Set playhead frame without emitting signals."""
        self._current_frame = max(0, min(frame, self._max_frame))
        self.update()

    def set_in_point(self, frame: int) -> None:
        """Set in-point marker without emitting signals."""
        self._in_point = max(0, min(frame, self._out_point))
        self.update()

    def set_out_point(self, frame: int) -> None:
        """Set out-point marker without emitting signals."""
        self._out_point = max(self._in_point, min(frame, self._max_frame))
        self.update()

    @property
    def in_point(self) -> int:
        return self._in_point

    @property
    def out_point(self) -> int:
        return self._out_point

    def paintEvent(self, _event: object) -> None:
        """Draw ruler, work range, track, and playhead."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), COLOR_BACKGROUND)

        content = self._content_rect()
        painter.fillRect(
            QRectF(0, 0, self.width(), RULER_HEIGHT_PX),
            COLOR_RULER_BG,
        )
        self._paint_ticks(painter, content)
        self._paint_range(painter, content)
        self._paint_track(painter, content)
        self._paint_playhead(painter, content)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        """Begin scrubbing or marker drag on left press."""
        if event is None or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        frame = self._frame_at_x(x)
        near_in = abs(x - self._x_for_frame(self._in_point)) <= 6
        near_out = abs(x - self._x_for_frame(self._out_point)) <= 6
        if near_in:
            self._dragging_in = True
            self._set_in(frame)
        elif near_out:
            self._dragging_out = True
            self._set_out(frame)
        else:
            self._dragging_playhead = True
            self._seek(frame)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        """Continue active drag operation."""
        if event is None:
            return
        frame = self._frame_at_x(event.position().x())
        if self._dragging_playhead:
            self._seek(frame)
        elif self._dragging_in:
            self._set_in(frame)
        elif self._dragging_out:
            self._set_out(frame)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        """End any drag operation."""
        if event is None:
            return
        self._dragging_playhead = False
        self._dragging_in = False
        self._dragging_out = False
        event.accept()

    def _content_rect(self) -> QRectF:
        return QRectF(
            LEFT_GUTTER_PX,
            0,
            max(1.0, self.width() - LEFT_GUTTER_PX - RIGHT_GUTTER_PX),
            float(self.height()),
        )

    def _x_for_frame(self, frame: int) -> float:
        content = self._content_rect()
        if self._max_frame <= 0:
            return content.left()
        ratio = frame / self._max_frame
        return content.left() + ratio * content.width()

    def _frame_at_x(self, x: float) -> int:
        content = self._content_rect()
        if self._max_frame <= 0:
            return 0
        ratio = (x - content.left()) / content.width()
        ratio = max(0.0, min(1.0, ratio))
        return int(round(ratio * self._max_frame))

    def _seek(self, frame: int) -> None:
        clamped = max(0, min(frame, self._max_frame))
        if clamped == self._current_frame:
            return
        self._current_frame = clamped
        self.update()
        self.frame_scrubbed.emit(clamped)

    def _set_in(self, frame: int) -> None:
        clamped = max(0, min(frame, self._out_point))
        if clamped == self._in_point:
            return
        self._in_point = clamped
        self.update()
        self.in_point_changed.emit(clamped)

    def _set_out(self, frame: int) -> None:
        clamped = max(self._in_point, min(frame, self._max_frame))
        if clamped == self._out_point:
            return
        self._out_point = clamped
        self.update()
        self.out_point_changed.emit(clamped)

    def _major_step(self, content_width: float) -> int:
        if self._max_frame <= 0:
            return 1
        frames_per_pixel = self._max_frame / content_width
        raw = max(1, int(frames_per_pixel * MIN_MAJOR_TICK_SPACING_PX))
        nice_steps = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800)
        for step in nice_steps:
            if step >= raw:
                return step
        return nice_steps[-1]

    def _paint_ticks(self, painter: QPainter, content: QRectF) -> None:
        major = self._major_step(content.width())
        minor = max(1, major // MINOR_TICKS_PER_MAJOR)
        font = QFont("Cascadia Mono", 8)
        if not font.exactMatch():
            font = QFont("Consolas", 8)
        painter.setFont(font)

        frame = 0
        while frame <= self._max_frame:
            x = self._x_for_frame(frame)
            is_major = frame % major == 0
            pen = QPen(COLOR_TICK_MAJOR if is_major else COLOR_TICK_MINOR)
            painter.setPen(pen)
            tick_h = 10 if is_major else 5
            painter.drawLine(
                QPoint(int(x), RULER_HEIGHT_PX - tick_h),
                QPoint(int(x), RULER_HEIGHT_PX - 1),
            )
            if is_major:
                painter.setPen(QPen(COLOR_TICK_TEXT))
                painter.drawText(int(x) + 3, 12, str(frame))
            frame += minor

    def _paint_range(self, painter: QPainter, content: QRectF) -> None:
        if self._max_frame <= 0:
            return
        x0 = self._x_for_frame(self._in_point)
        x1 = self._x_for_frame(self._out_point)
        track_top = float(RULER_HEIGHT_PX)
        painter.fillRect(
            QRectF(x0, track_top, max(1.0, x1 - x0), float(TRACK_HEIGHT_PX)),
            COLOR_RANGE_FILL,
        )
        painter.fillRect(
            QRectF(x0, track_top, MARKER_WIDTH_PX, float(TRACK_HEIGHT_PX)),
            COLOR_RANGE_EDGE,
        )
        painter.fillRect(
            QRectF(x1 - MARKER_WIDTH_PX, track_top, MARKER_WIDTH_PX, float(TRACK_HEIGHT_PX)),
            COLOR_RANGE_EDGE,
        )

    def _paint_track(self, painter: QPainter, content: QRectF) -> None:
        track = QRectF(
            content.left(),
            float(RULER_HEIGHT_PX + 4),
            content.width(),
            float(TRACK_HEIGHT_PX - 8),
        )
        painter.fillRect(track, COLOR_TRACK_BG)
        painter.setPen(QPen(COLOR_TRACK_BORDER))
        painter.drawRect(track)

    def _paint_playhead(self, painter: QPainter, content: QRectF) -> None:
        x = self._x_for_frame(self._current_frame)
        painter.fillRect(
            QRectF(x - 2, 0, 6, float(self.height())),
            COLOR_PLAYHEAD_GLOW,
        )
        painter.fillRect(
            QRectF(x - PLAYHEAD_WIDTH_PX / 2, 0, PLAYHEAD_WIDTH_PX, float(self.height())),
            COLOR_PLAYHEAD,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(COLOR_PLAYHEAD)
        tip = QPolygon(
            [
                QPoint(int(x) - 5, 0),
                QPoint(int(x) + 5, 0),
                QPoint(int(x), 8),
            ]
        )
        painter.drawPolygon(tip)
