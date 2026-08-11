"""Multi-node graph operations (align, distribute, duplicate)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.node_registry import global_node_registry

if TYPE_CHECKING:
    from gui.node_graph.node_item import NodeItem
    from gui.node_graph.view import NodeGraphView


def selected_node_items(view: NodeGraphView) -> list[NodeItem]:
    """Return currently selected node items."""
    from gui.node_graph.node_item import NodeItem

    return [item for item in view.scene.selectedItems() if isinstance(item, NodeItem)]


def delete_items(view: NodeGraphView, items: list[NodeItem]) -> None:
    """Delete the given node items from the project."""
    for item in list(items):
        view.project.remove_node(item.node_id)


def duplicate_items(view: NodeGraphView, items: list[NodeItem]) -> None:
    """Duplicate selected nodes with a small offset."""
    created_ids: list[str] = []
    for item in items:
        new_id = view.duplicate_node(item.node_id, offset_x=36, offset_y=36)
        if new_id is not None:
            created_ids.append(new_id)
    view.scene.clearSelection()
    for node_id in created_ids:
        node_item = view.node_items.get(node_id)
        if node_item is not None:
            node_item.setSelected(True)


def align_left(items: list[NodeItem]) -> None:
    if not items:
        return
    x = min(item.pos().x() for item in items)
    for item in items:
        item.setPos(x, item.pos().y())
        item._sync_node_position()


def align_right(items: list[NodeItem]) -> None:
    if not items:
        return
    right = max(item.pos().x() + item.rect().width() for item in items)
    for item in items:
        item.setPos(right - item.rect().width(), item.pos().y())
        item._sync_node_position()


def align_top(items: list[NodeItem]) -> None:
    if not items:
        return
    y = min(item.pos().y() for item in items)
    for item in items:
        item.setPos(item.pos().x(), y)
        item._sync_node_position()


def align_bottom(items: list[NodeItem]) -> None:
    if not items:
        return
    bottom = max(item.pos().y() + item.rect().height() for item in items)
    for item in items:
        item.setPos(item.pos().x(), bottom - item.rect().height())
        item._sync_node_position()


def align_center_h(items: list[NodeItem]) -> None:
    if not items:
        return
    centers = [item.pos().x() + item.rect().width() / 2 for item in items]
    target = sum(centers) / len(centers)
    for item in items:
        item.setPos(target - item.rect().width() / 2, item.pos().y())
        item._sync_node_position()


def align_center_v(items: list[NodeItem]) -> None:
    if not items:
        return
    centers = [item.pos().y() + item.rect().height() / 2 for item in items]
    target = sum(centers) / len(centers)
    for item in items:
        item.setPos(item.pos().x(), target - item.rect().height() / 2)
        item._sync_node_position()


def distribute_horizontal(items: list[NodeItem]) -> None:
    if len(items) < 3:
        return
    ordered = sorted(items, key=lambda item: item.pos().x())
    left = ordered[0].pos().x()
    right = ordered[-1].pos().x()
    step = (right - left) / (len(ordered) - 1)
    for index, item in enumerate(ordered):
        item.setPos(left + step * index, item.pos().y())
        item._sync_node_position()


def distribute_vertical(items: list[NodeItem]) -> None:
    if len(items) < 3:
        return
    ordered = sorted(items, key=lambda item: item.pos().y())
    top = ordered[0].pos().y()
    bottom = ordered[-1].pos().y()
    step = (bottom - top) / (len(ordered) - 1)
    for index, item in enumerate(ordered):
        item.setPos(item.pos().x(), top + step * index)
        item._sync_node_position()


def create_node_copy(
    view: NodeGraphView,
    node_id: str,
    offset_x: float,
    offset_y: float,
) -> str | None:
    """Create a duplicated node in the project and return its id."""
    node = view.project.nodes.get(node_id)
    if node is None:
        return None
    new_node = global_node_registry.create_node(
        node.node_type,
        category=node.node_category,
    )
    if new_node is None:
        return None
    for prop_name, prop in node.properties.items():
        if prop_name.startswith("_input_"):
            continue
        new_node.set_property(prop_name, prop.value)
    new_node.x = node.x + offset_x
    new_node.y = node.y + offset_y
    return view.project.add_node(new_node)
