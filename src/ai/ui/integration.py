"""Editor integration for the AI assistant.

All of this is lazy. ``ai_settings_store()`` is only touched when the user asks
for the assistant or opens preferences, so a user who never enables AI has no
AI module imported, no dock created, and no settings file read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai.credentials import credentials_store
from ai.settings import ai_settings_store

if TYPE_CHECKING:
    from ui.windows.editor import Editor

#: Object name of the assistant dock, used by the Window → Panels menu.
AI_DOCK_OBJECT_NAME: str = "Dock_AIAssistant"


def ai_dock(editor: Editor) -> Any | None:
    """Return the existing assistant dock, if one has been created."""
    return getattr(editor, "_ai_dock", None)


def ai_panel(editor: Editor) -> Any | None:
    return getattr(editor, "_ai_panel", None)


def ensure_ai_dock(editor: Editor, *, show: bool = True) -> Any | None:
    """Create the assistant dock on first use and return it."""
    from ai.ui.ai_panel import AIPanel
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QDockWidget

    existing = ai_dock(editor)
    if existing is not None:
        if show:
            existing.show()
            existing.raise_()
        return existing

    store = ai_settings_store()
    panel = AIPanel(editor, store, credentials_store())
    dock = QDockWidget("AI Assistant", editor)
    dock.setObjectName(AI_DOCK_OBJECT_NAME)
    dock.setWidget(panel)
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetClosable
        | QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    dock.setAllowedAreas(
        Qt.DockWidgetArea.LeftDockWidgetArea
        | Qt.DockWidgetArea.RightDockWidgetArea
        | Qt.DockWidgetArea.BottomDockWidgetArea
        | Qt.DockWidgetArea.TopDockWidgetArea
    )
    editor.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    properties_dock = getattr(getattr(editor, "docks", None), "properties", None)
    if properties_dock is not None:
        editor.tabifyDockWidget(properties_dock, dock)
        properties_dock.raise_()

    editor._ai_dock = dock
    editor._ai_panel = panel
    if show:
        dock.show()
        dock.raise_()
    return dock


def toggle_ai_assistant(editor: Editor) -> None:
    """View → AI Assistant / Ctrl+Shift+A.

    When the assistant is disabled this opens AI settings instead of an empty
    panel, because a disabled panel with no explanation is a dead end.
    """
    store = ai_settings_store()
    if not store.settings.enabled:
        open_ai_settings(editor)
        return

    dock = ai_dock(editor)
    if dock is None:
        ensure_ai_dock(editor, show=True)
        panel = ai_panel(editor)
        if panel is not None:
            panel.focus_input()
        return

    visible = dock.isVisible() and not dock.isMinimized()
    if visible:
        dock.hide()
    else:
        dock.show()
        dock.raise_()
        panel = ai_panel(editor)
        if panel is not None:
            panel.focus_input()


def open_ai_settings(editor: Editor) -> None:
    """Open the standalone AI settings dialog."""
    from ai.ui.ai_settings_dialog import AISettingsDialog

    dialog = AISettingsDialog(ai_settings_store(), credentials_store(), editor)
    accepted = dialog.exec() == AISettingsDialog.DialogCode.Accepted
    on_ai_settings_changed(editor, force_open=accepted and not ai_dock(editor))


def on_ai_settings_changed(editor: Editor, *, force_open: bool = False) -> None:
    """React to settings changes from any surface."""
    store = ai_settings_store()
    panel = ai_panel(editor)
    if panel is not None:
        panel.on_settings_changed()
    if store.settings.enabled:
        if force_open:
            ensure_ai_dock(editor, show=True)
        elif panel is None:
            return
    elif panel is not None:
        panel.refresh_state()


def shutdown_ai(editor: Editor) -> None:
    """Release the assistant before the editor closes."""
    panel = ai_panel(editor)
    if panel is not None:
        try:
            panel.shutdown()
        except Exception:  # noqa: BLE001 - shutdown must never block closing
            pass


__all__ = [
    "AI_DOCK_OBJECT_NAME",
    "ai_dock",
    "ai_panel",
    "ensure_ai_dock",
    "on_ai_settings_changed",
    "open_ai_settings",
    "shutdown_ai",
    "toggle_ai_assistant",
]
