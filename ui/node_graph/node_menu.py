"""Shared helpers for populating Add Node menus."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QMenu

from config.theme import CONTEXT_MENU_STYLE
from core.nodes import global_node_registry
from ui.icons import make_dot_icon
from ui.node_graph.constants import MENU_ICON_SIZE_PX

AddNodeCallback = Callable[[str, str], None]


def populate_add_node_menu(menu: QMenu, on_add: AddNodeCallback) -> None:
    """Fill a menu with registry categories and node types.

    Parameters:
        menu: Parent menu to populate.
        on_add: Callback ``(node_name, category)`` invoked when a type is chosen.
    """
    menu.setStyleSheet(CONTEXT_MENU_STYLE)
    for category in sorted(global_node_registry.get_categories()):
        category_menu = menu.addMenu(category)
        assert category_menu is not None
        category_menu.setStyleSheet(CONTEXT_MENU_STYLE)

        for node_name in global_node_registry.get_nodes_in_category(category):
            info = global_node_registry.get_node_info(category, node_name)
            if info is None:
                continue
            action = category_menu.addAction(
                make_dot_icon(info.color, size=MENU_ICON_SIZE_PX),
                node_name,
            )
            assert action is not None
            action.setToolTip(info.description)
            action.triggered.connect(
                lambda _checked=False, cat=category, name=node_name: on_add(name, cat)
            )
