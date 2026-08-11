"""Properties panel for editing the selected node's parameters."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.theme import PROPERTIES_STYLE
from core.events import ObserverEvent
from core.history import HistoryStack, SetPropertyCommand
from core.nodes import (
    NodeProperty,
    NodePropertyInputType,
    VideoFrameErrorMethod,
    VideoInputNode,
)
from core.project import Project
from render.video_decoder import probe_video


class MediaProbeThread(QThread):
    """Probe video metadata off the UI thread so file browse stays responsive."""

    probed = pyqtSignal(float, float, int, int)
    failed = pyqtSignal(str)

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        info = probe_video(self._path)
        if info is None or info.duration_sec <= 0.0:
            self.failed.emit(f"Could not read video: {self._path}")
            return
        self.probed.emit(info.fps, info.duration_sec, info.width, info.height)


class PropertyWidget(QWidget):
    """Base class for a single property editor control."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.prop = prop
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)

    def get_value(self) -> Any:
        raise NotImplementedError

    def set_value(self, value: Any) -> None:
        raise NotImplementedError


class NumberPropertyWidget(PropertyWidget):
    """Integer or float numeric editor (spin box, not a slider)."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)
        self._is_int = isinstance(prop.value, int)
        low = float(prop.slider_min_value)
        high = float(prop.slider_max_value)
        if high <= low:
            low, high = -999999.0, 999999.0

        if self._is_int:
            spin: QSpinBox | QDoubleSpinBox = QSpinBox()
            spin.setRange(int(low), int(high))
            spin.setValue(int(prop.value or 0))
            spin.setSingleStep(1)
        else:
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setValue(float(prop.value or 0.0))

        spin.setObjectName("PropertySpin")
        spin.setMinimumHeight(28)
        self.spinbox = spin
        self._row.addWidget(spin)

    def get_value(self) -> Any:
        return int(self.spinbox.value()) if self._is_int else float(self.spinbox.value())

    def set_value(self, value: Any) -> None:
        if self._is_int:
            self.spinbox.setValue(int(value or 0))
        else:
            self.spinbox.setValue(float(value or 0.0))


class SliderPropertyWidget(PropertyWidget):
    """Horizontal slider with a recessed value readout."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("PropertySlider")
        self.slider.setMinimum(int(prop.slider_min_value or 0))
        self.slider.setMaximum(int(prop.slider_max_value or 100))
        self.slider.setValue(int(prop.value or 0))
        self.slider.setMinimumHeight(28)

        self.value_label = QLabel(str(int(prop.value or 0)))
        self.value_label.setObjectName("PropertySliderValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slider.valueChanged.connect(lambda v: self.value_label.setText(str(v)))

        self._row.addWidget(self.slider, 1)
        self._row.addWidget(self.value_label)


class FilePropertyWidget(PropertyWidget):
    """Read-only path field with a browse button."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)
        self.file_input = QLineEdit()
        self.file_input.setObjectName("PropertyField")
        self.file_input.setText(str(prop.value or ""))
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText("No file selected")
        self.file_input.setMinimumHeight(28)

        self.browse_btn = QPushButton("…")
        self.browse_btn.setObjectName("PropertyBrowseButton")
        self._row.addWidget(self.file_input, 1)
        self._row.addWidget(self.browse_btn)

    def get_value(self) -> Any:
        return self.file_input.text()

    def set_value(self, value: Any) -> None:
        self.file_input.setText(str(value or ""))

    def get_browse_button(self) -> QPushButton:
        return self.browse_btn


class EnumPropertyWidget(PropertyWidget):
    """Dropdown for enum-backed properties."""

    def __init__(
        self,
        prop: NodeProperty,
        enum_class: type[Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(prop, parent)
        self.enum_class = enum_class
        self.combo = QComboBox()
        self.combo.setObjectName("PropertyCombo")
        self.combo.setMinimumHeight(28)

        for member in enum_class:
            self.combo.addItem(member.name, member)

        if prop.value is not None:
            index = self.combo.findData(prop.value)
            if index < 0 and isinstance(prop.value, int):
                index = self.combo.findData(enum_class(prop.value))
            if index >= 0:
                self.combo.setCurrentIndex(index)

        self._row.addWidget(self.combo)

    def get_value(self) -> Any:
        return self.combo.currentData()

    def set_value(self, value: Any) -> None:
        index = self.combo.findData(value)
        if index >= 0:
            self.combo.setCurrentIndex(index)


class CheckboxPropertyWidget(PropertyWidget):
    """Boolean toggle rendered as a styled checkbox."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)
        self.checkbox = QCheckBox("On")
        self.checkbox.setObjectName("PropertyCheck")
        self.checkbox.setChecked(bool(prop.value))
        self.checkbox.toggled.connect(self._sync_label)
        self._sync_label(bool(prop.value))
        self._row.addWidget(self.checkbox)
        self._row.addStretch(1)

    def _sync_label(self, checked: bool) -> None:
        self.checkbox.setText("On" if checked else "Off")

    def get_value(self) -> Any:
        return bool(self.checkbox.isChecked())

    def set_value(self, value: Any) -> None:
        checked = bool(value)
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)
        self._sync_label(checked)


