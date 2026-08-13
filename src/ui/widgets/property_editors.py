"""Compact reusable editors for typed node properties."""

from __future__ import annotations

from enum import Enum
from typing import Any

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPalette, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from core.nodes import NEUTRAL_COLOR_RGB, NodeProperty
from core.nodes.base import ColorRgb
from core.project import Project

CONTROL_HEIGHT_PX: int = 24
SLIDER_HEIGHT_PX: int = 26
PROPERTY_LABEL_WIDTH_PX: int = 88


class PropertyWidget(QWidget):
    """Base class for one property value editor."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Initialize shared property metadata and row layout."""
        super().__init__(parent)
        self.prop: NodeProperty = prop
        self.setToolTip(prop.description)
        self._row: QHBoxLayout = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)

    def get_value(self) -> Any:
        """Return the current editor value."""
        raise NotImplementedError

    def set_value(self, value: Any) -> None:
        """Replace the current editor value."""
        raise NotImplementedError


class NumberPropertyWidget(PropertyWidget):
    """Integer or floating-point spin box."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build a spin box matching the property's numeric kind."""
        super().__init__(prop, parent)
        self._is_int: bool = isinstance(prop.value, int)
        low: float = float(prop.slider_min_value)
        high: float = float(prop.slider_max_value)
        if high <= low:
            low, high = -999999.0, 999999.0
        self.spinbox: QSpinBox | QDoubleSpinBox = self._build_spin(prop, low, high)
        self._row.addWidget(self.spinbox, 1)

    def _build_spin(
        self,
        prop: NodeProperty,
        low: float,
        high: float,
    ) -> QSpinBox | QDoubleSpinBox:
        """Construct and configure an integer or decimal spin box."""
        if self._is_int:
            spin: QSpinBox | QDoubleSpinBox = QSpinBox()
            spin.setRange(int(low), int(high))
            spin.setValue(int(prop.value or 0))
        else:
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setValue(float(prop.value or 0.0))
        spin.setObjectName("PropertySpin")
        spin.setFixedHeight(CONTROL_HEIGHT_PX)
        spin.setSuffix(prop.suffix)
        return spin

    def get_value(self) -> int | float:
        """Return the numeric value."""
        if self._is_int:
            return int(self.spinbox.value())
        return float(self.spinbox.value())

    def set_value(self, value: Any) -> None:
        """Set the numeric value without re-emitting ``valueChanged``.

        Signals are blocked so programmatic refreshes (e.g. scrubbing an
        animated property to a new frame) never re-enter ``update_property``.
        """
        self.spinbox.blockSignals(True)
        if isinstance(self.spinbox, QSpinBox):
            self.spinbox.setValue(int(value or 0))
        else:
            self.spinbox.setValue(float(value or 0.0))
        self.spinbox.blockSignals(False)


