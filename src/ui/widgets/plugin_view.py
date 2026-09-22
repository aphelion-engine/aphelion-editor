"""Qt implementation of the SDK ``WidgetView`` protocol."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QFrame,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.theme import PLUGIN_SURFACE_STYLE
from utils.logging_setup import get_logger


def _safe_callback(callback):
    def invoke(*args):
        try:
            callback(*args)
        except Exception:
            get_logger("plugin_view").exception("Plugin control callback failed")
    return invoke


_UNKNOWN_CONTROL: str = ""


class QtPluginView:
    """Vertical stack of labeled primitives. Plugin authors never import this."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self._root: QWidget = QWidget(parent)
        self._root.setObjectName("PluginSurface")
        self._root.setStyleSheet(PLUGIN_SURFACE_STYLE)
        self._layout: QVBoxLayout = QVBoxLayout(self._root)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)
        self._labels: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._fields: dict[str, QLineEdit] = {}
        self._values: dict[str, QWidget] = {}

    def native_widget(self) -> QWidget:
        """Return the Qt widget the editor embeds in a dock or dialog."""
        return self._root

    def add_label(self, control_id: str, text: str) -> None:
        """Append a static text label."""
        label = QLabel(text)
        label.setObjectName("PluginSurfaceLabel")
        label.setWordWrap(True)
        self._labels[control_id] = label
        self._layout.addWidget(label)

    def add_button(
        self,
        control_id: str,
        label: str,
        on_click: Callable[[], None],
    ) -> None:
        """Append a push button that invokes ``on_click``."""
        button = QPushButton(label)
        button.setObjectName("PluginSurfaceButton")
        button.clicked.connect(_safe_callback(lambda _checked=False: on_click()))
        self._buttons[control_id] = button
        self._layout.addWidget(button)

    def add_text(
        self,
        control_id: str,
        value: str,
        placeholder: str = "",
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        """Append a single-line text field."""
        field = QLineEdit(value)
        field.setObjectName("PluginSurfaceText")
        field.setPlaceholderText(placeholder)
        self._fields[control_id] = field
        self._layout.addWidget(field)
        if on_change is not None:
            field.textEdited.connect(_safe_callback(on_change))

    def add_separator(self) -> None:
        """Append a horizontal divider."""
        line = QFrame()
        line.setObjectName("PluginSurfaceDivider")
        line.setFrameShape(QFrame.Shape.HLine)
        self._layout.addWidget(line)

    def set_text(self, control_id: str, text: str) -> None:
        """Replace the visible text of a label, button, or text field."""
        if control_id in self._labels:
            self._labels[control_id].setText(text)
            return
        if control_id in self._buttons:
            self._buttons[control_id].setText(text)
            return
        if control_id in self._fields:
            self._fields[control_id].setText(text)

    def get_text(self, control_id: str) -> str:
        """Return the current text of a label, button, or text field."""
        if control_id in self._labels:
            return self._labels[control_id].text()
        if control_id in self._buttons:
            return self._buttons[control_id].text()
        if control_id in self._fields:
            return self._fields[control_id].text()
        return _UNKNOWN_CONTROL

    def embed_native(self, widget: object) -> None:
        """Reparent a PyQt6 ``QWidget`` into this surface."""
        if not isinstance(widget, QWidget):
            raise TypeError("embed_native requires a PyQt6 QWidget")
        widget.setParent(self._root)
        self._layout.addWidget(widget, 1)

    def add_stretch(self) -> None:
        """Push remaining controls toward the top of the view."""
        self._layout.addStretch(1)

    def add_number(self, control_id, label, value, minimum=-1e9, maximum=1e9, on_change=None):
        if minimum > maximum:
            raise ValueError("minimum must not exceed maximum")
        field = QDoubleSpinBox()
        field.setDecimals(6)
        field.setRange(minimum, maximum)
        field.setValue(value)
        self._layout.addWidget(QLabel(label))
        self._layout.addWidget(field)
        self._values[control_id] = field
        if on_change is not None:
            field.valueChanged.connect(_safe_callback(on_change))

    def add_toggle(self, control_id, label, value, on_change=None):
        field = QCheckBox(label)
        field.setChecked(value)
        self._layout.addWidget(field)
        self._values[control_id] = field
        if on_change is not None:
            field.toggled.connect(_safe_callback(on_change))

    def add_choice(self, control_id, label, choices, value, on_change=None):
        if value not in choices:
            raise ValueError("value must be one of choices")
        field = QComboBox()
        field.addItems(choices)
        field.setCurrentText(value)
        self._layout.addWidget(QLabel(label))
        self._layout.addWidget(field)
        self._values[control_id] = field
        if on_change is not None:
            field.currentTextChanged.connect(_safe_callback(on_change))

    def get_value(self, control_id):
        if control_id in self._fields:
            return self._fields[control_id].text()
        field = self._values[control_id]
        if isinstance(field, QDoubleSpinBox):
            return field.value()
        if isinstance(field, QCheckBox):
            return field.isChecked()
        return field.currentText()

    def set_value(self, control_id, value):
        field = self._fields.get(control_id)
        if field is None:
            field = self._values[control_id]
        blocked = field.blockSignals(True)
        try:
            if isinstance(field, QDoubleSpinBox):
                field.setValue(float(value))
            elif isinstance(field, QCheckBox):
                field.setChecked(bool(value))
            elif isinstance(field, QComboBox):
                if field.findText(str(value)) < 0:
                    raise ValueError("value must be one of choices")
                field.setCurrentText(str(value))
            else:
                field.setText(str(value))
        finally:
            field.blockSignals(blocked)
