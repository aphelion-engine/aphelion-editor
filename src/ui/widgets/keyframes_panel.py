"""Optional panel listing keyframes on the selected node."""

from __future__ import annotations

from typing import Final

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.theme import KEYFRAMES_PANEL_STYLE
from core.animation import AnimationCurve
from core.events import ObserverEvent
from core.history import HistoryStack, RemoveKeyframeCommand, SetKeyframeCommand
from core.nodes import Node, NodeProperty, NodePropertyInputType
from core.project import Project

_ANIMATABLE_INPUT_TYPES: Final[frozenset[NodePropertyInputType]] = frozenset(
    {NodePropertyInputType.Slider, NodePropertyInputType.Number}
)
_GOLD: Final[str] = "#ffbe3c"
_GOLD_DIM: Final[str] = "#8a7030"
_NEUTRAL: Final[str] = "#505058"


class KeyframeRulerWidget(QWidget):
    """Compact horizontal map of keyed frames across the project timeline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty ruler."""
        super().__init__(parent)
        self.setObjectName("KeyframeRuler")
        self.setFixedHeight(28)
        self._frames: tuple[int, ...] = ()
        self._current_frame: int = 0
        self._max_frame: int = 0

    def set_state(
        self,
        *,
        frames: tuple[int, ...],
        current_frame: int,
        max_frame: int,
    ) -> None:
        """Update keyed frames and repaint."""
        self._frames = frames
        self._current_frame = max(0, int(current_frame))
        self._max_frame = max(0, int(max_frame))
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Draw keyed-frame ticks and the playhead."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        height = self.height()
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)

        baseline_y = height - 6
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1.0))
        painter.drawLine(4, baseline_y, width - 4, baseline_y)

        span = max(1, self._max_frame)
        for frame in self._frames:
            x = 4 + (width - 8) * (frame / span)
            painter.setPen(QPen(_GOLD, 1.4))
            painter.drawLine(int(x), baseline_y - 10, int(x), baseline_y)

        playhead_x = 4 + (width - 8) * (self._current_frame / span)
        painter.setPen(QPen(Qt.GlobalColor.white, 1.6))
        painter.drawLine(int(playhead_x), 4, int(playhead_x), baseline_y)
        painter.end()


class KeyframePropertyRow(QWidget):
    """One animatable property and its keyed frame buttons."""

    frame_clicked = pyqtSignal(int)
    add_requested = pyqtSignal(str)
    remove_requested = pyqtSignal(str, int)

    def __init__(
        self,
        prop_name: str,
        label: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        """Build a property row with a horizontal frame list."""
        super().__init__(parent)
        self.prop_name: str = prop_name
        self.setObjectName("KeyframePropertyRow")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title = QLabel(label)
        title.setObjectName("KeyframePropertyLabel")
        header.addWidget(title, 1)
        add_button = QPushButton("+")
        add_button.setObjectName("KeyframeMiniButton")
        add_button.setFixedSize(22, 22)
        add_button.setToolTip("Add keyframe at the current frame")
        add_button.clicked.connect(lambda: self.add_requested.emit(self.prop_name))
        header.addWidget(add_button)
        root.addLayout(header)

        self._frames_row = QWidget()
        self._frames_layout = QHBoxLayout(self._frames_row)
        self._frames_layout.setContentsMargins(0, 0, 0, 0)
        self._frames_layout.setSpacing(4)
        self._frames_layout.addStretch(1)
        root.addWidget(self._frames_row)

        self._empty_label = QLabel("No keyframes")
        self._empty_label.setObjectName("KeyframeEmptyLabel")
        root.addWidget(self._empty_label)

    def set_keyframes(
        self,
        *,
        frames: tuple[int, ...],
        current_frame: int,
        values: dict[int, float],
    ) -> None:
        """Rebuild frame chips for this property."""
        while self._frames_layout.count() > 1:
            item = self._frames_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        has_frames = bool(frames)
        self._frames_row.setVisible(has_frames)
        self._empty_label.setVisible(not has_frames)
        if not has_frames:
            return

        for frame in frames:
            value = values.get(frame, 0.0)
            button = QPushButton(str(frame))
            button.setObjectName("KeyframeFrameChip")
            button.setFixedHeight(22)
            button.setToolTip(f"Frame {frame}: {value:.4g}")
            is_current = frame == current_frame
            if is_current:
                button.setProperty("current", True)
            button.clicked.connect(
                lambda _checked=False, f=frame: self.frame_clicked.emit(f)
            )
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda _pos, f=frame: self.remove_requested.emit(self.prop_name, f)
            )
            self._frames_layout.insertWidget(self._frames_layout.count() - 1, button)
            button.style().unpolish(button)
            button.style().polish(button)