class SliderPropertyWidget(PropertyWidget):
    """Horizontal integer slider with compact value readout."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build a bounded slider and suffix-aware value readout."""
        super().__init__(prop, parent)
        self.slider: QSlider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("PropertySlider")
        self.slider.setRange(
            int(prop.slider_min_value or 0),
            int(prop.slider_max_value or 100),
        )
        self.slider.setValue(int(prop.value or 0))
        self.slider.setFixedHeight(SLIDER_HEIGHT_PX)
        self.value_label: QLabel = QLabel()
        self.value_label.setObjectName("PropertySliderValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slider.valueChanged.connect(self._update_label)
        self._update_label(self.slider.value())
        self._row.addWidget(self.slider, 1)
        self._row.addWidget(self.value_label)

    def _update_label(self, value: int) -> None:
        """Refresh the compact value readout."""
        self.value_label.setText(f"{value}{self.prop.suffix}")

    def get_value(self) -> int:
        """Return the slider value."""
        return int(self.slider.value())

    def set_value(self, value: Any) -> None:
        """Set the slider value without re-emitting ``valueChanged``."""
        self.slider.blockSignals(True)
        self.slider.setValue(int(value or 0))
        self._update_label(self.slider.value())
        self.slider.blockSignals(False)


class FilePropertyWidget(PropertyWidget):
    """Read-only path field with browse button."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build the path display and browse action."""
        super().__init__(prop, parent)
        self.file_input: QLineEdit = QLineEdit()
        self.file_input.setObjectName("PropertyField")
        self.file_input.setText(str(prop.value or ""))
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText("No file selected")
        self.file_input.setFixedHeight(CONTROL_HEIGHT_PX)
        self.browse_btn: QPushButton = QPushButton("…")
        self.browse_btn.setObjectName("PropertyBrowseButton")
        self.browse_btn.setFixedHeight(CONTROL_HEIGHT_PX)
        self._row.addWidget(self.file_input, 1)
        self._row.addWidget(self.browse_btn)

    def get_value(self) -> str:
        """Return the selected path."""
        return self.file_input.text()

    def set_value(self, value: Any) -> None:
        """Set the displayed path."""
        self.file_input.setText(str(value or ""))

    def get_browse_button(self) -> QPushButton:
        """Return the browse action button."""
        return self.browse_btn


class TextPropertyWidget(PropertyWidget):
    """Single-line editable text field."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build an editable line edit seeded with the property's text."""
        super().__init__(prop, parent)
        self.line_edit: QLineEdit = QLineEdit()
        self.line_edit.setObjectName("PropertyField")
        self.line_edit.setText(str(prop.value or ""))
        self.line_edit.setFixedHeight(CONTROL_HEIGHT_PX)
        self._row.addWidget(self.line_edit, 1)

    def get_value(self) -> str:
        """Return the current text."""
        return self.line_edit.text()

    def set_value(self, value: Any) -> None:
        """Set the displayed text without re-emitting ``editingFinished``."""
        self.line_edit.blockSignals(True)
        self.line_edit.setText(str(value or ""))
        self.line_edit.blockSignals(False)


class EnumPropertyWidget(PropertyWidget):
    """Dropdown for enum-backed properties."""

    def __init__(
        self,
        prop: NodeProperty,
        enum_class: type[Enum],
        parent: QWidget | None = None,
    ) -> None:
        """Populate a dropdown from ``enum_class``."""
        super().__init__(prop, parent)
        self.enum_class: type[Enum] = enum_class
        self.combo: QComboBox = QComboBox()
        self.combo.setObjectName("PropertyCombo")
        self.combo.setFixedHeight(CONTROL_HEIGHT_PX)
        for member in enum_class:
            self.combo.addItem(_enum_label(member), member)
        self.set_value(prop.value)
        self._row.addWidget(self.combo, 1)

    def get_value(self) -> Enum | None:
        """Return the selected enum member."""
        value: object = self.combo.currentData()
        return value if isinstance(value, Enum) else None

    def set_value(self, value: Any) -> None:
        """Select the matching enum member."""
        index: int = self.combo.findData(value)
        if index < 0 and isinstance(value, int):
            try:
                index = self.combo.findData(self.enum_class(value))
            except ValueError:
                return
        if index >= 0:
            self.combo.setCurrentIndex(index)


class NodePropertyChoiceWidget(PropertyWidget):
    """Dropdown of numeric properties on a wired source/target node."""

    def __init__(
        self,
        prop: NodeProperty,
        project: Project,
        owner_node_id: str,
        reference_slot: str,
        parent: QWidget | None = None,
    ) -> None:
        """Build a property picker bound to the owner's reference wire."""
        super().__init__(prop, parent)
        self.project: Project = project
        self.owner_node_id: str = owner_node_id
        self.reference_slot: str = reference_slot
        self.combo: QComboBox = QComboBox()
        self.combo.setObjectName("PropertyCombo")
        self.combo.setFixedHeight(CONTROL_HEIGHT_PX)
        self._row.addWidget(self.combo, 1)
        self.refresh_choices()
        self.set_value(prop.value)

    def refresh_choices(self) -> None:
        """Rebuild options from the currently connected reference node."""
        from core.nodes.property_link import (
            linkable_properties,
            node_reference_id,
            property_link_label,
        )

        current: str = str(self.combo.currentData() or "")
        self.combo.blockSignals(True)
        self.combo.clear()
        source_id = node_reference_id(
            self.project,
            self.owner_node_id,
            self.reference_slot,
        )
        if source_id is None:
            self.combo.addItem("Connect a node…", "")
            self.combo.setEnabled(False)
            self.combo.blockSignals(False)
            return

        source = self.project.nodes.get(source_id)
        if source is None:
            self.combo.addItem("Source node missing", "")
            self.combo.setEnabled(False)
            self.combo.blockSignals(False)
            return

        self.combo.setEnabled(True)
        options = linkable_properties(source)
        if not options:
            self.combo.addItem("No numeric properties", "")
        else:
            for key, node_prop in options:
                self.combo.addItem(property_link_label(node_prop, key), key)

        index = self.combo.findData(current)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        elif self.combo.count() > 0:
            self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

    def get_value(self) -> str:
        """Return the selected property key."""
        value: object = self.combo.currentData()
        return str(value or "")

    def set_value(self, value: Any) -> None:
        """Select a property key when present in the current option list."""
        index: int = self.combo.findData(str(value or ""))
        if index >= 0:
            self.combo.setCurrentIndex(index)


class CheckboxPropertyWidget(PropertyWidget):
    """Compact boolean toggle."""

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build a checkbox reflecting the current property value."""
        super().__init__(prop, parent)
        self.checkbox: QCheckBox = QCheckBox()
        self.checkbox.setObjectName("PropertyCheck")
        self.checkbox.setChecked(bool(prop.value))
        self.checkbox.setFixedHeight(CONTROL_HEIGHT_PX)
        self._row.addWidget(self.checkbox)
        self._row.addStretch(1)

    def get_value(self) -> bool:
        """Return the toggle state."""
        return bool(self.checkbox.isChecked())

    def set_value(self, value: Any) -> None:
        """Set the toggle state without emitting."""
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(bool(value))
        self.checkbox.blockSignals(False)


class ColorSwatch(QWidget):
    """Clickable color chip."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the clickable palette-backed swatch."""
        super().__init__(parent)
        self.setObjectName("PropertyColorSwatch")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Choose color")
        self.setAutoFillBackground(True)
        self.setFixedSize(32, CONTROL_HEIGHT_PX)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """Emit ``clicked`` for the primary mouse button."""
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(a0)


class ColorPropertyWidget(PropertyWidget):
    """RGB color chip and hexadecimal readout."""

    color_changed = pyqtSignal(object)

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build a swatch and hexadecimal color readout."""
        super().__init__(prop, parent)
        self._rgb: ColorRgb = coerce_color_rgb(prop.value)
        self.swatch: ColorSwatch = ColorSwatch()
        self.swatch.clicked.connect(self._pick_color)
        self.hex_label: QLabel = QLabel()
        self.hex_label.setObjectName("PropertyColorHex")
        self._row.addWidget(self.swatch)
        self._row.addWidget(self.hex_label, 1)
        self._apply_swatch()

    def get_value(self) -> ColorRgb:
        """Return the selected RGB tuple."""
        return self._rgb

    def set_value(self, value: Any) -> None:
        """Set and display an RGB tuple."""
        self._rgb = coerce_color_rgb(value)
        self._apply_swatch()

    def _pick_color(self) -> None:
        """Open the native color dialog and emit accepted changes."""
        initial: QColor = QColor(*self._rgb)
        chosen: QColor = QColorDialog.getColor(initial, self, "Select Color")
        if not chosen.isValid():
            return
        next_rgb: ColorRgb = (chosen.red(), chosen.green(), chosen.blue())
        if next_rgb != self._rgb:
            self._rgb = next_rgb
            self._apply_swatch()
            self.color_changed.emit(self._rgb)

    def _apply_swatch(self) -> None:
        """Apply the selected color through the widget palette."""
        red: int
        green: int
        blue: int
        red, green, blue = self._rgb
        palette: QPalette = self.swatch.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(red, green, blue))
        self.swatch.setPalette(palette)
        self.hex_label.setText(f"#{red:02X}{green:02X}{blue:02X}")


class KeyframeButtonWidget(QWidget):
    """Small diamond toggle marking a property's keyframe state at this frame.

    Hollow gray: never animated. Hollow gold outline: animated, but no
    keyframe sits exactly on the current frame. Solid gold: a keyframe is
    set on the current frame.
    """

    toggled_keyframe = pyqtSignal()

    _DIAMOND_RADIUS_PX: float = 5.0
    _GOLD: QColor = QColor(255, 190, 60)
    _NEUTRAL: QColor = QColor(70, 70, 78)
    _NEUTRAL_BORDER: QColor = QColor(120, 120, 128)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a fixed-size clickable keyframe indicator."""
        super().__init__(parent)
        self.setObjectName("KeyframeButton")
        self.setFixedSize(18, CONTROL_HEIGHT_PX)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._is_keyed: bool = False
        self._is_animated: bool = False
        self._apply_tooltip()

    def set_state(self, *, is_keyed: bool, is_animated: bool) -> None:
        """Update the visual state and tooltip, then repaint."""
        self._is_keyed = is_keyed
        self._is_animated = is_animated
        self._apply_tooltip()
        self.update()

    def _apply_tooltip(self) -> None:
        action = "Remove" if self._is_keyed else "Set"
        self.setToolTip(f"{action} keyframe at the current frame")

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """Emit ``toggled_keyframe`` for the primary mouse button."""
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.toggled_keyframe.emit()
        super().mousePressEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """Draw the diamond keyframe glyph."""
        del a0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        radius = self._DIAMOND_RADIUS_PX
        diamond = QPolygonF(
            [
                QPointF(center_x, center_y - radius),
                QPointF(center_x + radius, center_y),
                QPointF(center_x, center_y + radius),
                QPointF(center_x - radius, center_y),
            ]
        )
        if self._is_keyed:
            painter.setBrush(self._GOLD)
            painter.setPen(QPen(self._GOLD.lighter(130), 1.2))
        elif self._is_animated:
            painter.setBrush(self._NEUTRAL)
            painter.setPen(QPen(self._GOLD, 1.2))
        else:
            painter.setBrush(self._NEUTRAL)
            painter.setPen(QPen(self._NEUTRAL_BORDER, 1.0))
        painter.drawPolygon(diamond)
        painter.end()


class PropertyRow(QWidget):
    """Single compact horizontal label/editor row."""

    def __init__(
        self,
        title: str,
        editor: PropertyWidget,
        description: str,
        parent: QWidget | None = None,
        *,
        keyframe_button: KeyframeButtonWidget | None = None,
    ) -> None:
        """Lay out the fixed-width label, flexible editor, and optional keyframe toggle."""
        super().__init__(parent)
        self.setObjectName("PropertyRow")
        self.editor: PropertyWidget = editor
        self.keyframe_button: KeyframeButtonWidget | None = keyframe_button
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label: QLabel = QLabel(title)
        label.setObjectName("PropertyRowLabel")
        label.setFixedWidth(PROPERTY_LABEL_WIDTH_PX)
        label.setToolTip(description)
        layout.addWidget(label)
        layout.addWidget(editor, 1)
        if keyframe_button is not None:
            layout.addWidget(keyframe_button)


def coerce_color_rgb(value: Any) -> ColorRgb:
    """Normalize an arbitrary value into an RGB 0–255 tuple."""
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (
            max(0, min(255, int(value[0]))),
            max(0, min(255, int(value[1]))),
            max(0, min(255, int(value[2]))),
        )
    return NEUTRAL_COLOR_RGB


def _enum_label(member: Enum) -> str:
    """Convert an enum member name into a readable label."""
    return member.name.replace("_", " ")
