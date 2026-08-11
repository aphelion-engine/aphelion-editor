"""Creates and owns application ``QAction`` instances from the keybind store."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QWidget

from config.keybinds import KeyAction, KeybindStore, NodeCreateSlot
from ui.icons import AppIcon, make_icon

if TYPE_CHECKING:
    from ui.windows.editor import Editor

ActionHandler = Callable[[], None]


class EditorActions:
    """Registry of editor actions with shortcuts sourced from ``KeybindStore``."""

    def __init__(self, editor: Editor, store: KeybindStore) -> None:
        self._editor = editor
        self._store = store
        self._actions: dict[KeyAction, QAction] = {}
        self._node_create_actions: dict[str, QAction] = {}

    @property
    def store(self) -> KeybindStore:
        return self._store

    def get(self, action: KeyAction) -> QAction:
        return self._actions[action]

    def node_create_action(self, slot_id: str) -> QAction | None:
        return self._node_create_actions.get(slot_id)

    def node_create_actions(self) -> list[QAction]:
        """Return create-slot actions in store order (for menus)."""
        actions: list[QAction] = []
        for slot in self._store.node_create_slots():
            action = self._node_create_actions.get(slot.slot_id)
            if action is not None:
                actions.append(action)
        return actions

    def build(self) -> None:
        """Create all actions, wire handlers, and register shortcuts."""
        editor = self._editor
        self._register(
            KeyAction.EXIT,
            editor.close,
            icon=None,
        )
        self._register(KeyAction.UNDO, editor.undo, icon=AppIcon.UNDO)
        self._register(KeyAction.REDO, editor.redo, icon=AppIcon.REDO)
        self._register(
            KeyAction.COPY,
            editor.copy_selected_nodes,
            icon=AppIcon.COPY,
        )
        self._register(KeyAction.PASTE, editor.paste_nodes, icon=AppIcon.PASTE)
        self._register(
            KeyAction.SELECT_ALL,
            editor.node_graph.select_all_nodes,
            icon=AppIcon.SELECT_ALL,
        )
        self._register(
            KeyAction.DUPLICATE,
            editor.duplicate_selected_nodes,
            icon=AppIcon.DUPLICATE,
        )
        self._register(
            KeyAction.DELETE,
            editor.delete_selected_nodes,
            icon=AppIcon.DELETE,
        )
        self._register(
            KeyAction.SEARCH_NODE,
            editor.node_graph.open_node_search,
            icon=AppIcon.ADD_NODE,
            widget_scope=editor.node_graph,
        )
        self._register(
            KeyAction.FIT_GRAPH,
            editor.node_graph.fit_all_nodes,
            icon=AppIcon.FIT_VIEW,
        )
        self._register(
            KeyAction.FIT_GRAPH_ALT,
            editor.node_graph.fit_all_nodes,
            icon=AppIcon.FIT_VIEW,
        )
        self._register(
            KeyAction.TOGGLE_FULLSCREEN,
            editor.toggle_fullscreen,
        )
        self._register(
            KeyAction.FOCUS_VIEWPORT,
            lambda: editor.viewport.setFocus(),
        )
        self._register(
            KeyAction.FOCUS_GRAPH,
            lambda: editor.node_graph.setFocus(),
        )
        self._register(
            KeyAction.FOCUS_TIMELINE,
            lambda: editor.timeline.setFocus(),
        )
        self._register(
            KeyAction.FOCUS_PROPERTIES,
            lambda: editor.properties.setFocus(),
        )
        self._register(KeyAction.RESET_LAYOUT, editor.reset_layout)
        self._register(KeyAction.SHOW_ALL_PANELS, editor.show_all_panels)
        self._register(
            KeyAction.PLAY_PAUSE,
            editor.timeline.toggle_playback,
            icon=AppIcon.PLAY,
        )
        self._register(
            KeyAction.GO_TO_START,
            editor.timeline.go_to_start,
            icon=AppIcon.TO_START,
        )
        self._register(
            KeyAction.STEP_BACK,
            editor.timeline.step_backward,
            icon=AppIcon.STEP_BACK,
        )
        self._register(
            KeyAction.STEP_FORWARD,
            editor.timeline.step_forward,
            icon=AppIcon.STEP_FORWARD,
        )
        self._register(
            KeyAction.GO_TO_END,
            editor.timeline.go_to_end,
            icon=AppIcon.TO_END,
        )
        self._register(
            KeyAction.MARK_IN,
            editor.timeline.set_in_at_playhead,
            icon=AppIcon.MARK_IN,
        )
        self._register(
            KeyAction.MARK_OUT,
            editor.timeline.set_out_at_playhead,
            icon=AppIcon.MARK_OUT,
        )
        self._register(
            KeyAction.SHOW_SHORTCUTS,
            editor.show_keyboard_shortcuts,
        )
        self._register(
            KeyAction.NEW_PROJECT,
            editor.new_project,
            icon=AppIcon.NEW_FILE,
        )
        self._register(
            KeyAction.OPEN_PROJECT,
            editor.open_project,
            icon=AppIcon.OPEN_FILE,
        )
        self._register(
            KeyAction.SAVE_PROJECT,
            editor.save_project,
            icon=AppIcon.SAVE_FILE,
        )

        self._register_node_create_slots()

        editor.undo_action = self.get(KeyAction.UNDO)
        editor.redo_action = self.get(KeyAction.REDO)

    def reapply_shortcuts(self) -> None:
        """Refresh QAction shortcuts after the store changes."""
        for key_action, qaction in self._actions.items():
            self._apply_shortcut(key_action, qaction)
        self.refresh_node_create_actions()

    def refresh_node_create_actions(self) -> None:
        """Sync create-slot labels/shortcuts/enabled state from the store.

        Call after settings remap a slot's key or target.
        """
        for slot in self._store.node_create_slots():
            action = self._node_create_actions.get(slot.slot_id)
            if action is None:
                continue
            self._sync_node_create_action(action, slot)

    def _register_node_create_slots(self) -> None:
        editor = self._editor
        for slot in self._store.node_create_slots():
            action = QAction(slot.display_label(), editor)
            action.setIcon(make_icon(AppIcon.ADD_NODE))
            action.triggered.connect(
                lambda _checked=False, sid=slot.slot_id: editor.create_node_from_slot(
                    sid
                )
            )
            # Graph-scoped so digit keys don't fight timeline/property focus.
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            editor.node_graph.addAction(action)
            self._sync_node_create_action(action, slot)
            self._node_create_actions[slot.slot_id] = action

    def _sync_node_create_action(self, action: QAction, slot: NodeCreateSlot) -> None:
        action.setText(slot.display_label())
        action.setStatusTip(slot.description())
        action.setToolTip(
            f"{slot.display_label()} ({slot.sequence})"
            if slot.sequence
            else slot.display_label()
        )
        action.setShortcut(QKeySequence(slot.sequence))
        action.setShortcutVisibleInContextMenu(True)
        action.setEnabled(slot.target.is_bound and bool(slot.sequence))

    def _register(
        self,
        key_action: KeyAction,
        handler: ActionHandler,
        *,
        icon: AppIcon | None = None,
        widget_scope: QWidget | None = None,
    ) -> QAction:
        spec = self._store.spec(key_action)
        action = QAction(spec.label, self._editor)
        if icon is not None:
            action.setIcon(make_icon(icon))
        if spec.description:
            action.setStatusTip(spec.description)
            action.setToolTip(self._store.tooltip(spec.label, key_action))
        action.triggered.connect(handler)
        self._apply_shortcut(key_action, action, widget_scope=widget_scope)
        host = widget_scope if widget_scope is not None else self._editor
        host.addAction(action)
        self._actions[key_action] = action
        return action

    def _apply_shortcut(
        self,
        key_action: KeyAction,
        action: QAction,
        *,
        widget_scope: QWidget | None = None,
    ) -> None:
        sequence = self._store.sequence(key_action)
        action.setShortcut(QKeySequence(sequence))
        action.setShortcutVisibleInContextMenu(True)
        if widget_scope is not None:
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        else:
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
