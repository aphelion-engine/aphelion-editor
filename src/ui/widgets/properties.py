"""Properties panel for editing the selected node's parameters."""

from __future__ import annotations

from enum import Enum
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.theme import PROPERTIES_STYLE
from core.animation import AnimationCurve
from core.events import Connection, ObserverEvent
from core.history import (
    HistoryStack,
    RemoveKeyframeCommand,
    SetKeyframeCommand,
    SetPlanarTrackCommand,
    SetPropertyCommand,
    SetTrackCommand,
)
from core.nodes import (
    Node,
    NodeProperty,
    NodePropertyInputType,
    VideoFrameErrorMethod,
    VideoInputNode,
)
from core.nodes.tracking_nodes import PlanarTrackerNode, TrackerNode
from core.nodes.math_nodes import PropertyDriveNode, PropertyLinkNode
from core.nodes.property_link import (
    PROPERTY_DRIVE_PROPERTY_KEY,
    PROPERTY_DRIVE_TARGET_SLOT,
    PROPERTY_LINK_PROPERTY_KEY,
    PROPERTY_LINK_SOURCE_SLOT,
    node_reference_id,
)
from aphelion_sdk.widgets.host import WidgetContext, WidgetHost, WidgetView
from app_io.plugin_loader import plugin_registry_key
from core.project import Project
from render.tracking_worker import (
    PlanarTrackingWorker,
    PointTrackingWorker,
    TrackingRequest,
)
from render.video_decoder import probe_video
from ui.widgets.property_editors import (
    CheckboxPropertyWidget,
    ColorPropertyWidget,
    CustomPropertyWidget,
    EnumPropertyWidget,
    EqCurvePropertyWidget,
    FilePropertyWidget,
    KeyframeButtonWidget,
    NodePropertyChoiceWidget,
    NumberPropertyWidget,
    PropertyRow,
    PropertyWidget,
    SliderPropertyWidget,
    TextPropertyWidget,
    coerce_color_rgb,
)

# Property input types eligible for keyframe animation (numeric-valued only).
_ANIMATABLE_INPUT_TYPES: frozenset[NodePropertyInputType] = frozenset(
    {NodePropertyInputType.Slider, NodePropertyInputType.Number}
)


def _split_xy_curves(
    result: dict[int, tuple[float, float]],
) -> tuple[AnimationCurve, AnimationCurve]:
    """Split a tracker's ``{frame: (x, y)}`` result into two curves."""
    curve_x = AnimationCurve()
    curve_y = AnimationCurve()
    for frame_num, (x, y) in result.items():
        curve_x.set_keyframe(frame_num, x)
        curve_y.set_keyframe(frame_num, y)
    return curve_x, curve_y


class MediaProbeThread(QThread):
    """Probe video metadata off the UI thread so file browse stays responsive."""

    probed = pyqtSignal(float, float, int, int, int)
    failed = pyqtSignal(str)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        info = probe_video(self._path)
        if info is None or info.duration_sec <= 0.0:
            self.failed.emit(f"Could not read video: {self._path}")
            return
        self.probed.emit(info.fps, info.duration_sec, info.width, info.height, info.frame_count)


