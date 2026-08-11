"""Styled context menus for the node graph."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, QSize, pyqtSignal
from PyQt6.QtWidgets import QMenu, QWidget

from core.node_registry import global_node_registry
from core.project import Project
from gui.icons import AppIcon, make_dot_icon, make_icon
from gui.node_graph.constants import MENU_ICON_SIZE_PX
from gui.theme import CONTEXT_MENU_STYLE

if TYPE_CHECKING:
    from gui.node_graph.node_item import NodeItem
    from gui.node_graph.view import NodeGraphView


class GraphContextMenu(QMenu):
    """Empty-canvas menu: add nodes, select all, fit view."""

    node_selected = pyqtSignal(str, str, QPointF)
    select_all_requested = pyqtSignal()
    fit_view_requested = pyqtSignal()

    def __init__(
        self,
        project: Project,
        position: QPointF,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.position = position
        self.setStyleSheet(CONTEXT_MENU_STYLE)
        self.setIconSize(QSize(MENU_ICON_SIZE_PX, MENU_ICON_SIZE_PX))
        self._populate()

    def _populate(self) -> None:
        add_menu = self.addMenu(make_icon(AppIcon.ADD_NODE), "Add Node")
        assert add_menu is not None
        add_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        add_menu.setIconSize(QSize(MENU_ICON_SIZE_PX, MENU_ICON_SIZE_PX))
        self._populate_add_nodes(add_menu)

        self.addSeparator()
        select_all = self.addAction(make_icon(AppIcon.SELECT_ALL), "Select All")
        assert select_all is not None
        select_all.setShortcut("Ctrl+A")
        select_all.triggered.connect(self.select_all_requested.emit)

        fit = self.addAction(make_icon(AppIcon.FIT_VIEW), "Fit to View")
        assert fit is not None
        fit.setShortcut("F")
        fit.triggered.connect(self.fit_view_requested.emit)

    def _populate_add_nodes(self, menu: QMenu) -> None:
        for category in sorted(global_node_registry.get_categories()):
            category_menu = menu.addMenu(category)
            assert category_menu is not None
            category_menu.setStyleSheet(CONTEXT_MENU_STYLE)
            category_menu.setIconSize(QSize(MENU_ICON_SIZE_PX, MENU_ICON_SIZE_PX))

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
                    lambda _checked=False, cat=category, name=node_name: (
                        self.node_selected.emit(name, cat, self.position)
                    )
                )


class NodeOperationsMenu(QMenu):
    """Selection menu supporting single- and multi-node operations."""

    def __init__(self, view: NodeGraphView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = view
        self.setStyleSheet(CONTEXT_MENU_STYLE)
        self.setIconSize(QSize(MENU_ICON_SIZE_PX, MENU_ICON_SIZE_PX))
        self._populate()

    def _populate(self) -> None:
        from gui.node_graph import operations as node_ops

        items = self.view.selected_nodes()
        count = len(items)

        delete = self.addAction(
            make_icon(AppIcon.DELETE),
            f"Delete {count} Nodes" if count > 1 else "Delete Node",
        )
        assert delete is not None
        delete.setShortcut("Delete")
        delete.triggered.connect(lambda: node_ops.delete_items(self.view, items))

        duplicate = self.addAction(
            make_icon(AppIcon.DUPLICATE),
            f"Duplicate {count} Nodes" if count > 1 else "Duplicate Node",
        )
        assert duplicate is not None
        duplicate.setShortcut("Ctrl+D")
        duplicate.triggered.connect(lambda: node_ops.duplicate_items(self.view, items))

        self.addSeparator()
        self._add_align_menu(items)
        self._add_distribute_menu(items)

        self.addSeparator()
        select_all = self.addAction(make_icon(AppIcon.SELECT_ALL), "Select All")
        assert select_all is not None
        select_all.triggered.connect(self.view.select_all_nodes)

        fit = self.addAction(make_icon(AppIcon.FIT_VIEW), "Fit to View")
        assert fit is not None
        fit.triggered.connect(self.view.fit_all_nodes)

    def _add_align_menu(self, items: list[NodeItem]) -> None:
        from gui.node_graph import operations as node_ops

        align_menu = self.addMenu("Align")
        assert align_menu is not None
        align_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        align_menu.setIconSize(QSize(MENU_ICON_SIZE_PX, MENU_ICON_SIZE_PX))
        enabled = len(items) >= 2

        actions: list[tuple[AppIcon, str, object]] = [
            (AppIcon.ALIGN_LEFT, "Left", node_ops.align_left),
            (AppIcon.ALIGN_RIGHT, "Right", node_ops.align_right),
            (AppIcon.ALIGN_TOP, "Top", node_ops.align_top),
            (AppIcon.ALIGN_BOTTOM, "Bottom", node_ops.align_bottom),
            (AppIcon.ALIGN_CENTER_H, "Center Horizontal", node_ops.align_center_h),
            (AppIcon.ALIGN_CENTER_V, "Center Vertical", node_ops.align_center_v),
        ]
        for icon, label, handler in actions:
            action = align_menu.addAction(make_icon(icon), label)
            assert action is not None
            action.setEnabled(enabled)
            action.triggered.connect(lambda _c=False, h=handler: h(items))

    def _add_distribute_menu(self, items: list[NodeItem]) -> None:
        from gui.node_graph import operations as node_ops

        dist_menu = self.addMenu("Distribute")
        assert dist_menu is not None
        dist_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        dist_menu.setIconSize(QSize(MENU_ICON_SIZE_PX, MENU_ICON_SIZE_PX))
        enabled = len(items) >= 3

        h_action = dist_menu.addAction(make_icon(AppIcon.DISTRIBUTE_H), "Horizontally")
        assert h_action is not None
        h_action.setEnabled(enabled)
        h_action.triggered.connect(lambda: node_ops.distribute_horizontal(items))

        v_action = dist_menu.addAction(make_icon(AppIcon.DISTRIBUTE_V), "Vertically")
        assert v_action is not None
        v_action.setEnabled(enabled)
        v_action.triggered.connect(lambda: node_ops.distribute_vertical(items))


# Backwards-compatible alias used by older imports.
NodeContextMenu = GraphContextMenu
