"""Qt implementation of the SDK ``WidgetView`` protocol."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.theme import PLUGIN_SURFACE_STYLE

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
        button.clicked.connect(on_click)
        self._buttons[control_id] = button
        self._layout.addWidget(button)

    def add_text(
        self,
        control_id: str,
        value: str,
        placeholder: str = "",
    ) -> None:
        """Append a single-line text field."""
        field = QLineEdit(value)
        field.setObjectName("PluginSurfaceText")
        field.setPlaceholderText(placeholder)
        self._fields[control_id] = field
        self._layout.addWidget(field)

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
