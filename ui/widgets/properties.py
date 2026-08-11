"""
Properties panel for node parameter editing with advanced controls
"""

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.events import ObserverEvent
from core.nodes import (
    NodeProperty,
    NodePropertyInputType,
    VideoFrameErrorMethod,
    VideoInputNode,
)
from core.project import Project


class PropertyWidget(QWidget):
    """Base class for property input widgets"""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.prop = prop
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)
        self.setLayout(self.layout)

    def get_value(self) -> Any:
        """Get the current value from the widget"""
        raise NotImplementedError

    def set_value(self, value: Any) -> None:
        """Set the value in the widget"""
        raise NotImplementedError


class NumberPropertyWidget(PropertyWidget):
    """Widget for number properties"""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)

        self.spinbox = QDoubleSpinBox()
        self.spinbox.setValue(float(prop.value or 0))
        self.spinbox.setRange(-999999, 999999)
        self.spinbox.setDecimals(2)
        self.spinbox.setSingleStep(0.1)
        self.spinbox.setMinimumHeight(28)
        self.spinbox.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 10px;
                font-weight: 500;
            }
            QDoubleSpinBox:focus {
                border: 1px solid #0078d4;
                background-color: #313131;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background-color: #2a2a2a;
                border: none;
                width: 16px;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #353535;
            }
        """)

        self.layout.addWidget(self.spinbox)

    def get_value(self) -> Any:
        return self.spinbox.value()

    def set_value(self, value: Any) -> None:
        self.spinbox.setValue(float(value or 0))


class SliderPropertyWidget(PropertyWidget):
    """Widget for slider properties"""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(prop.slider_min_value or 0))
        self.slider.setMaximum(int(prop.slider_max_value or 100))
        self.slider.setValue(int(prop.value or 0))
        self.slider.setMinimumHeight(28)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #3a3a3a;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background-color: #0078d4;
                width: 12px;
                margin: -4px 0px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background-color: #0084db;
            }
        """)

        self.value_label = QLabel(str(int(prop.value or 0)))
        self.value_label.setStyleSheet(
            "color: #0078d4; font-weight: bold; font-size: 9px; min-width: 30px;"
        )
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slider.valueChanged.connect(lambda v: self.value_label.setText(str(v)))

        self.layout.addWidget(self.slider, 1)
        self.layout.addWidget(self.value_label)

    def get_value(self) -> Any:
        return self.slider.value()

    def set_value(self, value: Any) -> None:
        self.slider.setValue(int(value or 0))


class FilePropertyWidget(PropertyWidget):
    """Widget for file path properties"""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)

        self.file_input = QLineEdit()
        self.file_input.setText(str(prop.value or ""))
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText("No file")
        self.file_input.setMinimumHeight(28)
        self.file_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: #888888;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 9px;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
                color: #ffffff;
            }
        """)

        self.browse_btn = QPushButton("…")
        self.browse_btn.setMaximumWidth(30)
        self.browse_btn.setMinimumHeight(28)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: #ffffff;
                border: none;
                border-radius: 3px;
                padding: 2px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #0084db;
            }
            QPushButton:pressed {
                background-color: #006abb;
            }
        """)

        self.layout.addWidget(self.file_input, 1)
        self.layout.addWidget(self.browse_btn)

    def get_value(self) -> Any:
        return self.file_input.text()

    def set_value(self, value: Any) -> None:
        self.file_input.setText(str(value or ""))

    def get_browse_button(self) -> QPushButton:
        return self.browse_btn


