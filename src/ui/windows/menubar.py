"""Application menu bar construction for the main editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QDockWidget, QMenu, QMenuBar

from aphelion_sdk.widgets.host import WidgetContext
from config.keybinds import KeyAction
from config.theme import CONTEXT_MENU_STYLE, MENUBAR_STYLE
from ui.icons import AppIcon, make_icon
from ui.node_graph.node_menu import populate_add_node_menu
from ui.windows.layouts import LAYOUT_LABELS, LayoutMode
from core.widgets.registry import global_widget_registry

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
    _build_render_menu(menubar, editor)
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

    recent_menu = file_menu.addMenu("Recent Projects")
    assert recent_menu is not None
    _style_menu(recent_menu)
    _populate_recent_projects(recent_menu, editor)

    file_menu.addSeparator()
    _add_action(file_menu, editor, KeyAction.SAVE_PROJECT)
    _add_action(file_menu, editor, KeyAction.SAVE_PROJECT_AS)
    file_menu.addSeparator()
    _add_action(file_menu, editor, KeyAction.PROJECT_SETTINGS)
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
    edit_menu.addSeparator()
    _add_action(edit_menu, editor, KeyAction.CLEAR_CACHE)
    edit_menu.addSeparator()
    _add_action(edit_menu, editor, KeyAction.OPEN_PREFERENCES)
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
    organize = _add_action(nodes_menu, editor, KeyAction.ORGANIZE_GRAPH)
    organize.setText("Organize Graph…")


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
    _populate_panels_menu(panels_menu, editor)

    window_menu.addSeparator()
    _build_plugin_windows_menu(window_menu, editor)

    window_menu.addSeparator()
    _build_pin_bar_entries(window_menu, editor)

    window_menu.addSeparator()
    reset_window = window_menu.addAction("Reset Layout")
    assert reset_window is not None
    reset_window.setStatusTip(editor.actions.store.spec(KeyAction.RESET_LAYOUT).description)
    reset_window.triggered.connect(editor.reset_layout)


def _populate_panels_menu(panels_menu: QMenu, editor: Editor) -> None:
    """Add built-in and plugin-attached dock toggles."""
    panel_entries: tuple[tuple[str, QDockWidget], ...] = (
        ("Viewport", editor.docks.viewport),
        ("Node Graph", editor.docks.node_graph),
        ("Timeline", editor.docks.timeline),
        ("Properties", editor.docks.properties),
        ("Keyframes", editor.docks.keyframes),
        ("Media Pool", editor.docks.media_pool),
        ("Logs", editor.docks.logs),
    )
    for label, dock in panel_entries:
        _add_dock_toggle(panels_menu, editor, label, dock)
    if editor.plugin_docks:
        panels_menu.addSeparator()
        for dock in editor.plugin_docks:
            title: str = dock.windowTitle() or "Plugin"
            _add_dock_toggle(panels_menu, editor, title, dock)
    panels_menu.addSeparator()
    _add_action(panels_menu, editor, KeyAction.SHOW_ALL_PANELS)
    _add_action(panels_menu, editor, KeyAction.TOGGLE_LOGS)


def _add_dock_toggle(
    menu: QMenu,
    editor: Editor,
    label: str,
    dock: QDockWidget,
) -> None:
    """Add a checkable visibility action for ``dock``."""
    action = QAction(label, editor)
    action.setCheckable(True)
    action.setChecked(dock.isVisible())
    dock.visibilityChanged.connect(action.setChecked)
    action.triggered.connect(
        lambda checked=False, d=dock: d.setVisible(bool(checked))
    )
    menu.addAction(action)


def _build_plugin_windows_menu(window_menu: QMenu, editor: Editor) -> None:
    """Add popups attached to loaded plugins, labeled with the parent plugin."""
    dialogs = global_widget_registry.dialogs(menu_only=True)
    if not dialogs:
        return
    plugin_menu = window_menu.addMenu("Plugin Windows")
    assert plugin_menu is not None
    _style_menu(plugin_menu)
    for registration in dialogs:
        label: str = f"{registration.plugin_name} — {registration.title}"
        action = QAction(label, editor)
        action.triggered.connect(
            lambda _checked=False, key=registration.plugin_key, wid=registration.widget_id: (
                editor.open_plugin_dialog(
                    wid,
                    context=WidgetContext(
                        plugin_key=key,
                        project_name=editor.project.name,
                    ),
                )
            )
        )
        plugin_menu.addAction(action)


def _build_render_menu(menubar: QMenuBar, editor: Editor) -> None:
    """Dedicated menu for exporting/rendering the active viewer output."""
    render_menu = menubar.addMenu("Render")
    assert render_menu is not None
    _style_menu(render_menu)

    _add_action(render_menu, editor, KeyAction.EXPORT_SEQUENCE)


def _build_pin_bar_entries(window_menu: QMenu, editor: Editor) -> None:
    """Add pin-bar visibility toggle and customization entries.

    The pin bar is opt-in: it is never shown automatically, and its
    contents are entirely user-chosen via the customize dialog.
    """
    toggle = editor.pin_bar.toggleViewAction()
    toggle.setText("Pin Bar")
    toggle.setStatusTip("Show or hide the pin bar of frequently used actions")
    window_menu.addAction(toggle)

    customize = window_menu.addAction("Customize Pin Bar…")
    assert customize is not None
    customize.triggered.connect(editor.customize_pin_bar)


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
    about.triggered.connect(editor.show_about)


def _populate_recent_projects(menu: QMenu, editor: Editor) -> None:
    """Fill the recent-projects submenu from the persistent store."""
    menu.clear()
    entries = editor.recent_projects.list_entries()
    if not entries:
        empty = menu.addAction("No recent projects")
        assert empty is not None
        empty.setEnabled(False)
        return

    for entry in entries:
        label = entry.name
        if not entry.exists:
            label = f"{label} (missing)"
        action = menu.addAction(label)
        assert action is not None
        action.setEnabled(entry.exists)
        action.setStatusTip(entry.path)
        action.triggered.connect(
            lambda _checked=False, path=entry.path: editor.open_recent_project(path)
        )
