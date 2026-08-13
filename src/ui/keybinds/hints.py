"""Helpers for showing keybind hints in menus, tooltips, and status chrome."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence

from config.keybinds import KeyAction, KeybindStore


def apply_menu_hint(
    action: QAction,
    store: KeybindStore,
    key_action: KeyAction,
) -> None:
    """Show a shortcut in a context menu without grabbing it app-wide.

    Parameters:
        action: Menu action to annotate.
        store: Active keybind store.
        key_action: Which binding to display.
    """
    sequence = store.sequence(key_action)
    if not sequence:
        return
    action.setShortcut(QKeySequence(sequence))
    action.setShortcutVisibleInContextMenu(True)
    action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)


def status_hint_line(store: KeybindStore, *, context: str) -> str:
    """Compact status-bar hint string for the focused panel context."""
    parts: list[str] = []
    if context == "graph":
        pairs: list[tuple[str, KeyAction]] = [
            ("Search", KeyAction.SEARCH_NODE),
            ("Fit", KeyAction.FIT_GRAPH),
            ("Copy", KeyAction.COPY),
            ("Paste", KeyAction.PASTE),
        ]
        parts.extend(f"{store.hint(action)} {label}" for label, action in pairs)
        for slot in store.bound_node_create_slots()[:3]:
            parts.append(f"{slot.sequence} {slot.target.node_type}")
    elif context == "timeline":
        pairs = [
            ("Play", KeyAction.PLAY_PAUSE),
            ("Step", KeyAction.STEP_FORWARD),
            ("In", KeyAction.MARK_IN),
            ("Out", KeyAction.MARK_OUT),
        ]
        parts.extend(f"{store.hint(action)} {label}" for label, action in pairs)
    else:
        pairs = [
            ("Undo", KeyAction.UNDO),
            ("Play", KeyAction.PLAY_PAUSE),
            ("Shortcuts", KeyAction.SHOW_SHORTCUTS),
        ]
        parts.extend(f"{store.hint(action)} {label}" for label, action in pairs)
    return "  |  ".join(parts)
