"""Host chrome for plugin-attached ``DialogWidget`` popups."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
)

from aphelion_sdk.widgets.dialog import DialogWidget
from aphelion_sdk.widgets.host import WidgetHost, WidgetView
from config.theme import PLUGIN_DIALOG_STYLE
from core.widgets.registry import WidgetRegistration, global_widget_registry
from ui.widgets.plugin_surface import realize_plugin_widget
from utils.logging_setup import get_logger

_LOG = get_logger("plugin_dialog")


def open_attached_dialog(
    parent: QWidget,
    widget_id: str,
    host: WidgetHost,
) -> bool:
    """Open the dialog widget attached to ``host.context().plugin_key``.

    Parameters:
        parent: Editor window used as dialog parent.
        widget_id: Widget id on the bound parent plugin.
        host: Host already bound to that plugin (and optional node).

    Returns:
        True when a dialog was constructed and shown.
    """
    registration = global_widget_registry.resolve(
        widget_id,
        plugin_key=host.context().plugin_key,
    )
    if registration is None:
        _LOG.warning("No dialog widget %r on plugin %s", widget_id, host.context().plugin_key)
        return False
    if not issubclass(registration.widget_class, DialogWidget):
        _LOG.warning("Widget %s is not a DialogWidget", registration.key)
        return False
    dialog = PluginPopupDialog(parent, registration, host)
    dialog.exec()
    return True


class PluginPopupDialog(QDialog):
    """Modal/modeless chrome around a plugin-attached dialog widget."""

    def __init__(
        self,
        parent: QWidget,
        registration: WidgetRegistration,
        host: WidgetHost,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PluginPopupDialog")
        self.setStyleSheet(PLUGIN_DIALOG_STYLE)
        title: str = f"{registration.plugin_name} — {registration.title}"
        self.setWindowTitle(title)
        self.setModal(registration.dialog_modal)
        self.resize(registration.dialog_width, registration.dialog_height)
        self._host: WidgetHost = host
        self._widget: DialogWidget = _dialog_instance(registration)
        self._view: WidgetView
        native: QWidget | None
        self._view, native = realize_plugin_widget(self._widget, host, self)
        self._layout_chrome(native)

    def _layout_chrome(self, body: QWidget | None) -> None:
        """Stack the body view and standard OK/Cancel buttons."""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        if body is not None:
            root.addWidget(body, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self) -> None:
        """Commit dialog state through the widget, then close."""
        self._widget.on_accept(self._view, self._host)
        super().accept()

    def reject(self) -> None:
        """Notify the widget of cancel, then close."""
        self._widget.on_reject(self._view, self._host)
        super().reject()


def _dialog_instance(registration: WidgetRegistration) -> DialogWidget:
    """Construct the dialog widget class stored on ``registration``."""
    instance = registration.widget_class()
    if not isinstance(instance, DialogWidget):
        raise TypeError(f"{registration.key} is not a DialogWidget")
    return instance
