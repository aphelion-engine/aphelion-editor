"""Interactive viewport overlay for placing/dragging Tracker seed points.

Mirrors ``ui.widgets.roto_overlay``'s interaction model so the two feel
consistent: drag a point live (mutating the model directly for immediate
visual feedback), then commit the whole gesture as one undo step on
mouse release.

Orange points are un-tracked seed positions (used the next time "Track"
runs); green points already carry tracked keyframes, and dragging one edits
that curve at the current frame instead of the seed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QGridLayout, QLayout, QPushButton, QSizePolicy, QWidget

from core.animation import AnimationCurve
from core.history import (
    CompositeCommand,
    SetPlanarTrackCommand,
    SetPropertyCommand,
    SetTrackCommand,
)
from core.nodes.shape_tracker import ShapeTrackerNode
from core.nodes.enums import TrackerShape
from core.nodes.tracking_nodes import PlanarTrackerNode, TrackerNode
from ui.widgets.tracking_actions import CORNER_NAMES, clear_tracking, run_tracking

if TYPE_CHECKING:
    from core.history import HistoryStack
    from core.project import Project

TrackerLike = TrackerNode | PlanarTrackerNode

# Visual sizing, in overlay-widget pixels.
_POINT_RADIUS: float = 5.0
_HIT_RADIUS_SQUARED: float = 9.0 * 9.0

_SEED_COLOR: QColor = QColor(255, 140, 40)
_TRACKED_COLOR: QColor = QColor(90, 220, 130)


def _clone_curve(curve: AnimationCurve) -> AnimationCurve:
    """Deep-copy a curve via its own JSON-native round-trip."""
    return AnimationCurve.from_dict(curve.to_dict())


def _point_keys(node: TrackerLike) -> tuple[str, ...]:
    """Return the point keys this tracker exposes ("point", or corner names)."""
    if isinstance(node, PlanarTrackerNode):
        return CORNER_NAMES
    return ("point",)


def _seed_property_names(node: TrackerLike, key: str) -> tuple[str, str]:
    """Return the ``(x_property, y_property)`` names backing ``key``'s seed."""
    if isinstance(node, PlanarTrackerNode):
        return f"{key}_seed_x", f"{key}_seed_y"
    return "center_x", "center_y"


def _seed_position(node: TrackerLike, key: str) -> tuple[float, float]:
    """Return ``key``'s normalized seed position."""
    if isinstance(node, PlanarTrackerNode):
        return node.seed_corners()[CORNER_NAMES.index(key)]
    return node.seed_position()


def _set_seed_position(node: TrackerLike, key: str, x: float, y: float) -> None:
    """Write ``key``'s seed position (normalized 0-1) back as percent properties."""
    x_prop, y_prop = _seed_property_names(node, key)
    node.set_property(x_prop, x * 100.0)
    node.set_property(y_prop, y * 100.0)


def _curve_pair(node: TrackerLike, key: str) -> tuple[AnimationCurve, AnimationCurve]:
    """Return ``key``'s ``(x_curve, y_curve)``."""
    if isinstance(node, PlanarTrackerNode):
        return node.corner_curves[key]
    return node.track_x, node.track_y


def _set_curve_pair(
    node: TrackerLike, key: str, curve_x: AnimationCurve, curve_y: AnimationCurve
) -> None:
    """Assign ``key``'s ``(x_curve, y_curve)`` directly on the node."""
    if isinstance(node, PlanarTrackerNode):
        node.corner_curves[key] = (curve_x, curve_y)
    else:
        node.track_x = curve_x
        node.track_y = curve_y


def _is_tracked(node: TrackerLike, key: str) -> bool:
    """Return whether ``key`` already carries tracked keyframes."""
    curve_x, curve_y = _curve_pair(node, key)
    return not curve_x.is_empty and not curve_y.is_empty


