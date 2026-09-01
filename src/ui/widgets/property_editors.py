"""Compact reusable editors for typed node properties."""

from __future__ import annotations

from enum import Enum
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
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
    QToolButton,
    QVBoxLayout,
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

class EqCurveCanvas(QWidget):
    """Interactive mini EQ graph with draggable bands."""

    bands_changed = pyqtSignal(object)

    def __init__(self, bands: list[dict[str, float]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bands: list[dict[str, float]] = []
        self._active_band: int | None = None
        self._set_bands(bands)
        self.setMinimumHeight(170)
        self.setMouseTracking(True)

    def _set_bands(self, bands: list[dict[str, float]]) -> None:
        cleaned: list[dict[str, float]] = []
        for band in bands:
            freq = float(band.get("freq", 1000.0))
            gain = float(band.get("gain", 0.0))
            q = float(band.get("q", 1.0))
            cleaned.append(
                {
                    "freq": max(20.0, min(20000.0, freq)),
                    "gain": max(-24.0, min(24.0, gain)),
                    "q": max(0.2, min(10.0, q)),
                }
            )
        cleaned.sort(key=lambda item: item["freq"])
        self._bands = cleaned
        self.update()

    def bands(self) -> list[dict[str, float]]:
        return [dict(band) for band in self._bands]

    def set_bands(self, bands: list[dict[str, float]]) -> None:
        self._set_bands(bands)

    def _plot_rect(self) -> QRectF:
        return QRectF(12.0, 12.0, max(10.0, self.width() - 24.0), max(10.0, self.height() - 24.0))

    def _freq_to_x(self, freq: float, rect: QRectF) -> float:
        lo = np.log10(20.0)
        hi = np.log10(20000.0)
        t = (np.log10(max(20.0, min(20000.0, freq))) - lo) / (hi - lo)
        return rect.left() + rect.width() * t

    def _x_to_freq(self, x: float, rect: QRectF) -> float:
        lo = np.log10(20.0)
        hi = np.log10(20000.0)
        t = 0.0 if rect.width() <= 0 else (x - rect.left()) / rect.width()
        t = max(0.0, min(1.0, t))
        return float(10.0 ** (lo + (hi - lo) * t))

    def _gain_to_y(self, gain: float, rect: QRectF) -> float:
        t = (max(-24.0, min(24.0, gain)) + 24.0) / 48.0
        return rect.bottom() - rect.height() * t

    def _y_to_gain(self, y: float, rect: QRectF) -> float:
        t = 0.0 if rect.height() <= 0 else (rect.bottom() - y) / rect.height()
        t = max(0.0, min(1.0, t))
        return float((t * 48.0) - 24.0)

    def _band_at(self, pos_x: float, pos_y: float) -> int | None:
        rect = self._plot_rect()
        best_idx: int | None = None
        best_dist = 14.0
        for idx, band in enumerate(self._bands):
            bx = self._freq_to_x(band["freq"], rect)
            by = self._gain_to_y(band["gain"], rect)
            dist = float(((bx - pos_x) ** 2 + (by - pos_y) ** 2) ** 0.5)
            if dist <= best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._active_band = self._band_at(event.position().x(), event.position().y())
            if self._active_band is not None:
                self._move_active(event.position().x(), event.position().y())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._active_band is not None:
            self._move_active(event.position().x(), event.position().y())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._active_band = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            rect = self._plot_rect()
            freq = self._x_to_freq(event.position().x(), rect)
            gain = self._y_to_gain(event.position().y(), rect)
            self._bands.append({"freq": freq, "gain": gain, "q": 1.0})
            self._bands.sort(key=lambda item: item["freq"])
            self.bands_changed.emit(self.bands())
            self.update()
            return
        super().mouseDoubleClickEvent(event)

    def _move_active(self, x: float, y: float) -> None:
        if self._active_band is None:
            return
        rect = self._plot_rect()
        band = self._bands[self._active_band]
        band["freq"] = self._x_to_freq(x, rect)
        band["gain"] = self._y_to_gain(y, rect)
        self._bands.sort(key=lambda item: item["freq"])
        self.bands_changed.emit(self.bands())
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        rect = self._plot_rect()
        painter.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base).darker(115))
        painter.fillRect(rect, pal.color(QPalette.ColorRole.Base))

        grid_pen = QPen(pal.color(QPalette.ColorRole.Mid))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for gain in (-24, -12, 0, 12, 24):
            y = self._gain_to_y(float(gain), rect)
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        for freq in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
            x = self._freq_to_x(float(freq), rect)
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

        zero_pen = QPen(QColor(90, 170, 255))
        zero_pen.setWidth(2)
        painter.setPen(zero_pen)
        zero_y = self._gain_to_y(0.0, rect)
        painter.drawLine(int(rect.left()), int(zero_y), int(rect.right()), int(zero_y))

        if self._bands:
            points = QPolygonF()
            for x in np.linspace(rect.left(), rect.right(), 192):
                freq = self._x_to_freq(float(x), rect)
                total_gain = 0.0
                for band in self._bands:
                    distance = np.log2(max(freq, 20.0) / max(band["freq"], 20.0))
                    spread = max(0.15, 1.2 / band["q"])
                    total_gain += band["gain"] * float(np.exp(-0.5 * (distance / spread) ** 2))
                y = self._gain_to_y(max(-24.0, min(24.0, total_gain)), rect)
                points.append(QPointF(float(x), y))
            curve_pen = QPen(QColor(255, 180, 80))
            curve_pen.setWidth(2)
            painter.setPen(curve_pen)
            painter.drawPolyline(points)

        for idx, band in enumerate(self._bands):
            bx = self._freq_to_x(band["freq"], rect)
            by = self._gain_to_y(band["gain"], rect)
            color = QColor(255, 210, 100) if idx == self._active_band else QColor(220, 220, 220)
            painter.setPen(QPen(color, 2))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(bx, by), 4.5, 4.5)


