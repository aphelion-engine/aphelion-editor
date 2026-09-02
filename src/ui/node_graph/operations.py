"""Multi-node graph operations (align, distribute, duplicate, clipboard)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

from PyQt6.QtCore import QPointF

from config.constants import PASTE_OFFSET_PX
from core.history import (
    AddNodeCommand,
    CompositeCommand,
    InsertAfterCommand,
    MoveNodesCommand,
    PasteNodesCommand,
    RemoveNodesCommand,
    resolve_insert_sockets,
)
from core.nodes import Node, global_node_registry

if TYPE_CHECKING:
    from ui.node_graph.node_item import NodeItem
    from ui.node_graph.view import NodeGraphView


def selected_node_items(view: NodeGraphView) -> list[NodeItem]:
    """Return currently selected node items."""
    from ui.node_graph.node_item import NodeItem

    return [item for item in view.scene.selectedItems() if isinstance(item, NodeItem)]


def delete_items(view: NodeGraphView, items: list[NodeItem]) -> None:
    """Delete the given node items via the global history stack."""
    if not items:
        return
    node_ids = [item.node_id for item in items]
    view.history.push(RemoveNodesCommand(node_ids))


def duplicate_items(view: NodeGraphView, items: list[NodeItem]) -> None:
    """Duplicate selected nodes with a small offset (one undo step)."""
    if not items:
        return
    add_commands: list[AddNodeCommand] = []
    for item in items:
        new_node = _build_node_copy(
            view, item.node_id, offset_x=36.0, offset_y=36.0)
        if new_node is None:
            continue
        add_commands.append(AddNodeCommand(new_node))
    if not add_commands:
        return
    label = (
        "Duplicate Node"
        if len(add_commands) == 1
        else f"Duplicate {len(add_commands)} Nodes"
    )
    if not view.history.push(CompositeCommand(list(add_commands), label)):
        return
    view.scene.clearSelection()
    for command in add_commands:
        node_id = command.node_id
        if node_id is None:
            continue
        node_item = view.node_items.get(node_id)
        if node_item is not None:
            node_item.setSelected(True)


def _commit_positions(
    view: NodeGraphView,
    items: list[NodeItem],
    after: dict[str, tuple[float, float]],
) -> None:
    before = {
        item.node_id: (float(item.pos().x()), float(item.pos().y()))
        for item in items
    }
    view.history.push(MoveNodesCommand(before, after))


def align_left(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    x = min(item.pos().x() for item in items)
    after = {
        item.node_id: (float(x), float(item.pos().y()))
        for item in items
    }
    _commit_positions(view, items, after)


def align_right(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    right = max(item.pos().x() + item.rect().width() for item in items)
    after = {
        item.node_id: (float(right - item.rect().width()),
                       float(item.pos().y()))
        for item in items
    }
    _commit_positions(view, items, after)


def align_top(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    y = min(item.pos().y() for item in items)
    after = {
        item.node_id: (float(item.pos().x()), float(y))
        for item in items
    }
    _commit_positions(view, items, after)


def align_bottom(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    bottom = max(item.pos().y() + item.rect().height() for item in items)
    after = {
        item.node_id: (float(item.pos().x()), float(
            bottom - item.rect().height()))
        for item in items
    }
    _commit_positions(view, items, after)


def align_center_h(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    centers = [item.pos().x() + item.rect().width() / 2 for item in items]
    target = sum(centers) / len(centers)
    after = {
        item.node_id: (float(target - item.rect().width() / 2),
                       float(item.pos().y()))
        for item in items
    }
    _commit_positions(view, items, after)


def align_center_v(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    centers = [item.pos().y() + item.rect().height() / 2 for item in items]
    target = sum(centers) / len(centers)
    after = {
        item.node_id: (float(item.pos().x()), float(
            target - item.rect().height() / 2))
        for item in items
    }
    _commit_positions(view, items, after)


def distribute_horizontal(view: NodeGraphView, items: list[NodeItem]) -> None:
    if len(items) < 3:
        return
    ordered = sorted(items, key=lambda item: item.pos().x())
    left = ordered[0].pos().x()
    right = ordered[-1].pos().x()
    step = (right - left) / (len(ordered) - 1)
    after = {
        item.node_id: (float(left + step * index), float(item.pos().y()))
        for index, item in enumerate(ordered)
    }
    _commit_positions(view, items, after)


def distribute_vertical(view: NodeGraphView, items: list[NodeItem]) -> None:
    if len(items) < 3:
        return
    ordered = sorted(items, key=lambda item: item.pos().y())
    top = ordered[0].pos().y()
    bottom = ordered[-1].pos().y()
    step = (bottom - top) / (len(ordered) - 1)
    after = {
        item.node_id: (float(item.pos().x()), float(top + step * index))
        for index, item in enumerate(ordered)
    }
    _commit_positions(view, items, after)


def create_node_copy(
    view: NodeGraphView,
    node_id: str,
    offset_x: float,
    offset_y: float,
) -> str | None:
    """Create a duplicated node through history and return its id."""
    new_node = _build_node_copy(
        view, node_id, offset_x=offset_x, offset_y=offset_y)
    if new_node is None:
        return None
    command = AddNodeCommand(new_node)
    if not view.history.push(command):
        return None
    return command.node_id


def copy_items(view: NodeGraphView, items: list[NodeItem]) -> bool:
    """Copy selected nodes (and internal wires) into the graph clipboard."""
    if not items:
        return False
    return view.clipboard.capture(
        view.project,
        [item.node_id for item in items],
    )


def paste_items(
    view: NodeGraphView,
    position: QPointF | None = None,
) -> list[str]:
    """Paste the clipboard at ``position`` (or view center) and select results."""
    if view.clipboard.is_empty:
        return []
    if position is None:
        position = view.view_center_scene_pos()
    generation = view.consume_paste_generation()
    origin = (
        float(position.x()) + PASTE_OFFSET_PX * generation,
        float(position.y()) + PASTE_OFFSET_PX * generation,
    )
    command = PasteNodesCommand(
        view.clipboard.snapshots,
        view.clipboard.connections,
        origin,
    )
    if not view.history.push(command):
        return []
    created = command.created_ids
    view.scene.clearSelection()
    for node_id in created:
        item = view.node_items.get(node_id)
        if item is not None:
            item.setSelected(True)
    return created


def insert_node_after(
    view: NodeGraphView,
    source_id: str,
    name: str,
    category: str,
) -> str | None:
    """Create ``name`` after ``source_id`` and splice it into outgoing wires."""
    node = global_node_registry.create_node(name, category=category)
    if node is None:
        return None
    source = view.project.nodes.get(source_id)
    if source is None:
        return None
    if resolve_insert_sockets(source, node) is None:
        return None
    command = InsertAfterCommand(source_id, node)
    if not view.history.push(command):
        return None
    node_id = command.node_id
    if node_id is None:
        return None
    view.scene.clearSelection()
    item = view.node_items.get(node_id)
    if item is not None:
        item.setSelected(True)
    return node_id


def source_has_outgoing(view: NodeGraphView, node_id: str) -> bool:
    """Return whether ``node_id`` has at least one outgoing connection."""
    return any(
        conn.output_node_id == node_id for conn in view.project.connections
    )


def insertable_node_types(
    view: NodeGraphView,
    source_id: str,
) -> list[tuple[str, str]]:
    """Return ``(name, category)`` pairs that can follow ``source_id`` in a chain.

    Passthrough nodes splice into existing wires. Sink nodes (input only) still
    appear and connect after the source without breaking the original chain.
    """
    source = view.project.nodes.get(source_id)
    if source is None or not source.outputs:
        return []
    results: list[tuple[str, str]] = []
    for info in sorted(
        global_node_registry.get_all_nodes().values(),
        key=lambda item: (item.category, item.name),
    ):
        candidate = info.create_instance()
        if resolve_insert_sockets(source, candidate) is None:
            continue
        results.append((info.name, info.category))
    return results


# ---------------------------------------------------------------------------
# Advanced graph organization (layered + size-aware + component grouping)
# ---------------------------------------------------------------------------

def organize_graph(view: NodeGraphView) -> bool:
    """Auto-arrange all nodes by data flow using a layered, size-aware layout.

    This uses a Sugiyama-style layered layout:
    - Topological layering (left-to-right flow).
    - Size-aware spacing based on measured node width/height.
    - Component grouping (disconnected subgraphs separated).
    - Median-based ordering within layers to reduce crossings.
    """

    from ui.node_graph.node_layout import measure_node

    project = view.project
    nodes = project.nodes
    connections = project.connections

    if not nodes:
        return False

    # Build adjacency and reverse adjacency
    adjacency: Dict[str, List[str]] = {nid: [] for nid in nodes}
    reverse_adj: Dict[str, List[str]] = {nid: [] for nid in nodes}

    for conn in connections:
        if conn.output_node_id in adjacency and conn.input_node_id in reverse_adj:
            adjacency[conn.output_node_id].append(conn.input_node_id)
            reverse_adj[conn.input_node_id].append(conn.output_node_id)

    # Detect connected components (so disconnected graphs don't overlap)
    components: List[List[str]] = []
    visited: set[str] = set()

    for nid in nodes:
        if nid in visited:
            continue
        stack = [nid]
        comp: List[str] = []
        visited.add(nid)
        while stack:
            current = stack.pop()
            comp.append(current)
            for child in adjacency[current]:
                if child not in visited:
                    visited.add(child)
                    stack.append(child)
            for parent in reverse_adj[current]:
                if parent not in visited:
                    visited.add(parent)
                    stack.append(parent)
        components.append(comp)

    # Measure node sizes
    sizes: Dict[str, Tuple[int, int]] = {}
    for node_id, node in nodes.items():
        item = view.node_items.get(node_id)
        if item is not None:
            measured = measure_node(node)
            sizes[node_id] = (measured.width, measured.height)
        else:
            sizes[node_id] = (max(int(node.width), 160),
                              max(int(node.height), 92))

    # Layout parameters
    BASE_X_SPACING = 80.0
    BASE_Y_SPACING = 40.0
    COMPONENT_X_GAP = 320.0
    COMPONENT_Y_GAP = 240.0

    after: Dict[str, Tuple[float, float]] = {}
    component_offset_x = 0.0
    component_offset_y = 0.0

    # Layout each component independently
    for comp_index, comp_nodes in enumerate(components):
        # Build indegree for this component
        indegree: Dict[str, int] = {nid: 0 for nid in comp_nodes}
        for nid in comp_nodes:
            for child in adjacency[nid]:
                if child in indegree:
                    indegree[child] += 1

        # Topological order (Kahn)
        queue: List[str] = [nid for nid in comp_nodes if indegree[nid] == 0]
        topo_order: List[str] = []

        while queue:
            nid = queue.pop(0)
            topo_order.append(nid)
            for child in adjacency[nid]:
                if child in indegree:
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        queue.append(child)

        # If cycles exist, append remaining nodes
        for nid in comp_nodes:
            if nid not in topo_order:
                topo_order.append(nid)

        # Assign layers based on longest path depth
        layer: Dict[str, int] = {nid: 0 for nid in comp_nodes}
        for nid in topo_order:
            for child in adjacency[nid]:
                if child in layer:
                    layer[child] = max(layer[child], layer[nid] + 1)

        # Group nodes by layer
        layers: Dict[int, List[str]] = {}
        for nid, depth in layer.items():
            layers.setdefault(depth, []).append(nid)

        # Sort nodes within each layer by median of parent layer index
        for depth, group in layers.items():
            if depth == 0:
                # Stable sort by name for first layer
                layers[depth] = sorted(group, key=lambda nid: nodes[nid].name)
                continue

            parent_median: Dict[str, float] = {}
            for nid in group:
                parents = [p for p in reverse_adj[nid] if p in comp_nodes]
                if parents:
                    parent_median[nid] = sum(layer[p]
                                             for p in parents) / len(parents)
                else:
                    parent_median[nid] = float(depth)
            layers[depth] = sorted(group, key=lambda nid: parent_median[nid])

        # Compute per-layer max width and height
        layer_max_width: Dict[int, float] = {}
        layer_max_height: Dict[int, float] = {}
        for depth, group in layers.items():
            max_w = 0.0
            max_h = 0.0
            for nid in group:
                w, h = sizes[nid]
                max_w = max(max_w, float(w))
                max_h = max(max_h, float(h))
            layer_max_width[depth] = max_w
            layer_max_height[depth] = max_h

        # Compute x positions per layer (cumulative)
        layer_x: Dict[int, float] = {}
        current_x = component_offset_x
        sorted_layers = sorted(layers.keys())
        for depth in sorted_layers:
            layer_x[depth] = current_x
            current_x += layer_max_width[depth] + BASE_X_SPACING

        # Compute y positions within each layer (centered around component_offset_y)
        for depth in sorted_layers:
            group = layers[depth]
            total_height = sum(
                layer_max_height[depth] for _ in group) + BASE_Y_SPACING * (len(group) - 1)
            start_y = component_offset_y - total_height / 2.0
            y_cursor = start_y
            for nid in group:
                w, h = sizes[nid]
                x = layer_x[depth]
                # Center node vertically within its slot
                after[nid] = (x, y_cursor)
                y_cursor += layer_max_height[depth] + BASE_Y_SPACING

        # Advance component offsets for next component
        component_offset_x = current_x + COMPONENT_X_GAP
        if comp_index % 2 == 1:
            component_offset_y += COMPONENT_Y_GAP

    before: Dict[str, Tuple[float, float]] = {
        node_id: (float(node.x), float(node.y)) for node_id, node in nodes.items()
    }

    if before == after:
        return False

    if not view.history.push(MoveNodesCommand(before, after)):
        return False

    view.fit_all_nodes()
    return True


def _build_node_copy(
    view: NodeGraphView,
    node_id: str,
    *,
    offset_x: float,
    offset_y: float,
) -> Node | None:
    """Build an unregistered node copy, or ``None`` if the source is missing."""
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
    return new_node
