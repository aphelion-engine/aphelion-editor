"""Application menu bar construction for the main editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QDockWidget, QMenu, QMenuBar

from config.keybinds import KeyAction
from config.theme import CONTEXT_MENU_STYLE, MENUBAR_STYLE
from ui.icons import AppIcon, make_icon
from ui.node_graph.node_menu import populate_add_node_menu
from ui.windows.layouts import LAYOUT_LABELS, LayoutMode

if TYPE_CHECKING:
    from ui.windows.editor import Editor


def build_menu_bar(editor: Editor) -> QMenuBar:
    """Create and wire the full application menu bar.

    Parameters:
        editor: Host editor window providing actions and the node graph.

    Returns:
        The configured ``QMenuBar`` attached to ``editor``.
    """
    menubar = editor.menuBar()
    assert menubar is not None
    menubar.clear()
    menubar.setStyleSheet(MENUBAR_STYLE)

    _build_file_menu(menubar, editor)
    _build_edit_menu(menubar, editor)
    _build_nodes_menu(menubar, editor)
    _build_view_menu(menubar, editor)
    _build_window_menu(menubar, editor)
    _build_playback_menu(menubar, editor)
    _build_help_menu(menubar, editor)
    return menubar


def _style_menu(menu: QMenu) -> None:
    menu.setStyleSheet(CONTEXT_MENU_STYLE)


def _add_action(menu: QMenu, editor: Editor, key_action: KeyAction) -> QAction:
    action = editor.actions.get(key_action)
    menu.addAction(action)
    return action


def _build_file_menu(menubar: QMenuBar, editor: Editor) -> None:
    file_menu = menubar.addMenu("File")
    assert file_menu is not None
    _style_menu(file_menu)

    _add_action(file_menu, editor, KeyAction.NEW_PROJECT)
    _add_action(file_menu, editor, KeyAction.OPEN_PROJECT)
    _add_action(file_menu, editor, KeyAction.SAVE_PROJECT)
    file_menu.addSeparator()
    _add_action(file_menu, editor, KeyAction.EXIT)


def _build_edit_menu(menubar: QMenuBar, editor: Editor) -> None:
    edit_menu = menubar.addMenu("Edit")
    assert edit_menu is not None
    _style_menu(edit_menu)

    _add_action(edit_menu, editor, KeyAction.UNDO)
    _add_action(edit_menu, editor, KeyAction.REDO)
    edit_menu.addSeparator()
    _add_action(edit_menu, editor, KeyAction.COPY)
    _add_action(edit_menu, editor, KeyAction.PASTE)
    edit_menu.addSeparator()
    _add_action(edit_menu, editor, KeyAction.SELECT_ALL)
    _add_action(edit_menu, editor, KeyAction.DUPLICATE)
    _add_action(edit_menu, editor, KeyAction.DELETE)
    editor._sync_history_actions()


def _build_nodes_menu(menubar: QMenuBar, editor: Editor) -> None:
    nodes_menu = menubar.addMenu("Nodes")
    assert nodes_menu is not None
    _style_menu(nodes_menu)

    add_root = nodes_menu.addMenu(make_icon(AppIcon.ADD_NODE), "Add Node")
    assert add_root is not None
    populate_add_node_menu(add_root, editor.insert_node_from_menu)

    search = _add_action(nodes_menu, editor, KeyAction.SEARCH_NODE)
    search.setText("Search Nodes…")

    quick = nodes_menu.addMenu("Quick Create")
    assert quick is not None
    _style_menu(quick)
    for action in editor.actions.node_create_actions():
        if action.isEnabled():
            quick.addAction(action)

    nodes_menu.addSeparator()
    _add_action(nodes_menu, editor, KeyAction.FIT_GRAPH)


def _build_view_menu(menubar: QMenuBar, editor: Editor) -> None:
    view_menu = menubar.addMenu("View")
    assert view_menu is not None
    _style_menu(view_menu)

    _add_action(view_menu, editor, KeyAction.FIT_GRAPH_ALT)
    view_menu.addSeparator()
    _add_action(view_menu, editor, KeyAction.TOGGLE_FULLSCREEN)
    view_menu.addSeparator()
    _add_action(view_menu, editor, KeyAction.FOCUS_VIEWPORT)
    _add_action(view_menu, editor, KeyAction.FOCUS_GRAPH)
    _add_action(view_menu, editor, KeyAction.FOCUS_TIMELINE)
    _add_action(view_menu, editor, KeyAction.FOCUS_PROPERTIES)


def _build_window_menu(menubar: QMenuBar, editor: Editor) -> None:
    window_menu = menubar.addMenu("Window")
    assert window_menu is not None
    _style_menu(window_menu)

    layouts_menu = window_menu.addMenu("Layout")
    assert layouts_menu is not None
    _style_menu(layouts_menu)

    layout_group = QActionGroup(editor)
    layout_group.setExclusive(True)
    editor.layout_actions = {}
    for mode in LayoutMode:
        action = QAction(LAYOUT_LABELS[mode], editor)
        action.setCheckable(True)
        action.setChecked(mode == editor.layout_mode)
        action.triggered.connect(
            lambda _checked=False, m=mode: editor.set_layout_mode(m)
        )
        layout_group.addAction(action)
        layouts_menu.addAction(action)
        editor.layout_actions[mode] = action

    layouts_menu.addSeparator()
    _add_action(layouts_menu, editor, KeyAction.RESET_LAYOUT)

    window_menu.addSeparator()

    panels_menu = window_menu.addMenu("Panels")
    assert panels_menu is not None
    _style_menu(panels_menu)

    panel_entries: tuple[tuple[str, QDockWidget], ...] = (
        ("Viewport", editor.docks.viewport),
        ("Node Graph", editor.docks.node_graph),
        ("Timeline", editor.docks.timeline),
        ("Properties", editor.docks.properties),
    )
    for label, dock in panel_entries:
        action = QAction(label, editor)
        action.setCheckable(True)
        action.setChecked(dock.isVisible())
        dock.visibilityChanged.connect(action.setChecked)
        action.triggered.connect(
            lambda checked=False, d=dock: d.setVisible(bool(checked))
        )
        panels_menu.addAction(action)

    panels_menu.addSeparator()
    _add_action(panels_menu, editor, KeyAction.SHOW_ALL_PANELS)

    window_menu.addSeparator()
    reset_window = window_menu.addAction("Reset Layout")
    assert reset_window is not None
    reset_window.setStatusTip(editor.actions.store.spec(KeyAction.RESET_LAYOUT).description)
    reset_window.triggered.connect(editor.reset_layout)


def _build_playback_menu(menubar: QMenuBar, editor: Editor) -> None:
    playback_menu = menubar.addMenu("Playback")
    assert playback_menu is not None
    _style_menu(playback_menu)

    _add_action(playback_menu, editor, KeyAction.PLAY_PAUSE)
    playback_menu.addSeparator()
    _add_action(playback_menu, editor, KeyAction.GO_TO_START)
    _add_action(playback_menu, editor, KeyAction.STEP_BACK)
    _add_action(playback_menu, editor, KeyAction.STEP_FORWARD)
    _add_action(playback_menu, editor, KeyAction.GO_TO_END)
    playback_menu.addSeparator()
    _add_action(playback_menu, editor, KeyAction.MARK_IN)
    _add_action(playback_menu, editor, KeyAction.MARK_OUT)


def _build_help_menu(menubar: QMenuBar, editor: Editor) -> None:
    help_menu = menubar.addMenu("Help")
    assert help_menu is not None
    _style_menu(help_menu)

    _add_action(help_menu, editor, KeyAction.SHOW_SHORTCUTS)
    help_menu.addSeparator()

    about = help_menu.addAction("About Aphelion")
    assert about is not None
    about.triggered.connect(
        lambda: _status(editor, "Aphelion — node-based video editor")
    )


def _status(editor: Editor, message: str) -> None:
    status = editor.statusBar()
    if status is not None:
        status.showMessage(message, 4000)