class PropertyRow(QWidget):
    """Compact property block: label above control, no card chrome."""

    def __init__(self, title: str, editor: PropertyWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PropertyRow")
        self.editor = editor

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        label = QLabel(title)
        label.setObjectName("PropertyRowLabel")
        layout.addWidget(label)
        layout.addWidget(editor)


class PropertiesPanel(QWidget):
    """Edit selected node properties without stacking previous UI."""

    def __init__(self, project: Project, history: HistoryStack) -> None:
        super().__init__()
        self.setObjectName("PropertiesPanel")
        self.setStyleSheet(PROPERTIES_STYLE)

        self.project = project
        self.history = history
        self.current_node_id: str | None = None
        self.property_widgets: dict[str, PropertyWidget] = {}
        self._probe_thread: MediaProbeThread | None = None
        self._probe_generation: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("PropertiesScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)

        self._content = QWidget()
        self._content.setObjectName("PropertiesContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._scroll.setWidget(self._content)

        self.project.subscribe(self.on_project_changed)
        self._show_empty_state("Select a node")

    def set_project(self, project: Project, history: HistoryStack) -> None:
        """Retarget the panel at a newly loaded project / history stack."""
        self.project.unsubscribe(self.on_project_changed)
        self.project = project
        self.history = history
        self.current_node_id = None
        self.project.subscribe(self.on_project_changed)
        self._show_empty_state("Select a node")

    def on_project_changed(self, event: ObserverEvent, data: Any) -> None:
        if (
            event == ObserverEvent.NodeRemoved
            and isinstance(data, str)
            and data == self.current_node_id
        ):
            self.current_node_id = None
            self._show_empty_state("Select a node")
            return
        if (
            event == ObserverEvent.NodeModified
            and isinstance(data, str)
            and data == self.current_node_id
            and self.history.is_applying
        ):
            self._reload_current_node()
            node = self.project.nodes.get(data)
            if isinstance(node, VideoInputNode):
                path_prop = node.get_property("file_path")
                if path_prop is not None and path_prop.value:
                    self._start_media_probe(str(path_prop.value), data)

    def _reload_current_node(self) -> None:
        """Rebuild editors so undo/redo values match the model."""
        node_id = self.current_node_id
        if node_id is None:
            return
        self.current_node_id = None
        self.set_node(node_id)

    def _format_property_name(self, name: str) -> str:
        labels: dict[str, str] = {
            "file_path": "File Path",
            "start_frame": "Start Frame",
            "end_frame": "End Frame (-1 = last)",
            "frame_offset": "Frame Offset",
            "fps": "FPS (0 = source)",
            "speed": "Speed",
            "before_start": "Before Start",
            "after_end": "After End",
            "on_error": "On Error",
            "auto_sync_timeline": "Auto Sync Timeline",
            "preview_max_width": "Preview Max Width",
            "apply_exposure": "Apply Exposure",
            "flip_horizontal": "Flip Horizontal",
            "flip_vertical": "Flip Vertical",
            "prefetch_frames": "Prefetch Frames",
            "fit_mode": "Fit Mode",
        }
        if name in labels:
            return labels[name]
        return name.lstrip("_").replace("_", " ").title()

    def _replace_content(self) -> QVBoxLayout:
        """Swap the scroll content widget so old controls cannot ghost/stack.

        ``QScrollArea.setWidget`` takes ownership and destroys the previous
        widget, so we must not call ``deleteLater`` on it again.
        """
        self._content = QWidget()
        self._content.setObjectName("PropertiesContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._scroll.setWidget(self._content)
        self.property_widgets.clear()
        return self._content_layout

    def _show_empty_state(self, message: str) -> None:
        layout = self._replace_content()
        label = QLabel(message)
        label.setObjectName("PropertiesEmptyLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        layout.addStretch(1)

    def set_node(self, node_id: str) -> None:
        """Rebuild the panel for ``node_id`` (always replaces previous content)."""
        if self.current_node_id == node_id and self.property_widgets:
            return

        node = self.project.nodes.get(node_id)
        if node is None:
            self.current_node_id = None
            self._show_empty_state("Select a node")
            return

        self.current_node_id = node_id
        layout = self._replace_content()

        title = QLabel(node.name)
        title.setObjectName("PropertiesNodeTitle")
        layout.addWidget(title)

        divider = QFrame()
        divider.setObjectName("PropertiesDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        has_properties = False
        # Lower ``priority`` values appear first; ties break by name.
        ordered = sorted(
            node.properties.items(),
            key=lambda item: (item[1].priority, item[0]),
        )
        for prop_name, prop in ordered:
            if prop_name.startswith("_input_") or not isinstance(prop, NodeProperty):
                continue
            editor = self._create_property_widget(prop, prop_name)
            if editor is None:
                continue
            has_properties = True
            self.property_widgets[prop_name] = editor
            self._wire_editor(prop_name, editor)
            row = PropertyRow(self._format_property_name(prop_name), editor)
            layout.addWidget(row)

        if not has_properties:
            empty = QLabel("No properties")
            empty.setObjectName("PropertiesEmptyLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)

        layout.addStretch(1)

    def _wire_editor(self, prop_name: str, editor: PropertyWidget) -> None:
        if isinstance(editor, NumberPropertyWidget):
            editor.spinbox.valueChanged.connect(
                lambda v, p=prop_name: self.update_property(p, v)
            )
        elif isinstance(editor, SliderPropertyWidget):
            editor.slider.valueChanged.connect(
                lambda v, p=prop_name: self.update_property(p, v)
            )
        elif isinstance(editor, EnumPropertyWidget):
            editor.combo.currentIndexChanged.connect(
                lambda _i, p=prop_name, w=editor: self.update_property(p, w.get_value())
            )
        elif isinstance(editor, CheckboxPropertyWidget):
            editor.checkbox.toggled.connect(
                lambda checked, p=prop_name: self.update_property(p, bool(checked))
            )
        elif isinstance(editor, FilePropertyWidget):
            editor.get_browse_button().clicked.connect(
                lambda _checked=False, p=prop_name, w=editor: self.browse_file(p, w)
            )

    def _create_property_widget(
        self,
        prop: NodeProperty,
        prop_name: str,
    ) -> PropertyWidget | None:
        _ = prop_name
        if prop.input_type == NodePropertyInputType.File:
            return FilePropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Slider:
            return SliderPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Number:
            return NumberPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Checkbox:
            return CheckboxPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.VideoFrameErrorMethod:
            return EnumPropertyWidget(prop, VideoFrameErrorMethod)
        if prop.input_type == NodePropertyInputType.CustomChoice:
            if prop.value is None:
                return None
            return EnumPropertyWidget(prop, type(prop.value))
        return None

    def update_property(self, prop_name: str, value: Any) -> None:
        """Write a property value through history (coalesces rapid edits)."""
        if self.current_node_id is None or self.current_node_id not in self.project.nodes:
            return
        node = self.project.nodes[self.current_node_id]
        prop = node.get_property(prop_name)
        if prop is None:
            return

        if prop.input_type in {
            NodePropertyInputType.CustomChoice,
            NodePropertyInputType.VideoFrameErrorMethod,
        } and isinstance(value, int):
            enum_type = type(prop.value) if prop.value is not None else None
            if enum_type is not None:
                try:
                    value = enum_type(value)
                except ValueError:
                    pass

        if prop.value == value:
            return

        node_id = self.current_node_id
        if not self.history.push(
            SetPropertyCommand(node_id, prop_name, value, old_value=prop.value)
        ):
            return

        if prop_name == "file_path" and isinstance(node, VideoInputNode):
            self._start_media_probe(str(value), node_id)

    def _start_media_probe(self, path: str, node_id: str) -> None:
        if not path:
            return
        self._probe_generation += 1
        generation = self._probe_generation
        thread = MediaProbeThread(path)
        thread.probed.connect(
            lambda fps, dur, w, h, gen=generation, nid=node_id: self._on_probe_ok(
                gen, nid, fps, dur, w, h
            )
        )
        thread.failed.connect(
            lambda msg, gen=generation, nid=node_id: self._on_probe_failed(
                gen, nid, msg
            )
        )
        self._probe_thread = thread
        thread.start()

    def _on_probe_ok(
        self,
        generation: int,
        node_id: str,
        fps: float,
        duration_sec: float,
        width: int,
        height: int,
    ) -> None:
        if generation != self._probe_generation:
            return
        node = self.project.nodes.get(node_id)
        sync_prop = node.get_property("auto_sync_timeline") if node is not None else None
        should_sync = sync_prop is None or bool(sync_prop.value)
        if should_sync:
            # sync_timeline_from_media clears cache and emits FrameChanged.
            self.project.sync_timeline_from_media(
                fps=fps,
                duration_sec=duration_sec,
                width=width,
                height=height,
            )
        self.project.invalidate_cache(node_id)

    def _on_probe_failed(self, generation: int, node_id: str, message: str) -> None:
        if generation != self._probe_generation:
            return
        _ = message
        self.project.invalidate_cache(node_id)

    def browse_file(self, prop_name: str, widget: FilePropertyWidget) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a video file",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)",
        )
        if file_path:
            widget.set_value(file_path)
            self.update_property(prop_name, file_path)
