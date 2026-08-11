"""Styled context menus for the node graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QMenu, QWidget

from config.theme import CONTEXT_MENU_STYLE
from ui.icons import AppIcon, make_icon
from ui.node_graph.node_menu import populate_add_node_menu

if TYPE_CHECKING:
    from ui.node_graph.node_item import NodeItem
    from ui.node_graph.view import NodeGraphView

AddNodeAtCallback = Callable[[str, str, QPointF], None]


class GraphContextMenu(QMenu):
    """Empty-canvas menu: add nodes, select all, fit view."""

    def __init__(
        self,
        position: QPointF,
        *,
        on_add_node: AddNodeAtCallback,
        on_select_all: Callable[[], None],
        on_fit_view: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._position = position
        self._on_add_node = on_add_node
        self.setStyleSheet(CONTEXT_MENU_STYLE)

        add_menu = self.addMenu(make_icon(AppIcon.ADD_NODE), "Add Node")
        assert add_menu is not None
        populate_add_node_menu(
            add_menu,
            lambda name, cat: self._on_add_node(name, cat, self._position),
        )

        self.addSeparator()
        select_all = self.addAction(make_icon(AppIcon.SELECT_ALL), "Select All")
        assert select_all is not None
        select_all.triggered.connect(on_select_all)

        fit = self.addAction(make_icon(AppIcon.FIT_VIEW), "Fit to View")
        assert fit is not None
        fit.triggered.connect(on_fit_view)


class NodeOperationsMenu(QMenu):
    """Selection menu supporting single- and multi-node operations."""

    def __init__(self, view: NodeGraphView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = view
        self.setStyleSheet(CONTEXT_MENU_STYLE)
        self._populate()

    def _populate(self) -> None:
        from ui.node_graph import operations as node_ops

        items = self.view.selected_nodes()
        count = len(items)

        delete = self.addAction(
            make_icon(AppIcon.DELETE),
            f"Delete {count} Nodes" if count > 1 else "Delete Node",
        )
        assert delete is not None
        delete.triggered.connect(lambda: node_ops.delete_items(self.view, items))

        duplicate = self.addAction(
            make_icon(AppIcon.DUPLICATE),
            f"Duplicate {count} Nodes" if count > 1 else "Duplicate Node",
        )
        assert duplicate is not None
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
        from ui.node_graph import operations as node_ops

        align_menu = self.addMenu("Align")
        assert align_menu is not None
        align_menu.setStyleSheet(CONTEXT_MENU_STYLE)
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
        from ui.node_graph import operations as node_ops

        dist_menu = self.addMenu("Distribute")
        assert dist_menu is not None
        dist_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        enabled = len(items) >= 3

        h_action = dist_menu.addAction(make_icon(AppIcon.DISTRIBUTE_H), "Horizontally")
        assert h_action is not None
        h_action.setEnabled(enabled)
        h_action.triggered.connect(lambda: node_ops.distribute_horizontal(items))

        v_action = dist_menu.addAction(make_icon(AppIcon.DISTRIBUTE_V), "Vertically")
        assert v_action is not None
        v_action.setEnabled(enabled)
        v_action.triggered.connect(lambda: node_ops.distribute_vertical(items))