class KeyframesPanelWidget(QWidget):
    """Browse and edit keyframes for the selected node's numeric properties."""

    def __init__(self, project: Project, history: HistoryStack) -> None:
        """Subscribe to project events and build the panel chrome."""
        super().__init__()
        self.setObjectName("KeyframesPanelWidget")
        self.setStyleSheet(KEYFRAMES_PANEL_STYLE)

        self.project: Project = project
        self.history: HistoryStack = history
        self.current_node_id: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self._header = QLabel("Select a node")
        self._header.setObjectName("KeyframesHeader")
        root.addWidget(self._header)

        self._ruler = KeyframeRulerWidget()
        root.addWidget(self._ruler)

        toolbar = QWidget()
        toolbar.setObjectName("KeyframesToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(6)

        self._property_combo = QComboBox()
        self._property_combo.setObjectName("KeyframesPropertyCombo")
        self._property_combo.currentIndexChanged.connect(self._on_property_combo_changed)
        toolbar_layout.addWidget(self._property_combo, 1)

        self._add_button = QPushButton("Add Keyframe")
        self._add_button.setObjectName("KeyframesActionButton")
        self._add_button.clicked.connect(self._add_keyframe_at_playhead)
        toolbar_layout.addWidget(self._add_button)

        self._remove_button = QPushButton("Remove")
        self._remove_button.setObjectName("KeyframesActionButton")
        self._remove_button.clicked.connect(self._remove_keyframe_at_playhead)
        toolbar_layout.addWidget(self._remove_button)
        root.addWidget(toolbar)

        divider = QFrame()
        divider.setObjectName("KeyframesDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("KeyframesScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        root.addWidget(self._scroll, 1)

        self._content = QWidget()
        self._content.setObjectName("KeyframesContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        self._scroll.setWidget(self._content)

        self._empty_state = QLabel("No animatable properties")
        self._empty_state.setObjectName("KeyframesEmptyState")
        self._empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(self._empty_state)
        self._content_layout.addStretch(1)

        self.project.subscribe(self._on_project_changed)
        self._refresh()

    def set_project(self, project: Project, history: HistoryStack) -> None:
        """Retarget the panel at a newly loaded project."""
        self.project.unsubscribe(self._on_project_changed)
        self.project = project
        self.history = history
        self.current_node_id = None
        self.project.subscribe(self._on_project_changed)
        self._refresh()

    def set_node(self, node_id: str | None) -> None:
        """Show keyframes for ``node_id``."""
        self.current_node_id = node_id
        self._refresh()

    def _on_project_changed(self, event: ObserverEvent, data: object) -> None:
        """Refresh when the playhead or animated data changes."""
        if event == ObserverEvent.FrameChanged:
            self._refresh_highlight()
            return
        if event == ObserverEvent.NodeRemoved and data == self.current_node_id:
            self.current_node_id = None
            self._refresh()
            return
        if (
            event == ObserverEvent.NodeModified
            and isinstance(data, str)
            and data == self.current_node_id
        ):
            self._refresh()

    def _refresh_highlight(self) -> None:
        """Update playhead highlight without rebuilding the whole panel."""
        node = self._current_node()
        if node is None:
            return
        self._update_ruler(node)
        for index in range(self._content_layout.count()):
            item = self._content_layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if not isinstance(widget, KeyframePropertyRow):
                continue
            curve = node.animated_properties.get(widget.prop_name)
            frames, values = self._curve_frames(curve)
            widget.set_keyframes(
                frames=frames,
                current_frame=self.project.current_frame,
                values=values,
            )
        self._sync_action_buttons(node)

    def _refresh(self) -> None:
        """Rebuild the property list and toolbar."""
        self._clear_rows()
        node = self._current_node()
        if node is None:
            self._header.setText("Select a node")
            self._ruler.set_state(frames=(), current_frame=0, max_frame=0)
            self._property_combo.clear()
            self._empty_state.setText("Select a node in the graph")
            self._empty_state.show()
            self._set_toolbar_enabled(False)
            return

        self._header.setText(f"{node.name}  ·  {node.node_type}")
        animatable = self._animatable_properties(node)
        self._property_combo.blockSignals(True)
        self._property_combo.clear()
        for prop_name, prop in animatable:
            label = prop.label or prop_name.replace("_", " ").title()
            self._property_combo.addItem(label, prop_name)
        self._property_combo.blockSignals(False)
        self._set_toolbar_enabled(bool(animatable))

        if not animatable:
            self._empty_state.setText("No animatable properties on this node")
            self._empty_state.show()
            self._update_ruler(node)
            return

        self._empty_state.hide()
        animated_any = False
        for prop_name, prop in animatable:
            curve = node.animated_properties.get(prop_name)
            frames, values = self._curve_frames(curve)
            if frames:
                animated_any = True
            label = prop.label or prop_name.replace("_", " ").title()
            row = KeyframePropertyRow(prop_name, label)
            row.frame_clicked.connect(self._seek_frame)
            row.add_requested.connect(self._add_keyframe)
            row.remove_requested.connect(self._remove_keyframe)
            row.set_keyframes(
                frames=frames,
                current_frame=self.project.current_frame,
                values=values,
            )
            self._content_layout.insertWidget(self._content_layout.count() - 1, row)

        if not animated_any:
            hint = QLabel("Use Add Keyframe to animate a property at the playhead.")
            hint.setObjectName("KeyframesHintLabel")
            hint.setWordWrap(True)
            self._content_layout.insertWidget(self._content_layout.count() - 1, hint)

        self._update_ruler(node)
        self._sync_action_buttons(node)

    def _clear_rows(self) -> None:
        """Remove dynamic property rows while keeping the empty-state stub."""
        while self._content_layout.count() > 2:
            item = self._content_layout.takeAt(1)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _current_node(self) -> Node | None:
        """Return the selected node, if it still exists."""
        if self.current_node_id is None:
            return None
        return self.project.nodes.get(self.current_node_id)

    @staticmethod
    def _animatable_properties(node: Node) -> list[tuple[str, NodeProperty]]:
        """Return sorted numeric properties eligible for keyframes."""
        items: list[tuple[str, NodeProperty]] = []
        for key, prop in node.properties.items():
            if key.startswith("_input_") or key.startswith("in_"):
                continue
            if prop.input_type not in _ANIMATABLE_INPUT_TYPES:
                continue
            items.append((key, prop))
        items.sort(key=lambda item: (item[1].priority, item[0]))
        return items

    @staticmethod
    def _curve_frames(
        curve: AnimationCurve | None,
    ) -> tuple[tuple[int, ...], dict[int, float]]:
        """Return sorted frame numbers and values for one curve."""
        if curve is None or curve.is_empty:
            return (), {}
        frames = tuple(sorted(curve.keyframes.keys()))
        return frames, dict(curve.keyframes)

    def _all_keyed_frames(self, node: Node) -> tuple[int, ...]:
        """Return every keyed frame across animatable properties."""
        frames: set[int] = set()
        for prop_name, _prop in self._animatable_properties(node):
            curve = node.animated_properties.get(prop_name)
            if curve is None or curve.is_empty:
                continue
            frames.update(curve.keyframes.keys())
        return tuple(sorted(frames))

    def _update_ruler(self, node: Node) -> None:
        """Refresh the compact timeline ruler."""
        self._ruler.set_state(
            frames=self._all_keyed_frames(node),
            current_frame=self.project.current_frame,
            max_frame=self.project.max_frame,
        )

    def _set_toolbar_enabled(self, enabled: bool) -> None:
        """Enable or disable keyframe editing controls."""
        self._property_combo.setEnabled(enabled)
        self._add_button.setEnabled(enabled)
        self._remove_button.setEnabled(enabled)

    def _selected_property_name(self) -> str | None:
        """Return the property key selected in the toolbar combo."""
        value: object = self._property_combo.currentData()
        return str(value) if value else None

    def _resolved_property_value(self, node: Node, prop_name: str) -> float | None:
        """Return the property's effective numeric value at the playhead."""
        prop = node.get_property(prop_name)
        if prop is None:
            return None
        curve = node.animated_properties.get(prop_name)
        if curve is not None and not curve.is_empty:
            return float(curve.value_at(self.project.current_frame))
        raw = prop.value
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)

    def _sync_action_buttons(self, node: Node) -> None:
        """Update remove-button enabled state for the current frame."""
        prop_name = self._selected_property_name()
        if prop_name is None:
            self._remove_button.setEnabled(False)
            return
        curve = node.animated_properties.get(prop_name)
        has_key = curve is not None and curve.has_keyframe_at(
            self.project.current_frame
        )
        self._remove_button.setEnabled(has_key)
        frame = self.project.current_frame
        self._add_button.setText(f"Add at F{frame}")

    def _on_property_combo_changed(self, _index: int) -> None:
        """Refresh toolbar enabled state when the target property changes."""
        node = self._current_node()
        if node is not None:
            self._sync_action_buttons(node)

    def _seek_frame(self, frame_num: int) -> None:
        """Move the timeline playhead to ``frame_num``."""
        self.project.set_frame(frame_num)

    def _add_keyframe_at_playhead(self) -> None:
        """Add a keyframe for the toolbar-selected property."""
        prop_name = self._selected_property_name()
        if prop_name is not None:
            self._add_keyframe(prop_name)

    def _remove_keyframe_at_playhead(self) -> None:
        """Remove a keyframe for the toolbar-selected property."""
        prop_name = self._selected_property_name()
        if prop_name is None:
            return
        self._remove_keyframe(prop_name, self.project.current_frame)

    def _add_keyframe(self, prop_name: str) -> None:
        """Insert a keyframe at the playhead using the current resolved value."""
        node_id = self.current_node_id
        node = self._current_node()
        if node_id is None or node is None:
            return
        frame = self.project.current_frame
        curve = node.animated_properties.get(prop_name)
        if curve is not None and curve.has_keyframe_at(frame):
            return
        value = self._resolved_property_value(node, prop_name)
        if value is None:
            return
        self.history.push(SetKeyframeCommand(node_id, prop_name, frame, value))
        self._refresh()

    def _remove_keyframe(self, prop_name: str, frame_num: int) -> None:
        """Delete one explicit keyframe."""
        node_id = self.current_node_id
        node = self._current_node()
        if node_id is None or node is None:
            return
        curve = node.animated_properties.get(prop_name)
        if curve is None or not curve.has_keyframe_at(frame_num):
            return
        self.history.push(RemoveKeyframeCommand(node_id, prop_name, frame_num))
        self._refresh()
