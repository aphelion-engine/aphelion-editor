"""Application menu bar construction for the main editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMenu, QMenuBar

from config.theme import CONTEXT_MENU_STYLE, MENUBAR_STYLE
from ui.icons import AppIcon, make_icon
from ui.node_graph.node_menu import populate_add_node_menu

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
    return menubar


def _style_menu(menu: QMenu) -> None:
    menu.setStyleSheet(CONTEXT_MENU_STYLE)


def _build_file_menu(menubar: QMenuBar, editor: Editor) -> None:
    file_menu = menubar.addMenu("File")
    assert file_menu is not None
    _style_menu(file_menu)

    new_action = file_menu.addAction(make_icon(AppIcon.NEW_FILE), "New Project")
    assert new_action is not None
    new_action.setShortcut(QKeySequence("Ctrl+N"))
    new_action.setStatusTip("Create a new project")

    open_action = file_menu.addAction(make_icon(AppIcon.OPEN_FILE), "Open Project…")
    assert open_action is not None
    open_action.setShortcut(QKeySequence("Ctrl+O"))
    open_action.setStatusTip("Open an existing project")

    save_action = file_menu.addAction(make_icon(AppIcon.SAVE_FILE), "Save Project")
    assert save_action is not None
    save_action.setShortcut(QKeySequence("Ctrl+S"))
    save_action.setStatusTip("Save the current project")

    file_menu.addSeparator()

    exit_action = file_menu.addAction("Exit")
    assert exit_action is not None
    exit_action.setShortcut(QKeySequence("Ctrl+Q"))
    exit_action.setStatusTip("Quit Aphelion")
    exit_action.triggered.connect(editor.close)


def _build_edit_menu(menubar: QMenuBar, editor: Editor) -> None:
    edit_menu = menubar.addMenu("Edit")
    assert edit_menu is not None
    _style_menu(edit_menu)

    undo_action = edit_menu.addAction(make_icon(AppIcon.UNDO), "Undo")
    assert undo_action is not None
    undo_action.setShortcut(QKeySequence("Ctrl+Z"))
    undo_action.setEnabled(False)

    redo_action = edit_menu.addAction(make_icon(AppIcon.REDO), "Redo")
    assert redo_action is not None
    redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
    redo_action.setEnabled(False)

    edit_menu.addSeparator()

    select_all = edit_menu.addAction(make_icon(AppIcon.SELECT_ALL), "Select All Nodes")
    assert select_all is not None
    select_all.setShortcut(QKeySequence("Ctrl+A"))
    select_all.triggered.connect(editor.node_graph.select_all_nodes)

    duplicate = edit_menu.addAction(make_icon(AppIcon.DUPLICATE), "Duplicate Selection")
    assert duplicate is not None
    duplicate.setShortcut(QKeySequence("Ctrl+D"))
    duplicate.triggered.connect(editor.duplicate_selected_nodes)

    delete_action = edit_menu.addAction(make_icon(AppIcon.DELETE), "Delete Selection")
    assert delete_action is not None
    delete_action.setShortcut(QKeySequence("Delete"))
    delete_action.triggered.connect(editor.delete_selected_nodes)


def _build_nodes_menu(menubar: QMenuBar, editor: Editor) -> None:
    nodes_menu = menubar.addMenu("Nodes")
    assert nodes_menu is not None
    _style_menu(nodes_menu)

    add_root = nodes_menu.addMenu(make_icon(AppIcon.ADD_NODE), "Add Node")
    assert add_root is not None
    populate_add_node_menu(add_root, editor.insert_node_from_menu)

    nodes_menu.addSeparator()

    fit = nodes_menu.addAction(make_icon(AppIcon.FIT_VIEW), "Fit Graph to View")
    assert fit is not None
    fit.setShortcut(QKeySequence("F"))
    fit.triggered.connect(editor.node_graph.fit_all_nodes)


def _build_view_menu(menubar: QMenuBar, editor: Editor) -> None:
    view_menu = menubar.addMenu("View")
    assert view_menu is not None
    _style_menu(view_menu)

    fit_action = view_menu.addAction(make_icon(AppIcon.FIT_VIEW), "Fit Graph to View")
    assert fit_action is not None
    fit_action.setShortcut(QKeySequence("Shift+F"))
    fit_action.triggered.connect(editor.node_graph.fit_all_nodes)

    view_menu.addSeparator()

    focus_graph = QAction("Focus Node Graph", editor)
    focus_graph.setShortcut(QKeySequence("Ctrl+1"))
    focus_graph.triggered.connect(lambda: editor.node_graph.setFocus())
    view_menu.addAction(focus_graph)

    focus_timeline = QAction("Focus Timeline", editor)
    focus_timeline.setShortcut(QKeySequence("Ctrl+2"))
    focus_timeline.triggered.connect(lambda: editor.timeline.setFocus())
    view_menu.addAction(focus_timeline)