def _display_position(node: TrackerLike, key: str, frame: int) -> tuple[float, float]:
    """Return ``key``'s normalized position to draw at ``frame``."""
    if isinstance(node,TrackerNode) and frame in node.track_samples:
        position = node.tracking_position(frame)
        sample = node.track_samples[frame]
        if position is not None:
            return position
        if sample.predicted_x is not None:
            return sample.predicted_x,sample.predicted_y
        return node.seed_position()
    curve_x, curve_y = _curve_pair(node, key)
    if not curve_x.is_empty and not curve_y.is_empty:
        return curve_x.value_at(frame), curve_y.value_at(frame)
    return _seed_position(node, key)


class _TrackerToolbar(QWidget):
    """Small floating control strip: track backward/forward, clear."""

    def __init__(
        self,
        *,
        on_track_backward: Callable[[], None],
        on_track_forward: Callable[[], None],
        on_clear: Callable[[], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TrackerOverlayToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QWidget#TrackerOverlayToolbar { background-color: rgba(20, 20, 20, 200);"
            " border-radius: 4px; }"
            "QPushButton { color: #e0e0e0; background-color: rgba(255, 255, 255, 20);"
            " border: 1px solid #555555; border-radius: 3px; padding: 3px 8px;"
            " font-size: 11px; }"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 40); }"
        )
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.track_backward_button = QPushButton("◄ Track")
        self.track_backward_button.setToolTip("Track backward to frame 0")
        self.track_backward_button.clicked.connect(on_track_backward)
        layout.addWidget(self.track_backward_button, 0, 0)

        self.track_forward_button = QPushButton("Track ►")
        self.track_forward_button.setToolTip("Track forward to the last frame")
        self.track_forward_button.clicked.connect(on_track_forward)
        layout.addWidget(self.track_forward_button, 0, 1)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Remove all tracked keyframes")
        self.clear_button.clicked.connect(on_clear)
        layout.addWidget(self.clear_button, 0, 2)

        self.draw_button = QPushButton("Draw polygon")
        self.draw_button.setCheckable(True)
        self.draw_button.setToolTip("Toggle polygon drawing, then click the image to add vertices. Turn off to move the tracking point. At least three vertices form a mask.")
        self.remove_vertex_button = QPushButton("Undo vertex")
        self.remove_vertex_button.setToolTip("Remove the last polygon vertex. This edit can also be undone with Undo.")
        self.clear_shape_button = QPushButton("Clear polygon")
        self.clear_shape_button.setToolTip("Remove polygon vertices without clearing the tracked motion.")
        for column, button in enumerate((self.draw_button,self.remove_vertex_button,self.clear_shape_button)):
            layout.addWidget(button,1,column)
            button.hide()
        for button in self.findChildren(QPushButton):
            button.setMinimumHeight(30)
            button.setMinimumWidth(button.sizeHint().width())
        self.adjustSize()


