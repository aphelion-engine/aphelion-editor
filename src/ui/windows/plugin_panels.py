"""Mount dockable ``PanelWidget`` instances attached to loaded plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget

from aphelion_sdk.widgets.host import WidgetContext
from aphelion_sdk.widgets.panel import PanelWidget
from core.widgets.registry import WidgetRegistration, global_widget_registry
from ui.widgets.plugin_host import EditorWidgetHost
from ui.widgets.plugin_surface import realize_plugin_widget
from utils.logging_setup import get_logger

if TYPE_CHECKING:
    from ui.windows.editor import Editor

_LOG = get_logger("plugin_panels")

_AREA_MAP: dict[str, Qt.DockWidgetArea] = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
    "top": Qt.DockWidgetArea.TopDockWidgetArea,
}


def mount_plugin_panels(editor: Editor) -> None:
    """Destroy previous plugin docks and remount from the widget registry."""
    unmount_plugin_panels(editor)
    docks: list[QDockWidget] = []
    for registration in global_widget_registry.panels():
        dock = _mount_one(editor, registration)
        if dock is not None:
            docks.append(dock)
    editor.plugin_docks = docks


def unmount_plugin_panels(editor: Editor) -> None:
    """Remove and delete every plugin-attached dock on ``editor``."""
    for dock in editor.plugin_docks:
        editor.removeDockWidget(dock)
        dock.deleteLater()
    editor.plugin_docks = []


def _mount_one(editor: Editor, registration: WidgetRegistration) -> QDockWidget | None:
    """Build one dock for ``registration``, or None if construction fails."""
    if not issubclass(registration.widget_class, PanelWidget):
        return None
    context = WidgetContext(
        plugin_key=registration.plugin_key,
        project_name=editor.project.name,
    )
    host = EditorWidgetHost(editor, context)
    instance = registration.widget_class()
    if not isinstance(instance, PanelWidget):
        return None
    try:
        _view, native = realize_plugin_widget(instance, host, editor)
    except Exception:  # noqa: BLE001
        _LOG.exception("Panel widget %s failed to build", registration.key)
        return None
    if native is None:
        return None
    title: str = f"{registration.plugin_name} — {registration.title}"
    dock = editor.create_dock(title, native)
    dock.setObjectName(f"Dock_Plugin_{registration.key.replace('/', '_')}")
    area = _AREA_MAP.get(registration.dock_area, Qt.DockWidgetArea.RightDockWidgetArea)
    editor.addDockWidget(area, dock)
    dock.setVisible(registration.default_visible)
    return dock