class EnumPropertyWidget(PropertyWidget):
    """Widget for enum properties"""

    def __init__(
        self, prop: NodeProperty, enum_class: Any, parent: QWidget | None = None
    ) -> None:
        super().__init__(prop, parent)

        self.enum_class = enum_class
        self.combo = QComboBox()
        self.combo.setMinimumHeight(28)

        # Populate combo box with enum values
        for member in enum_class:
            self.combo.addItem(member.name, member.value)

        # Set current value
        if prop.value:
            index = self.combo.findData(prop.value)
            if index >= 0:
                self.combo.setCurrentIndex(index)

        self.combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 10px;
                font-weight: 500;
            }
            QComboBox:focus {
                border: 1px solid #0078d4;
                background-color: #313131;
            }
            QComboBox::drop-down {
                border: none;
                background-color: #2a2a2a;
                width: 16px;
            }
            QComboBox::down-arrow {
                image: url(none);
                width: 0px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e;
                color: #ffffff;
                selection-background-color: #0078d4;
                border: 1px solid #444444;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 4px 6px;
                height: 26px;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #0078d4;
            }
        """)

        self.layout.addWidget(self.combo)

    def get_value(self) -> Any:
        return self.combo.currentData()

    def set_value(self, value: Any) -> None:
        index = self.combo.findData(value)
        if index >= 0:
            self.combo.setCurrentIndex(index)


class PropertiesPanel(QWidget):
    """Edit selected node properties with advanced controls"""

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self.current_node_id = None
        self.property_widgets: dict[str, PropertyWidget] = {}

        # Set dark background
        self.setStyleSheet("""
            PropertiesPanel {
                background-color: #1e1e1e;
            }
        """)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)
        self.setLayout(main_layout)

        # Scroll area for properties
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(280)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1e1e1e;
            }
            QScrollBar:vertical {
                width: 8px;
                background-color: #1e1e1e;
            }
            QScrollBar::handle:vertical {
                background-color: #444444;
                border-radius: 4px;
                min-height: 40px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #555555;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)

        # Container for properties
        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("background-color: #1e1e1e;")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(8)

        scroll.setWidget(self.scroll_widget)
        main_layout.addWidget(scroll)

        self.project.subscribe(self.on_project_changed)

        # Default message
        label = QLabel("Select a node")
        label.setStyleSheet("color: #555555; font-style: italic; font-size: 10px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_layout.addWidget(label)
        self.scroll_layout.addStretch()

    def on_project_changed(self, event: ObserverEvent, data: Any) -> None:
        """Handle project changes"""
        pass

    def _format_property_name(self, name: str) -> str:
        """Format property name from snake_case to Title Case"""
        # Remove leading underscores if any
        name = name.lstrip("_")
        # Replace underscores with spaces
        name = name.replace("_", " ")
        # Title case each word
        return name.title()

    def set_node(self, node_id: str) -> None:
        """Display properties for a specific node"""
        # If same node, don't refresh
        if self.current_node_id == node_id:
            return

        self.current_node_id = node_id
        self.property_widgets.clear()

        node = self.project.nodes.get(node_id)

        if not node:
            return

        # Completely clear layout
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                layout = item.layout()
                if layout is not None:
                    layout.deleteLater()

        # Add node name header
        name_label = QLabel(node.name)
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet(
            "color: #ffffff; padding-bottom: 4px; padding-top: 2px;"
        )
        self.scroll_layout.addWidget(name_label)

        # Add separator
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #333333; margin-bottom: 6px;")
        self.scroll_layout.addWidget(separator)

        # Create form for properties
        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        has_properties = False

        for prop_name, prop in sorted(node.properties.items()):
            # Skip internal properties
            if prop_name.startswith("_input_"):
                continue

            if not isinstance(prop, NodeProperty):
                continue

            has_properties = True

            # Property label with formatted name
            formatted_name = self._format_property_name(prop_name)
            label = QLabel(formatted_name)
            label.setStyleSheet("""
                color: #b0b0b0;
                font-weight: 600;
                font-size: 9px;
            """)
            label.setMinimumWidth(60)
            label.setMaximumWidth(100)

            # Create appropriate widget based on input type
            widget = self._create_property_widget(prop, prop_name)

            if widget:
                self.property_widgets[prop_name] = widget
                # Connect value changes
                if hasattr(widget, "spinbox"):
                    widget.spinbox.valueChanged.connect(
                        lambda v, p=prop_name: self.update_property(p, v)
                    )
                elif hasattr(widget, "slider"):
                    widget.slider.valueChanged.connect(
                        lambda v, p=prop_name: self.update_property(p, v)
                    )
                elif hasattr(widget, "combo"):
                    widget.combo.currentIndexChanged.connect(
                        lambda _, p=prop_name: self.update_property(
                            p, widget.get_value()
                        )
                    )

                form.addRow(label, widget)

        if has_properties:
            self.scroll_layout.addLayout(form)
        else:
            no_props = QLabel("No properties")
            no_props.setStyleSheet(
                "color: #555555; font-style: italic; font-size: 9px;"
            )
            no_props.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scroll_layout.addWidget(no_props)

        self.scroll_layout.addStretch()

    def _create_property_widget(
        self, prop: NodeProperty, prop_name: str
    ) -> PropertyWidget | None:
        """Create appropriate widget based on property type"""

        if prop.input_type == NodePropertyInputType.File:
            widget = FilePropertyWidget(prop)
            widget.get_browse_button().clicked.connect(
                lambda: self.browse_file(prop_name, widget)
            )
            return widget

        elif prop.input_type == NodePropertyInputType.Slider:
            return SliderPropertyWidget(prop)

        elif prop.input_type == NodePropertyInputType.Number:
            return NumberPropertyWidget(prop)

        elif prop.input_type == NodePropertyInputType.VideoFrameErrorMethod:
            return EnumPropertyWidget(prop, VideoFrameErrorMethod)

        elif prop.input_type == NodePropertyInputType.CustomChoice:
            return EnumPropertyWidget(prop, type(prop.value))

        return None

    def update_property(self, prop_name: str, value: Any) -> None:
        """Update a node property and sync media metadata when needed."""
        if not self.current_node_id or self.current_node_id not in self.project.nodes:
            return
        node = self.project.nodes[self.current_node_id]
        prop = node.get_property(prop_name)
        if prop is None:
            return
        prop.value = value
        self.project.invalidate_cache(self.current_node_id)
        if prop_name == "file_path" and isinstance(node, VideoInputNode):
            self._sync_video_media(node)

    def _sync_video_media(self, node: VideoInputNode) -> None:
        """Align project fps/duration/size with the selected video file."""
        meta = node.probe_media()
        if meta is None:
            return
        fps, duration_sec, width, height = meta
        self.project.sync_timeline_from_media(
            fps=fps,
            duration_sec=duration_sec,
            width=width,
            height=height,
        )

    def browse_file(self, prop_name: str, widget: FilePropertyWidget) -> None:
        """Open file browser for file properties"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a video file",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)",
        )

        if file_path:
            widget.set_value(file_path)
            self.update_property(prop_name, file_path)