class EqCurvePropertyWidget(PropertyWidget):
    """Visual EQ editor with draggable/addable bands."""

    value_changed = pyqtSignal(object)

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        super().__init__(prop, parent)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._row.addLayout(layout, 1)

        bands = self._normalize_value(prop.value)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        self.add_button = QToolButton()
        self.add_button.setText("+")
        self.remove_button = QToolButton()
        self.remove_button.setText("-")
        self.summary = QLabel()
        self.summary.setObjectName("PropertySliderValue")
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addWidget(self.summary, 1)
        layout.addLayout(toolbar)

        self.canvas = EqCurveCanvas(bands)
        layout.addWidget(self.canvas)

        self.add_button.clicked.connect(self._add_band)
        self.remove_button.clicked.connect(self._remove_band)
        self.canvas.bands_changed.connect(self._on_bands_changed)
        self._update_summary()

    def _normalize_value(self, value: Any) -> list[dict[str, float]]:
        if isinstance(value, dict) and isinstance(value.get("bands"), list):
            bands = value.get("bands")
            assert isinstance(bands, list)
            return [dict(item) for item in bands if isinstance(item, dict)]
        if isinstance(value, dict) and {"low", "mid", "high"}.issubset(set(value.keys())):
            return [
                {"freq": 120.0, "gain": float(value.get("low", 0.0)), "q": 0.8},
                {"freq": 1000.0, "gain": float(value.get("mid", 0.0)), "q": 1.0},
                {"freq": 8000.0, "gain": float(value.get("high", 0.0)), "q": 0.8},
            ]
        return [
            {"freq": 120.0, "gain": 0.0, "q": 0.8},
            {"freq": 1000.0, "gain": 0.0, "q": 1.0},
            {"freq": 8000.0, "gain": 0.0, "q": 0.8},
        ]

    def _pack_value(self) -> dict[str, Any]:
        bands = self.canvas.bands()
        derived = sorted(bands, key=lambda band: band["freq"])
        low = derived[0]["gain"] if derived else 0.0
        mid = derived[len(derived) // 2]["gain"] if derived else 0.0
        high = derived[-1]["gain"] if derived else 0.0
        return {"bands": bands, "low": low, "mid": mid, "high": high}

    def _update_summary(self) -> None:
        self.summary.setText(f"{len(self.canvas.bands())} band(s)  ·  drag to shape, double-click to add")

    def _on_bands_changed(self, _bands: object) -> None:
        self._update_summary()
        self.value_changed.emit(self._pack_value())

    def _add_band(self) -> None:
        bands = self.canvas.bands()
        bands.append({"freq": 2500.0 if not bands else min(20000.0, bands[-1]["freq"] * 1.5), "gain": 0.0, "q": 1.0})
        self.canvas.set_bands(bands)
        self._on_bands_changed(self.canvas.bands())

    def _remove_band(self) -> None:
        bands = self.canvas.bands()
        if len(bands) <= 1:
            return
        bands.pop()
        self.canvas.set_bands(bands)
        self._on_bands_changed(self.canvas.bands())

    def get_value(self) -> Any:
        return self._pack_value()

    def set_value(self, value: Any) -> None:
        self.canvas.set_bands(self._normalize_value(value))
        self._update_summary()


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


class CustomPropertyWidget(PropertyWidget):
    """Edit button that opens a dialog widget on the parent plugin."""

    edit_requested = pyqtSignal()

    def __init__(self, prop: NodeProperty, parent: QWidget | None = None) -> None:
        """Build a summary label and Edit action."""
        super().__init__(prop, parent)
        self._summary: QLabel = QLabel(_custom_summary(prop.value))
        self._summary.setObjectName("PropertyCustomSummary")
        self._button: QPushButton = QPushButton("Edit…")
        self._button.setObjectName("PropertyCustomButton")
        self._button.setFixedHeight(CONTROL_HEIGHT_PX)
        self._button.clicked.connect(self.edit_requested.emit)
        self._row.addWidget(self._summary, 1)
        self._row.addWidget(self._button)

    def get_value(self) -> Any:
        """Return the stored property value."""
        return self.prop.value

    def set_value(self, value: Any) -> None:
        """Refresh the summary from ``value``."""
        self.prop.value = value
        self._summary.setText(_custom_summary(value))


def _custom_summary(value: Any) -> str:
    """Return a compact inspector summary for a custom property value."""
    if value is None or value == "":
        return "—"
    text: str = str(value)
    if len(text) > 32:
        return text[:31] + "…"
    return text


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
    """Single compact property row with optional full-width editor mode."""

    def __init__(
        self,
        title: str,
        editor: PropertyWidget,
        description: str,
        parent: QWidget | None = None,
        *,
        keyframe_button: KeyframeButtonWidget | None = None,
        full_width: bool = False,
    ) -> None:
        """Lay out either a normal labeled row or a full-width custom editor."""
        super().__init__(parent)
        self.setObjectName("PropertyRow")
        self.editor: PropertyWidget = editor
        self.keyframe_button: KeyframeButtonWidget | None = keyframe_button
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if full_width:
            container = QVBoxLayout()
            container.setContentsMargins(0, 0, 0, 0)
            container.setSpacing(4)
            label: QLabel = QLabel(title)
            label.setObjectName("PropertyRowLabel")
            label.setToolTip(description)
            container.addWidget(label)
            container.addWidget(editor)
            layout.addLayout(container, 1)
            if keyframe_button is not None:
                layout.addWidget(keyframe_button, alignment=Qt.AlignmentFlag.AlignTop)
            return
        label = QLabel(title)
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