class PropertiesPanel(QWidget):
    """Edit selected node properties without stacking previous UI."""

    custom_editor_requested = pyqtSignal(str, str, str)

    def __init__(self, project: Project, history: HistoryStack) -> None:
        super().__init__()
        self.setObjectName("PropertiesPanel")
        self.setStyleSheet(PROPERTIES_STYLE)

        self.project: Project = project
        self.history: HistoryStack = history
        self.current_node_id: str | None = None
        self.property_widgets: dict[str, PropertyWidget] = {}
        self.keyframe_buttons: dict[str, KeyframeButtonWidget] = {}
        self._probe_thread: MediaProbeThread | None = None
        self._probe_generation: int = 0
        self._widget_host_factory: Callable[[WidgetContext], WidgetHost] | None = None

        root: QVBoxLayout = QVBoxLayout(self)
        root.setContentsMargins(5, 5, 5, 5)
        root.setSpacing(0)

        self._scroll: QScrollArea = QScrollArea()
        self._scroll.setObjectName("PropertiesScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)

        self._content: QWidget = QWidget()
        self._content.setObjectName("PropertiesContent")
        self._content_layout: QVBoxLayout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(3)
        self._scroll.setWidget(self._content)

        self.project.subscribe(self.on_project_changed)
        self._show_empty_state("Select a node")

    def set_widget_host_factory(
        self,
        factory: Callable[[WidgetContext], WidgetHost],
    ) -> None:
        """Inject the editor host used for plugin-attached inspector widgets."""
        self._widget_host_factory = factory

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
            return
        if event == ObserverEvent.FrameChanged:
            self._refresh_animated_editors()
            return
        if event in {
            ObserverEvent.ConnectionCreated,
            ObserverEvent.ConnectionRemoved,
        }:
            self._refresh_property_link_picker(data)

    def _refresh_property_link_picker(self, data: Any) -> None:
        """Refresh property pickers when a link/drive reference wire changes."""
        node_id = self.current_node_id
        if node_id is None:
            return
        node = self.project.nodes.get(node_id)
        if not isinstance(node, (PropertyLinkNode, PropertyDriveNode)):
            return
        if isinstance(data, Connection):
            reference_slot = (
                PROPERTY_DRIVE_TARGET_SLOT
                if isinstance(node, PropertyDriveNode)
                else PROPERTY_LINK_SOURCE_SLOT
            )
            reference_id = node_reference_id(self.project, node_id, reference_slot)
            feeds_owner = (
                data.input_node_id == node_id and data.input_slot == reference_slot
            )
            touches_reference = reference_id is not None and (
                data.output_node_id == reference_id
                or data.input_node_id == reference_id
            )
            if not feeds_owner and not touches_reference:
                return
        property_key = (
            PROPERTY_DRIVE_PROPERTY_KEY
            if isinstance(node, PropertyDriveNode)
            else PROPERTY_LINK_PROPERTY_KEY
        )
        editor = self.property_widgets.get(property_key)
        if isinstance(editor, NodePropertyChoiceWidget):
            editor.refresh_choices()

    def _refresh_animated_editors(self) -> None:
        """Repaint animated properties' live value and keyframe state.

        Runs on every playhead move, so this intentionally avoids rebuilding
        the panel (``set_node``) and only touches properties that actually
        carry a curve on the selected node.
        """
        node_id = self.current_node_id
        if node_id is None:
            return
        node = self.project.nodes.get(node_id)
        if node is None or not node.animated_properties:
            return
        for prop_name, curve in node.animated_properties.items():
            editor = self.property_widgets.get(prop_name)
            if editor is not None and not curve.is_empty:
                editor.set_value(curve.value_at(self.project.current_frame))
            self._refresh_keyframe_button(node, prop_name)

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
            "lift_color": "Lift (Shadows)",
            "gamma_color": "Gamma (Mids)",
            "gain_color": "Gain (Highlights)",
            "temperature": "Temperature",
            "tint": "Tint",
            "amount": "Mix",
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
        self._content_layout.setSpacing(3)
        self._scroll.setWidget(self._content)
        self.property_widgets.clear()
        self.keyframe_buttons.clear()
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

        node: Node | None = self.project.nodes.get(node_id)
        if node is None:
            self.current_node_id = None
            self._show_empty_state("Select a node")
            return

        self.current_node_id = node_id
        layout: QVBoxLayout = self._replace_content()
        self._add_node_header(layout, node)
        has_properties: bool = self._add_property_rows(layout, node)
        has_plugin_ui: bool = self._add_plugin_property_panel(layout, node)
        if not has_properties and not has_plugin_ui:
            empty: QLabel = QLabel("No properties")
            empty.setObjectName("PropertiesEmptyLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
        self._add_tracking_controls(layout, node)
        layout.addStretch(1)

    def _add_node_header(self, layout: QVBoxLayout, node: Node) -> None:
        """Add compact node identity and category details."""
        title: QLabel = QLabel(node.name)
        title.setObjectName("PropertiesNodeTitle")
        title.setToolTip(node.node_description)
        layout.addWidget(title)

        meta: QLabel = QLabel(f"{node.node_category}  ·  {node.node_type}")
        meta.setObjectName("PropertiesNodeMeta")
        meta.setToolTip(node.node_description)
        layout.addWidget(meta)

        divider: QFrame = QFrame()
        divider.setObjectName("PropertiesDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

    def _add_property_rows(self, layout: QVBoxLayout, node: Node) -> bool:
        """Create grouped rows for every visible property."""
        node_id = self.current_node_id
        if node_id is None:
            return False
        has_properties: bool = False
        ordered: list[tuple[str, NodeProperty]] = self._ordered_properties(node)
        current_group: str | None = None
        for prop_name, prop in ordered:
            if prop_name.startswith("_input_"):
                continue
            editor: PropertyWidget | None = self._create_property_widget(
                prop,
                prop_name,
                self.current_node_id or "",
            )
            if editor is None:
                continue
            if prop.group != current_group:
                current_group = prop.group
                section: QLabel = QLabel(current_group.upper())
                section.setObjectName("PropertySectionLabel")
                layout.addWidget(section)
            has_properties = True
            self.property_widgets[prop_name] = editor
            self._wire_editor(prop_name, editor)
            keyframe_button = self._build_keyframe_button(node, prop_name, prop)
            row: PropertyRow = PropertyRow(
                prop.label or self._format_property_name(prop_name),
                editor,
                prop.description,
                keyframe_button=keyframe_button,
                full_width=isinstance(editor, EqCurvePropertyWidget),
            )
            layout.addWidget(row)
        return has_properties

    def _add_plugin_property_panel(self, layout: QVBoxLayout, node: Node) -> bool:
        """Embed a plugin-attached inspector section when the node provides one."""
        if self._widget_host_factory is None or self.current_node_id is None:
            return False
        host = self._widget_host_factory(
            WidgetContext(
                plugin_key=plugin_registry_key(type(node)),
                node_id=self.current_node_id,
                project_name=self.project.name,
            )
        )
        native = _realize_property_qt_widget(node, host, self)
        if native is None:
            builder = getattr(node, "build_property_panel", None)
            if builder is None:
                return False
            view: WidgetView | None = _safe_build_property_panel(builder, host)
            native = _native_plugin_widget(view)
        if native is None:
            return False
        section: QLabel = QLabel("PLUGIN")
        section.setObjectName("PropertySectionLabel")
        layout.addWidget(section)
        layout.addWidget(native)
        return True

    def _build_keyframe_button(
        self,
        node: Node,
        prop_name: str,
        prop: NodeProperty,
    ) -> KeyframeButtonWidget | None:
        """Create a wired keyframe toggle for animatable properties, or ``None``."""
        if prop.input_type not in _ANIMATABLE_INPUT_TYPES:
            return None
        button = KeyframeButtonWidget()
        button.toggled_keyframe.connect(
            lambda p=prop_name: self.toggle_keyframe(p)
        )
        self.keyframe_buttons[prop_name] = button
        self._refresh_keyframe_button(node, prop_name)
        return button

    def _refresh_keyframe_button(self, node: Node, prop_name: str) -> None:
        """Sync one keyframe button's visual state with the model."""
        button = self.keyframe_buttons.get(prop_name)
        if button is None:
            return
        curve = node.animated_properties.get(prop_name)
        is_animated = curve is not None and not curve.is_empty
        is_keyed = is_animated and curve.has_keyframe_at(self.project.current_frame)
        button.set_state(is_keyed=is_keyed, is_animated=is_animated)

    def _resolved_property_value(self, node: Node, prop_name: str) -> Any:
        """Return the property's value at the current frame (curve-aware)."""
        prop = node.get_property(prop_name)
        if prop is None:
            return None
        curve = node.animated_properties.get(prop_name)
        if curve is not None and not curve.is_empty:
            return curve.value_at(self.project.current_frame)
        return prop.value

    def toggle_keyframe(self, prop_name: str) -> None:
        """Add or remove a keyframe for ``prop_name`` at the current frame."""
        node_id = self.current_node_id
        if node_id is None or node_id not in self.project.nodes:
            return
        node = self.project.nodes[node_id]
        frame = self.project.current_frame
        curve: AnimationCurve | None = node.animated_properties.get(prop_name)
        if curve is not None and curve.has_keyframe_at(frame):
            self.history.push(RemoveKeyframeCommand(node_id, prop_name, frame))
        else:
            value = self._resolved_property_value(node, prop_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return
            self.history.push(
                SetKeyframeCommand(node_id, prop_name, frame, float(value))
            )
        self._refresh_keyframe_button(node, prop_name)

    def _add_tracking_controls(self, layout: QVBoxLayout, node: Node) -> None:
        """Add Track Forward/Backward/Clear buttons for tracker nodes."""
        if not isinstance(node, (TrackerNode, PlanarTrackerNode)):
            return
        section: QLabel = QLabel("TRACK")
        section.setObjectName("PropertySectionLabel")
        layout.addWidget(section)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        backward_button = QPushButton("◄ Backward")
        forward_button = QPushButton("Forward ►")
        clear_button = QPushButton("Clear")
        backward_button.clicked.connect(lambda: self._run_tracking(node, direction=-1))
        forward_button.clicked.connect(lambda: self._run_tracking(node, direction=1))
        clear_button.clicked.connect(lambda: self._clear_tracking(node))
        row_layout.addWidget(backward_button)
        row_layout.addWidget(forward_button)
        row_layout.addWidget(clear_button)
        layout.addWidget(row)

    def _run_tracking(self, node: Node, *, direction: int) -> None:
        """Track ``node`` forward or backward from the current frame.

        Runs synchronously (via a modal progress dialog) and writes the
        result through an undoable command on success.
        """
        node_id = self.current_node_id
        if node_id is None:
            return
        start = self.project.current_frame
        end = self.project.max_frame if direction > 0 else 0
        frame_numbers = (
            list(range(start, end + 1))
            if direction > 0
            else list(range(start, end - 1, -1))
        )
        if len(frame_numbers) < 2:
            QMessageBox.information(
                self, "Tracking", "Nothing to track from the current frame."
            )
            return

        # Deferred import: ``ui.dialogs`` transitively imports this module
        # (via ``ui.widgets`` re-exports), so importing it at module scope
        # here would create a circular import.
        from ui.dialogs import TrackingProgressDialog

        request = TrackingRequest(
            node_id=node_id,
            frame_numbers=frame_numbers,
            region_size=node.region_size_normalized(),
            search_radius=node.search_radius_normalized(),
        )
        if isinstance(node, PlanarTrackerNode):
            self._run_planar_tracking(node_id, node, request, TrackingProgressDialog)
        else:
            self._run_point_tracking(node_id, node, request, TrackingProgressDialog)

    def _run_point_tracking(
        self,
        node_id: str,
        node: TrackerNode,
        request: TrackingRequest,
        dialog_cls: type,
    ) -> None:
        """Run a ``TrackerNode`` job and commit the result on success."""
        worker = PointTrackingWorker(self.project, request, node.seed_position())
        dialog = dialog_cls(worker, title=f"Tracking {node.name}", parent=self)
        if not dialog.run_modal():
            if dialog.error:
                QMessageBox.warning(self, "Tracking Failed", dialog.error)
            return
        curve_x, curve_y = _split_xy_curves(dialog.result or {})
        self.history.push(SetTrackCommand(node_id, curve_x, curve_y))
        self._reload_current_node()

    def _run_planar_tracking(
        self,
        node_id: str,
        node: PlanarTrackerNode,
        request: TrackingRequest,
        dialog_cls: type,
    ) -> None:
        """Run a ``PlanarTrackerNode`` job and commit the result on success."""
        worker = PlanarTrackingWorker(self.project, request, node.seed_corners())
        dialog = dialog_cls(worker, title=f"Tracking {node.name}", parent=self)
        if not dialog.run_modal():
            if dialog.error:
                QMessageBox.warning(self, "Tracking Failed", dialog.error)
            return
        raw = dialog.result or {}
        corner_curves = {
            corner: _split_xy_curves(raw.get(corner, {}))
            for corner in ("top_left", "top_right", "bottom_right", "bottom_left")
        }
        self.history.push(SetPlanarTrackCommand(node_id, corner_curves))
        self._reload_current_node()

    def _clear_tracking(self, node: Node) -> None:
        """Remove all tracked keyframes from a tracker node."""
        node_id = self.current_node_id
        if node_id is None:
            return
        if isinstance(node, TrackerNode):
            self.history.push(
                SetTrackCommand(node_id, AnimationCurve(), AnimationCurve())
            )
        elif isinstance(node, PlanarTrackerNode):
            empty_curves = {
                corner: (AnimationCurve(), AnimationCurve())
                for corner in ("top_left", "top_right", "bottom_right", "bottom_left")
            }
            self.history.push(SetPlanarTrackCommand(node_id, empty_curves))
        self._reload_current_node()

    @staticmethod
    def _ordered_properties(node: Node) -> list[tuple[str, NodeProperty]]:
        """Keep groups contiguous while respecting their first priority."""
        by_priority: list[tuple[str, NodeProperty]] = sorted(
            node.properties.items(),
            key=lambda item: (item[1].priority, item[0]),
        )
        group_order: dict[str, int] = {}
        for _name, prop in by_priority:
            if prop.group not in group_order:
                group_order[prop.group] = len(group_order)
        return sorted(
            by_priority,
            key=lambda item: (
                group_order[item[1].group],
                item[1].priority,
                item[0],
            ),
        )

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
        elif isinstance(editor, NodePropertyChoiceWidget):
            editor.combo.currentIndexChanged.connect(
                lambda _i, p=prop_name, w=editor: self.update_property(p, w.get_value())
            )
        elif isinstance(editor, TextPropertyWidget):
            editor.line_edit.editingFinished.connect(
                lambda p=prop_name, w=editor: self.update_property(p, w.get_value())
            )
        elif isinstance(editor, ColorPropertyWidget):
            editor.color_changed.connect(
                lambda rgb, p=prop_name: self.update_property(p, rgb)
            )
        elif isinstance(editor, EqCurvePropertyWidget):
            editor.value_changed.connect(
                lambda value, p=prop_name: self.update_property(p, value)
            )
        elif isinstance(editor, CustomPropertyWidget):
            editor.edit_requested.connect(
                lambda p=prop_name: self._emit_custom_editor(p)
            )

    def _create_property_widget(
        self,
        prop: NodeProperty,
        prop_name: str,
        node_id: str,
    ) -> PropertyWidget | None:
        node = self.project.nodes.get(node_id)
        if prop.input_type == NodePropertyInputType.NodePropertyChoice:
            reference_slot = PROPERTY_LINK_SOURCE_SLOT
            if isinstance(node, PropertyDriveNode):
                reference_slot = PROPERTY_DRIVE_TARGET_SLOT
            elif not isinstance(node, PropertyLinkNode):
                return None
            return NodePropertyChoiceWidget(
                prop,
                self.project,
                node_id,
                reference_slot,
            )
        if (
            prop_name == PROPERTY_LINK_PROPERTY_KEY
            and isinstance(node, PropertyLinkNode)
        ):
            return NodePropertyChoiceWidget(
                prop,
                self.project,
                node_id,
                PROPERTY_LINK_SOURCE_SLOT,
            )
        if (
            prop_name == PROPERTY_DRIVE_PROPERTY_KEY
            and isinstance(node, PropertyDriveNode)
        ):
            return NodePropertyChoiceWidget(
                prop,
                self.project,
                node_id,
                PROPERTY_DRIVE_TARGET_SLOT,
            )
        if prop.input_type in (
            NodePropertyInputType.File,
            NodePropertyInputType.ImageFile,
        ):
            return FilePropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Text:
            return TextPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Slider:
            return SliderPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Number:
            return NumberPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Checkbox:
            return CheckboxPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Color:
            return ColorPropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.VideoFrameErrorMethod:
            return EnumPropertyWidget(prop, VideoFrameErrorMethod)
        if prop.input_type == NodePropertyInputType.CustomChoice:
            if not isinstance(prop.value, Enum):
                return None
            return EnumPropertyWidget(prop, type(prop.value))
        if prop_name == "eq_curve":
            return EqCurvePropertyWidget(prop)
        if prop.input_type == NodePropertyInputType.Custom:
            return CustomPropertyWidget(prop)
        return None

    def _emit_custom_editor(self, prop_name: str) -> None:
        """Ask the editor to open the dialog widget attached to this plugin."""
        if self.current_node_id is None:
            return
        node = self.project.nodes.get(self.current_node_id)
        if node is None:
            return
        prop = node.get_property(prop_name)
        if prop is None or not prop.custom_widget_id:
            return
        self.custom_editor_requested.emit(
            self.current_node_id,
            prop_name,
            prop.custom_widget_id,
        )

    def update_property(self, prop_name: str, value: Any) -> None:
        """Write a property value through history (coalesces rapid edits)."""
        if (
            self.current_node_id is None
            or self.current_node_id not in self.project.nodes
        ):
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

        if prop.input_type == NodePropertyInputType.Color:
            value = coerce_color_rgb(value)

        node_id = self.current_node_id
        curve = node.animated_properties.get(prop_name)
        if curve is not None and not curve.is_empty:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return
            frame = self.project.current_frame
            if not self.history.push(
                SetKeyframeCommand(node_id, prop_name, frame, float(value))
            ):
                return
            self._refresh_keyframe_button(node, prop_name)
            return

        if prop.value == value:
            return

        if not self.history.push(
            SetPropertyCommand(node_id, prop_name, value, old_value=prop.value)
        ):
            return

        if prop_name == "file_path" and isinstance(node, VideoInputNode):
            self._start_media_probe(str(value), node_id)

    def _start_media_probe(self, path: str, node_id: str) -> None:
        if not path:
            return
        self.shutdown()
        self._probe_generation += 1
        generation = self._probe_generation
        thread = MediaProbeThread(path, parent=self)
        thread.probed.connect(
            lambda fps, dur, w, h, frame_count, gen=generation, nid=node_id: self._on_probe_ok(
                gen, nid, fps, dur, w, h, frame_count
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
        frame_count: int,
    ) -> None:
        if generation != self._probe_generation:
            return
        node = self.project.nodes.get(node_id)
        sync_prop = (
            node.get_property("auto_sync_timeline") if node is not None else None
        )
        should_sync = sync_prop is None or bool(sync_prop.value)
        if should_sync:
            # sync_timeline_from_media clears cache and emits FrameChanged.
            self.project.sync_timeline_from_media(
                fps=fps,
                duration_sec=duration_sec,
                width=width,
                height=height,
                frame_count=frame_count,
            )
        self.project.invalidate_cache(node_id)

    def _on_probe_failed(self, generation: int, node_id: str, message: str) -> None:
        if generation != self._probe_generation:
            return
        _ = message
        self.project.invalidate_cache(node_id)

    def shutdown(self) -> None:
        """Stop any in-flight media probe before application exit."""
        thread: MediaProbeThread | None = self._probe_thread
        self._probe_thread = None
        if thread is None:
            return
        thread.requestInterruption()
        if not thread.wait(1000):
            thread.terminate()
            thread.wait(500)

    def browse_file(self, prop_name: str, widget: FilePropertyWidget) -> None:
        is_image = widget.prop.input_type == NodePropertyInputType.ImageFile
        caption = "Select an image file" if is_image else "Select a video file"
        file_filter = (
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All Files (*)"
            if is_image
            else "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(self, caption, "", file_filter)
        if file_path:
            widget.set_value(file_path)
            self.update_property(prop_name, file_path)


def _safe_build_property_panel(
    builder: Callable[[WidgetHost], WidgetView | None],
    host: WidgetHost,
) -> WidgetView | None:
    """Call ``builder`` and swallow construction errors."""
    try:
        return builder(host)
    except Exception:  # noqa: BLE001
        return None


def _realize_property_qt_widget(
    node: Node,
    host: WidgetHost,
    parent: QWidget,
) -> QWidget | None:
    """Return ``build_property_qt_widget`` when it yields a QWidget."""
    builder = getattr(node, "build_property_qt_widget", None)
    if not callable(builder):
        return None
    try:
        built = builder(parent, host)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(built, QWidget):
        return built
    return None


def _native_plugin_widget(view: WidgetView | None) -> QWidget | None:
    """Return the Qt widget for a plugin inspector view."""
    if view is None:
        return None
    getter = getattr(view, "native_widget", None)
    if not callable(getter):
        return None
    widget = getter()
    if isinstance(widget, QWidget):
        return widget
    return None
