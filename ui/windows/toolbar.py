"""Optional 'Pin Bar' toolbar for user-chosen frequent actions.

Unlike a conventional always-on toolbar, the pin bar starts hidden and
empty of surprises: nothing is auto-enabled. Users opt in via
``Window -> Pin Bar`` and choose exactly which actions appear via
``Window -> Customize Pin Bar...`` (or the toolbar's right-click menu).
The chosen action set and visibility are persisted in ``AppPreferences``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QToolBar

from config.keybinds import KeyAction
from config.theme import CONTEXT_MENU_STYLE, TOOLBAR_STYLE
from ui.icons import icon_size

if TYPE_CHECKING:
    from ui.windows.editor import Editor

PIN_BAR_OBJECT_NAME: str = "PinBar"


def build_pin_bar(editor: Editor) -> QToolBar:
    """Create the pin bar toolbar, hidden by default, and attach to ``editor``.

    Parameters:
        editor: Host window providing registered ``QAction`` instances.

    Returns:
        The configured toolbar (also added to ``editor``). Visibility and
        contents are populated afterwards via ``sync_pin_bar``.
    """
    toolbar = QToolBar("Pin Bar", editor)
    toolbar.setObjectName(PIN_BAR_OBJECT_NAME)
    toolbar.setStyleSheet(TOOLBAR_STYLE)
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setIconSize(icon_size())
    toolbar.setVisible(False)
    toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    toolbar.customContextMenuRequested.connect(
        lambda _pos: _show_pin_bar_context_menu(editor)
    )
    editor.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
    return toolbar


def sync_pin_bar(editor: Editor) -> None:
    """Rebuild pin bar contents/visibility from the current preferences."""
    toolbar = editor.pin_bar
    toolbar.clear()
    for key_action in resolve_pinned_actions(editor):
        toolbar.addAction(editor.actions.get(key_action))
    toolbar.setVisible(editor.preferences_store.preferences.editor.show_pin_bar)


def resolve_pinned_actions(editor: Editor) -> list[KeyAction]:
    """Return the pinned ``KeyAction`` values, dropping unknown/stale entries."""
    resolved: list[KeyAction] = []
    for raw in editor.preferences_store.preferences.pinned_actions:
        try:
            resolved.append(KeyAction(raw))
        except ValueError:
            continue
    return resolved


def _show_pin_bar_context_menu(editor: Editor) -> None:
    menu = QMenu(editor)
    menu.setStyleSheet(CONTEXT_MENU_STYLE)
    customize: QAction | None = menu.addAction("Customize Pin Bar…")
    hide_bar: QAction | None = menu.addAction("Hide Pin Bar")
    if customize is not None:
        customize.triggered.connect(editor.customize_pin_bar)
    if hide_bar is not None:
        hide_bar.triggered.connect(lambda: editor.set_pin_bar_visible(False))
    menu.exec(editor.pin_bar.mapToGlobal(editor.pin_bar.rect().bottomLeft()))