class TrackerOverlayWidget(QWidget):
    """Transparent overlay drawing/editing a Tracker's point(s) in place.

    Coordinate mapping: normalized (0-1) positions map to overlay pixels via
    ``image_rect_provider``, which returns the rectangle the displayed frame
    currently occupies inside the viewport label (see
    ``ViewportWidget.displayed_image_rect``).
    """

    def __init__(
        self,
        project: Project,
        history: HistoryStack | None,
        image_rect_provider: Callable[[], QRect],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TrackerOverlay")
        self.project = project
        self.history = history
        self._image_rect_provider = image_rect_provider
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._node_id: str | None = None
        self._drag_key: str | None = None
        self._drag_was_tracked: bool = False
        self._drag_old_seed: tuple[float, float] | None = None
        self._drag_old_curves: tuple[AnimationCurve, AnimationCurve] | None = None

        self._toolbar = _TrackerToolbar(
            on_track_backward=lambda: self._run_track(direction=-1),
            on_track_forward=lambda: self._run_track(direction=1),
            on_clear=self._on_clear_clicked,
            parent=self,
        )
        self._toolbar.move(8, 8)
        self._toolbar.remove_vertex_button.clicked.connect(lambda: self._edit_polygon(remove=True))
        self._toolbar.clear_shape_button.clicked.connect(lambda: self._edit_polygon(clear=True))
        self._toolbar.hide()

        self.hide()

    def set_edit_target(self, node_id: str | None) -> None:
        """Arm (``node_id`` set to a tracker) or disarm interactive editing."""
        node = self.project.nodes.get(node_id) if node_id is not None else None
        self._node_id = node_id if isinstance(node, (TrackerNode, PlanarTrackerNode)) else None
        self._cancel_drag()
        self._toolbar.draw_button.setChecked(False)
        for button in (self._toolbar.draw_button,self._toolbar.remove_vertex_button,self._toolbar.clear_shape_button):
            button.setVisible(isinstance(node,ShapeTrackerNode))
        self._toolbar.setVisible(self._node_id is not None)
        self.setVisible(self._node_id is not None)
        if self._node_id is not None:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def sync_geometry(self, label_rect: QRect) -> None:
        """Resize to cover the viewport label so mapping stays pixel-accurate."""
        self.setGeometry(label_rect)

    def _node(self) -> TrackerLike | None:
        if self._node_id is None:
            return None
        node = self.project.nodes.get(self._node_id)
        return node if isinstance(node, (TrackerNode, PlanarTrackerNode)) else None

    def _to_widget_pos(self, x: float, y: float) -> QPointF:
        rect = self._image_rect_provider()
        return QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())

    def _to_normalized(self, pos: QPointF) -> tuple[float, float]:
        rect = self._image_rect_provider()
        if rect.width() <= 0 or rect.height() <= 0:
            return 0.0, 0.0
        x = (pos.x() - rect.x()) / rect.width()
        y = (pos.y() - rect.y()) / rect.height()
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))

    def _hit_test(self, pos: QPointF) -> str | None:
        node = self._node()
        if node is None:
            return None
        frame = self.project.current_frame
        best_key: str | None = None
        best_distance = _HIT_RADIUS_SQUARED
        for key in _point_keys(node):
            x, y = _display_position(node, key, frame)
            widget_pos = self._to_widget_pos(x, y)
            dx = widget_pos.x() - pos.x()
            dy = widget_pos.y() - pos.y()
            distance = dx * dx + dy * dy
            if distance <= best_distance:
                best_key = key
                best_distance = distance
        return best_key

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or self._node_id is None:
            return
        if a0.button() != Qt.MouseButton.LeftButton:
            return
        node = self._node()
        if node is None:
            return
        if isinstance(node,ShapeTrackerNode) and self._toolbar.draw_button.isChecked():
            self._edit_polygon(point=self._to_normalized(a0.position()))
            a0.accept()
            return
        key = self._hit_test(a0.position())
        if key is None:
            # A single-point Tracker has no ambiguity about "which point" —
            # clicking anywhere jumps it there directly, so placing a fresh
            # tracker is a single click rather than hunt-then-drag. A Planar
            # Tracker's four corners stay drag-only to avoid guessing intent.
            if isinstance(node, PlanarTrackerNode):
                return
            key = "point"
        self._begin_drag(key)
        self.mouseMoveEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or self._drag_key is None:
            return
        node = self._node()
        if node is None:
            return
        x, y = self._to_normalized(a0.position())
        if self._drag_was_tracked:
            curve_x, curve_y = _curve_pair(node, self._drag_key)
            curve_x.set_keyframe(self.project.current_frame, x)
            curve_y.set_keyframe(self.project.current_frame, y)
        else:
            _set_seed_position(node, self._drag_key, x, y)
        if self._node_id is not None:
            self.project.invalidate_cache(self._node_id)
        self.update()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        del a0
        if self._drag_key is None:
            return
        self._commit_drag()
        self._cancel_drag()

    def _begin_drag(self, key: str) -> None:
        node = self._node()
        if node is None:
            return
        self._drag_key = key
        self._drag_was_tracked = _is_tracked(node, key)
        if self._drag_was_tracked:
            curve_x, curve_y = _curve_pair(node, key)
            self._drag_old_curves = (_clone_curve(curve_x), _clone_curve(curve_y))
            # Give the drag a concrete keyframe to move at the current frame,
            # matching Roto's "seed a working point, then drag it" pattern.
            working_x = _clone_curve(curve_x)
            working_y = _clone_curve(curve_y)
            frame = self.project.current_frame
            working_x.set_keyframe(frame, working_x.value_at(frame))
            working_y.set_keyframe(frame, working_y.value_at(frame))
            _set_curve_pair(node, key, working_x, working_y)
        else:
            x_prop, y_prop = _seed_property_names(node, key)
            self._drag_old_seed = (
                node.float_value(x_prop, 0.0),
                node.float_value(y_prop, 0.0),
            )

    def _commit_drag(self) -> None:
        node = self._node()
        key = self._drag_key
        if node is None or self._node_id is None or key is None or self.history is None:
            if node is not None and self._node_id is not None:
                self.project.invalidate_cache(self._node_id)
            return

        if self._drag_was_tracked and self._drag_old_curves is not None:
            old_x, old_y = self._drag_old_curves
            new_x, new_y = _curve_pair(node, key)
            if isinstance(node, PlanarTrackerNode):
                old_curves = dict(node.corner_curves)
                old_curves[key] = (old_x, old_y)
                new_curves = dict(node.corner_curves)
                new_curves[key] = (new_x, new_y)
                self.history.push(
                    SetPlanarTrackCommand(
                        self._node_id, new_curves, old_corner_curves=old_curves
                    )
                )
            else:
                self.history.push(
                    SetTrackCommand(
                        self._node_id, new_x, new_y, old_track_x=old_x, old_track_y=old_y
                    )
                )
        elif self._drag_old_seed is not None:
            old_x_pct, old_y_pct = self._drag_old_seed
            x_prop, y_prop = _seed_property_names(node, key)
            new_x_pct = node.float_value(x_prop, 0.0)
            new_y_pct = node.float_value(y_prop, 0.0)
            self.history.push(
                CompositeCommand(
                    [
                        SetPropertyCommand(
                            self._node_id, x_prop, new_x_pct, old_value=old_x_pct
                        ),
                        SetPropertyCommand(
                            self._node_id, y_prop, new_y_pct, old_value=old_y_pct
                        ),
                    ],
                    "Move Tracker",
                )
            )
        self.update()

    def _cancel_drag(self) -> None:
        self._drag_key = None
        self._drag_was_tracked = False
        self._drag_old_seed = None
        self._drag_old_curves = None

    def _edit_polygon(self, *, point=None, remove=False, clear=False) -> None:
        node = self._node()
        if not isinstance(node,ShapeTrackerNode) or self._node_id is None:
            return
        vertices = node.polygon_vertices()
        if clear:
            vertices = []
        elif remove:
            vertices = vertices[:-1]
        elif point is not None:
            if len(vertices) >= 512:
                return
            center_x,center_y = _display_position(node,"point",self.project.current_frame)
            vertices.append(((point[0]-center_x)*100,(point[1]-center_y)*100))
        value = json.dumps(vertices)
        if self.history is not None:
            self.history.push(CompositeCommand([
                SetPropertyCommand(self._node_id,"vertices",value),
                SetPropertyCommand(self._node_id,"shape",TrackerShape.Polygon),
            ],"Edit tracked polygon"))
        else:
            node.set_property("vertices",value)
            node.set_property("shape",TrackerShape.Polygon)
            self.project.invalidate_cache(self._node_id)
        self.update()

    def _on_clear_clicked(self) -> None:
        node = self._node()
        if node is None or self._node_id is None or self.history is None:
            return
        clear_tracking(node, self._node_id, self.history)
        self.update()

    def _run_track(self, *, direction: int) -> None:
        node = self._node()
        if node is None or self._node_id is None or self.history is None:
            return
        run_tracking(
            node, self._node_id, self.project, self.history, direction=direction, parent=self
        )
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        del a0
        node = self._node()
        if node is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        frame = self.project.current_frame
        rect = self._image_rect_provider()
        region_w, region_h = node.region_size_normalized()
        search_radius = node.search_radius_normalized()
        is_planar = isinstance(node, PlanarTrackerNode)

        centers: list[QPointF] = []
        for key in _point_keys(node):
            x, y = _display_position(node, key, frame)
            center = self._to_widget_pos(x, y)
            centers.append(center)
            self._draw_point(
                painter,
                rect,
                center,
                region_w,
                region_h,
                search_radius,
                tracked=(_is_tracked(node,key) and (not isinstance(node,TrackerNode)
                         or frame not in node.track_samples or node.track_samples[frame].valid)),
                label=(key.replace("_", " ").title() if is_planar else self._sample_label(node,frame)),
            )

        if is_planar and len(centers) == 4:
            outline_pen = QPen(QColor(255, 255, 255, 90))
            outline_pen.setWidth(1)
            painter.setPen(outline_pen)
            for i in range(4):
                painter.drawLine(centers[i], centers[(i + 1) % 4])
        if isinstance(node,ShapeTrackerNode):
            points = [self._to_widget_pos(float(x),float(y)) for x,y in node.outline(frame)]
            painter.setPen(QPen(_TRACKED_COLOR,2))
            painter.setBrush(QColor(90,220,130,35))
            if len(points) >= 3:
                painter.drawPolygon(QPolygonF(points))
            elif len(points) == 2:
                painter.drawLine(points[0],points[1])
            if node.enum_value("shape",TrackerShape,TrackerShape.Ellipse) == TrackerShape.Polygon:
                for point in points:
                    painter.drawEllipse(point,3,3)
        painter.end()

    @staticmethod
    def _sample_label(node, frame):
        sample = node.track_samples.get(frame) if isinstance(node,TrackerNode) else None
        if sample is None:
            return None
        if sample.reacquired:
            return "Reacquired"
        if sample.valid:
            return "Tracked"
        if sample.predicted_x is not None:
            return f"{sample.state.value.title()} (prediction)"
        return "Lost"

    def _draw_point(
        self,
        painter: QPainter,
        rect: QRect,
        center: QPointF,
        region_w: float,
        region_h: float,
        search_radius: float,
        *,
        tracked: bool,
        label: str | None,
    ) -> None:
        color = _TRACKED_COLOR if tracked else _SEED_COLOR

        search_pen = QPen(color)
        search_pen.setStyle(Qt.PenStyle.DashLine)
        search_pen.setWidth(1)
        painter.setPen(search_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        search_radius_px = search_radius * rect.width()
        painter.drawEllipse(center, search_radius_px, search_radius_px)

        pattern_pen = QPen(color)
        pattern_pen.setWidth(1)
        painter.setPen(pattern_pen)
        half_w = region_w * rect.width() * 0.5
        half_h = region_h * rect.height() * 0.5
        painter.drawRect(QRectF(center.x() - half_w, center.y() - half_h, half_w * 2, half_h * 2))

        cross_pen = QPen(color)
        cross_pen.setWidth(2)
        painter.setPen(cross_pen)
        painter.drawLine(
            QPointF(center.x() - _POINT_RADIUS, center.y()),
            QPointF(center.x() + _POINT_RADIUS, center.y()),
        )
        painter.drawLine(
            QPointF(center.x(), center.y() - _POINT_RADIUS),
            QPointF(center.x(), center.y() + _POINT_RADIUS),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color if tracked else QColor(0, 0, 0, 0))
        painter.drawEllipse(center, _POINT_RADIUS, _POINT_RADIUS)

        if label is not None:
            painter.setPen(color)
            painter.drawText(center + QPointF(9, -9), label)
