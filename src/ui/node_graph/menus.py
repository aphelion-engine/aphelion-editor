"""Styled context menus for the node graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from config.keybinds import KeyAction, KeybindStore
from config.theme import CONTEXT_MENU_STYLE
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QMenu, QWidget
from ui.icons import AppIcon, make_dot_icon, make_icon
from ui.keybinds import apply_menu_hint
from ui.node_graph.constants import MENU_ICON_SIZE_PX
from ui.node_graph.node_menu import populate_add_node_menu

if TYPE_CHECKING:
    from ui.node_graph.node_item import NodeItem
    from ui.node_graph.view import NodeGraphView

AddNodeAtCallback = Callable[[str, str, QPointF], None]


class GraphContextMenu(QMenu):
    """Empty-canvas menu: add nodes, paste, selection tools, fit view."""

    def __init__(
        self,
        position: QPointF,
        *,
        on_add_node: AddNodeAtCallback,
        on_paste: Callable[[], None],
        can_paste: bool,
        on_select_all: Callable[[], None],
        on_fit_view: Callable[[], None],
        on_organize_graph: Callable[[], None],
        keybinds: KeybindStore,
        on_invert_selection: Callable[[], None] | None = None,
        on_select_connected: Callable[[], None] | None = None,
        on_toggle_spotlight: Callable[[], None] | None = None,
        spotlight_enabled: bool = False,
        can_select_related: bool = False,
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

        paste = self.addAction(make_icon(AppIcon.PASTE), "Paste")
        assert paste is not None
        paste.setEnabled(can_paste)
        apply_menu_hint(paste, keybinds, KeyAction.PASTE)
        paste.triggered.connect(on_paste)

        self.addSeparator()
        select_all = self.addAction(make_icon(AppIcon.SELECT_ALL), "Select All")
        assert select_all is not None
        apply_menu_hint(select_all, keybinds, KeyAction.SELECT_ALL)
        select_all.triggered.connect(on_select_all)

        if on_invert_selection is not None:
            invert = self.addAction("Invert Selection")
            assert invert is not None
            apply_menu_hint(invert, keybinds, KeyAction.INVERT_SELECTION)
            invert.triggered.connect(on_invert_selection)

        if on_select_connected is not None:
            connected = self.addAction("Select Connected")
            assert connected is not None
            connected.setEnabled(can_select_related)
            connected.setToolTip("Grow the selection along the graph")
            apply_menu_hint(connected, keybinds, KeyAction.SELECT_CONNECTED)
            connected.triggered.connect(on_select_connected)

        if on_toggle_spotlight is not None:
            spotlight = self.addAction(
                make_icon(AppIcon.SPOTLIGHT), "Spotlight Selection"
            )
            assert spotlight is not None
            spotlight.setCheckable(True)
            spotlight.setChecked(spotlight_enabled)
            spotlight.setToolTip("Dim everything outside the selection")
            apply_menu_hint(spotlight, keybinds, KeyAction.TOGGLE_SPOTLIGHT)
            spotlight.triggered.connect(on_toggle_spotlight)

        self.addSeparator()

        fit = self.addAction(make_icon(AppIcon.FIT_VIEW), "Fit to View")
        assert fit is not None
        apply_menu_hint(fit, keybinds, KeyAction.FIT_GRAPH)
        fit.triggered.connect(on_fit_view)

        organize = self.addAction(make_icon(AppIcon.DISTRIBUTE_H), "Organize Graph")
        assert organize is not None
        apply_menu_hint(organize, keybinds, KeyAction.ORGANIZE_GRAPH)
        organize.triggered.connect(on_organize_graph)


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
        keybinds = self.view.keybinds

        copy_action = self.addAction(make_icon(AppIcon.COPY), "Copy")
        assert copy_action is not None
        copy_action.setEnabled(count > 0)
        apply_menu_hint(copy_action, keybinds, KeyAction.COPY)
        copy_action.triggered.connect(lambda: node_ops.copy_items(self.view, items))

        paste_action = self.addAction(make_icon(AppIcon.PASTE), "Paste")
        assert paste_action is not None
        paste_action.setEnabled(not self.view.clipboard.is_empty)
        apply_menu_hint(paste_action, keybinds, KeyAction.PASTE)
        paste_action.triggered.connect(lambda: node_ops.paste_items(self.view))

        self.addSeparator()

        delete = self.addAction(
            make_icon(AppIcon.DELETE),
            f"Delete {count} Nodes" if count > 1 else "Delete Node",
        )
        assert delete is not None
        apply_menu_hint(delete, keybinds, KeyAction.DELETE)
        delete.triggered.connect(lambda: node_ops.delete_items(self.view, items))

        duplicate = self.addAction(
            make_icon(AppIcon.DUPLICATE),
            f"Duplicate {count} Nodes" if count > 1 else "Duplicate Node",
        )
        assert duplicate is not None
        apply_menu_hint(duplicate, keybinds, KeyAction.DUPLICATE)
        duplicate.triggered.connect(lambda: node_ops.duplicate_items(self.view, items))

        self.addSeparator()
        self._add_custom_node_menu(items)

        if count == 1:
            self._add_insert_after_menu(items[0])

        self.addSeparator()
        self._add_align_menu(items)
        self._add_distribute_menu(items)
        self._add_selection_menu(items)

        self.addSeparator()
        select_all = self.addAction(make_icon(AppIcon.SELECT_ALL), "Select All")
        assert select_all is not None
        apply_menu_hint(select_all, keybinds, KeyAction.SELECT_ALL)
        select_all.triggered.connect(self.view.select_all_nodes)

        fit = self.addAction(make_icon(AppIcon.FIT_VIEW), "Fit to View")
        assert fit is not None
        apply_menu_hint(fit, keybinds, KeyAction.FIT_GRAPH)
        fit.triggered.connect(self.view.fit_all_nodes)

        organize = self.addAction(make_icon(AppIcon.DISTRIBUTE_H), "Organize Graph")
        assert organize is not None
        apply_menu_hint(organize, keybinds, KeyAction.ORGANIZE_GRAPH)
        organize.triggered.connect(self.view.organize_graph)

    def _add_custom_node_menu(self, items: list[NodeItem]) -> None:
        """Add custom-node create / edit / expand entries."""
        from core.nodes.custom_nodes import CustomNode

        count = len(items)
        selected_node = (
            self.view.project.nodes.get(
                items[0].node_id) if count == 1 else None
        )
        is_custom = isinstance(selected_node, CustomNode)

        create = self.addAction(
            make_icon(AppIcon.ADD_NODE), "Create Custom Node…"
        )
        assert create is not None
        create.setEnabled(count >= 1)
        create.setToolTip(
            "Collapse the selected nodes into a reusable custom node"
        )
        create.triggered.connect(self.view.create_custom_node_from_selection)

        edit = self.addAction(
            make_icon(AppIcon.SETTINGS), "Edit Custom Node…"
        )
        assert edit is not None
        edit.setEnabled(is_custom)
        edit.setToolTip("Edit this custom node's inner graph and ports")
        edit.triggered.connect(self.view.edit_selected_custom_node)

        expand = self.addAction(
            make_icon(AppIcon.DUPLICATE), "Expand Custom Node"
        )
        assert expand is not None
        expand.setEnabled(is_custom)
        expand.setToolTip("Replace the custom node with its underlying nodes")
        expand.triggered.connect(self.view.expand_selected_custom_node)

    def _add_insert_after_menu(self, item: NodeItem) -> None:
        from core.nodes import global_node_registry
        from ui.node_graph import operations as node_ops

        if not node_ops.source_has_outgoing(self.view, item.node_id):
            return
        options = node_ops.insertable_node_types(self.view, item.node_id)
        if not options:
            return

        insert_menu = self.addMenu(make_icon(AppIcon.ADD_NODE), "Insert After…")
        assert insert_menu is not None
        insert_menu.setStyleSheet(CONTEXT_MENU_STYLE)

        for name, category in options:
            info = global_node_registry.get_node_info(category, name)
            icon = make_dot_icon(
                global_node_registry.resolve_color(category, name),
                size=MENU_ICON_SIZE_PX,
            )
            action = insert_menu.addAction(icon, name)
            assert action is not None
            if info is not None:
                action.setToolTip(info.description)
            action.triggered.connect(
                lambda _c=False, n=name, c=category, sid=item.node_id: (
                    node_ops.insert_node_after(self.view, sid, n, c)
                )
            )

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
            action.triggered.connect(
                lambda _c=False, h=handler: h(self.view, items)
            )

    def _add_distribute_menu(self, items: list[NodeItem]) -> None:
        from ui.node_graph import operations as node_ops

        dist_menu = self.addMenu("Distribute")
        assert dist_menu is not None
        dist_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        enabled = len(items) >= 3

        h_action = dist_menu.addAction(make_icon(AppIcon.DISTRIBUTE_H), "Horizontally")
        assert h_action is not None
        h_action.setEnabled(enabled)
        h_action.triggered.connect(
            lambda: node_ops.distribute_horizontal(self.view, items)
        )

        v_action = dist_menu.addAction(make_icon(AppIcon.DISTRIBUTE_V), "Vertically")
        assert v_action is not None
        v_action.setEnabled(enabled)
        v_action.triggered.connect(
            lambda: node_ops.distribute_vertical(self.view, items)
        )

    def _add_selection_menu(self, items: list[NodeItem]) -> None:
        """Add wiring, bypass, framing, and spotlight quick actions."""
        from ui.node_graph.selection_ops import SelectionTraversal

        view = self.view
        keybinds = view.keybinds
        count = len(items)

        bypass = self.addAction(make_icon(AppIcon.BYPASS), "Toggle Bypass")
        assert bypass is not None
        bypass.setEnabled(count > 0)
        bypass.setToolTip("Bypass or re-enable the selected effect nodes")
        apply_menu_hint(bypass, keybinds, KeyAction.TOGGLE_BYPASS)
        bypass.triggered.connect(view.toggle_selection_bypass)

        unwire = self.addAction(
            make_icon(AppIcon.DELETE), "Remove Attached Wires")
        assert unwire is not None
        unwire.setEnabled(count > 0)
        unwire.setToolTip("Disconnect every wire touching the selection")
        unwire.triggered.connect(view.remove_selection_wires)

        selection_menu = self.addMenu(
            make_icon(AppIcon.SELECT_ALL), "Selection"
        )
        assert selection_menu is not None
        selection_menu.setStyleSheet(CONTEXT_MENU_STYLE)

        invert = selection_menu.addAction("Invert Selection")
        assert invert is not None
        apply_menu_hint(invert, keybinds, KeyAction.INVERT_SELECTION)
        invert.triggered.connect(view.invert_selection)

        selection_menu.addSeparator()
        for label, handler, key_action in (
            ("Select Connected", view.select_connected, KeyAction.SELECT_CONNECTED),
            ("Select Upstream", view.select_upstream, None),
            ("Select Downstream", view.select_downstream, None),
            ("Select Same Type", view.select_same_type, None),
        ):
            action = selection_menu.addAction(label)
            assert action is not None
            action.setEnabled(count > 0)
            if key_action is not None:
                apply_menu_hint(action, keybinds, key_action)
            action.triggered.connect(handler)

        selection_menu.addSeparator()
        tidy = selection_menu.addAction(
            make_icon(AppIcon.TIDY), "Tidy Selection")
        assert tidy is not None
        tidy.setEnabled(count >= 2)
        apply_menu_hint(tidy, keybinds, KeyAction.TIDY_SELECTION)
        tidy.triggered.connect(view.tidy_selection)

        fit = selection_menu.addAction(
            make_icon(AppIcon.FIT_VIEW), "Fit Selection")
        assert fit is not None
        fit.setEnabled(count > 0)
        apply_menu_hint(fit, keybinds, KeyAction.FIT_SELECTION)
        fit.triggered.connect(view.fit_selection)

        selection_menu.addSeparator()
        spotlight = selection_menu.addAction(
            make_icon(AppIcon.SPOTLIGHT), "Spotlight Selection"
        )
        assert spotlight is not None
        spotlight.setCheckable(True)
        spotlight.setChecked(view.is_spotlight_enabled())
        spotlight.setEnabled(count > 0)
        spotlight.setToolTip("Dim everything outside the selection")
        apply_menu_hint(spotlight, keybinds, KeyAction.TOGGLE_SPOTLIGHT)
        spotlight.triggered.connect(lambda: view.toggle_spotlight())
