"""Realize a plugin-attached widget as a host view plus optional QWidget."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from aphelion_sdk.widgets.base import PluginWidget
from aphelion_sdk.widgets.host import WidgetHost, WidgetView
from ui.widgets.plugin_view import QtPluginView
from utils.logging_setup import get_logger

_LOG = get_logger("plugin_surface")


def realize_plugin_widget(
    attached: PluginWidget,
    host: WidgetHost,
    parent: QWidget,
) -> tuple[WidgetView, QWidget | None]:
    """Build ``attached`` using Qt first, then the primitive ``build_view``.

    Parameters:
        attached: Panel or dialog instance owned by a plugin.
        host: Editor host bound to that plugin.
        parent: Qt parent for advanced ``build_qt_widget`` results.

    Returns:
        The SDK view (for ``on_accept``) and the QWidget to embed, if any.
    """
    qt_body = _try_qt_widget(attached, host, parent)
    if qt_body is not None:
        view = host.create_view()
        view.embed_native(qt_body)
        return view, native_plugin_widget(view)
    try:
        view = attached.build_view(host)
    except Exception:  # noqa: BLE001
        _LOG.exception("Widget %s failed to build_view", type(attached))
        view = host.create_view()
    return view, native_plugin_widget(view)


def native_plugin_widget(view: WidgetView) -> QWidget | None:
    """Return the Qt widget backing ``view``, if the host provided one."""
    if isinstance(view, QtPluginView):
        return view.native_widget()
    getter = getattr(view, "native_widget", None)
    if not callable(getter):
        return None
    widget = getter()
    if isinstance(widget, QWidget):
        return widget
    return None


def _try_qt_widget(
    attached: PluginWidget,
    host: WidgetHost,
    parent: QWidget,
) -> QWidget | None:
    """Return ``build_qt_widget`` when it yields a QWidget."""
    try:
        built = attached.build_qt_widget(parent, host)
    except Exception:  # noqa: BLE001
        _LOG.exception("Widget %s failed to build_qt_widget", type(attached))
        return None
    if isinstance(built, QWidget):
        return built
    return None
