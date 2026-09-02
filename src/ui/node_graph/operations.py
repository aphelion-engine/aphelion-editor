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

from enum import Enum


class GraphLayoutMode(Enum):
    FRUCHTERMAN = 1
    HIERARCHICAL = 2
    GRID = 3
    DAG_LAYERED = 4


# ---------------------------------------------------------------------------
# Selection / basic operations
# ---------------------------------------------------------------------------

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
        new_node = _build_node_copy(view, item.node_id, offset_x=36.0, offset_y=36.0)
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


# ---------------------------------------------------------------------------
# Alignment / distribution
# ---------------------------------------------------------------------------

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
        item.node_id: (float(right - item.rect().width()), float(item.pos().y()))
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
        item.node_id: (float(item.pos().x()), float(bottom - item.rect().height()))
        for item in items
    }
    _commit_positions(view, items, after)


def align_center_h(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    centers = [item.pos().x() + item.rect().width() / 2 for item in items]
    target = sum(centers) / len(centers)
    after = {
        item.node_id: (float(target - item.rect().width() / 2), float(item.pos().y()))
        for item in items
    }
    _commit_positions(view, items, after)


def align_center_v(view: NodeGraphView, items: list[NodeItem]) -> None:
    if not items:
        return
    centers = [item.pos().y() + item.rect().height() / 2 for item in items]
    target = sum(centers) / len(centers)
    after = {
        item.node_id: (float(item.pos().x()), float(target - item.rect().height() / 2))
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


# ---------------------------------------------------------------------------
# Copy / paste / insert
# ---------------------------------------------------------------------------

def create_node_copy(
    view: NodeGraphView,
    node_id: str,
    offset_x: float,
    offset_y: float,
) -> str | None:
    """Create a duplicated node through history and return its id."""
    new_node = _build_node_copy(view, node_id, offset_x=offset_x, offset_y=offset_y)
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
# Layout dispatcher
# ---------------------------------------------------------------------------

def organize_graph(view: NodeGraphView) -> bool:
    """Dispatch to the selected layout algorithm based on view.layout_mode."""
    mode = getattr(view, "layout_mode", GraphLayoutMode.HIERARCHICAL)

    if mode is GraphLayoutMode.FRUCHTERMAN:
        return organize_graph_fruchterman(view)
    if mode is GraphLayoutMode.HIERARCHICAL:
        return organize_graph_hierarchical(view)
    if mode is GraphLayoutMode.GRID:
        return organize_graph_grid(view)
    if mode is GraphLayoutMode.DAG_LAYERED:
        return organize_graph_dag_layered(view)

    # Fallback
    return organize_graph_hierarchical(view)


# ---------------------------------------------------------------------------
# Fruchterman–Reingold force-directed layout
# ---------------------------------------------------------------------------

def organize_graph_fruchterman(view: NodeGraphView) -> bool:
    """
    Organize graph using the Fruchterman–Reingold force-directed algorithm.
    Produces natural clusters, clear areas, and readable layouts.
    """

    import random
    import math
    from ui.node_graph.node_layout import measure_node

    project = view.project
    nodes = project.nodes
    connections = project.connections

    if not nodes:
        return False

    adjacency = {nid: [] for nid in nodes}
    for c in connections:
        adjacency[c.output_node_id].append(c.input_node_id)
        adjacency[c.input_node_id].append(c.output_node_id)

    sizes = {}
    for nid, node in nodes.items():
        item = view.node_items.get(nid)
        if item:
            m = measure_node(node)
            sizes[nid] = (m.width, m.height)
        else:
            sizes[nid] = (max(int(node.width), 160), max(int(node.height), 92))

    positions = {}
    for nid in nodes:
        positions[nid] = [random.uniform(0, 1), random.uniform(0, 1)]

    area = 20000.0
    k = math.sqrt(area / max(len(nodes), 1))
    iterations = 80
    temperature = 200.0

    for _ in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in nodes}

        for v in nodes:
            for u in nodes:
                if u == v:
                    continue
                dx = positions[v][0] - positions[u][0]
                dy = positions[v][1] - positions[u][1]
                dist = math.sqrt(dx * dx + dy * dy) + 0.01
                force = (k * k) / dist
                disp[v][0] += (dx / dist) * force
                disp[v][1] += (dy / dist) * force

        for v in nodes:
            for u in adjacency[v]:
                dx = positions[v][0] - positions[u][0]
                dy = positions[v][1] - positions[u][1]
                dist = math.sqrt(dx * dx + dy * dy) + 0.01
                force = (dist * dist) / k
                disp[v][0] -= (dx / dist) * force
                disp[v][1] -= (dy / dist) * force

        for v in nodes:
            dx, dy = disp[v]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 0:
                positions[v][0] += (dx / dist) * min(dist, temperature)
                positions[v][1] += (dy / dist) * min(dist, temperature)

        temperature *= 0.92

    xs = [positions[nid][0] for nid in nodes]
    ys = [positions[nid][1] for nid in nodes]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    scale_x = 400.0
    scale_y = 300.0

    after = {}
    for nid in nodes:
        px = positions[nid][0]
        py = positions[nid][1]

        nx = (px - min_x) / (max_x - min_x + 0.001)
        ny = (py - min_y) / (max_y - min_y + 0.001)

        after[nid] = (
            nx * scale_x * len(nodes) ** 0.5,
            ny * scale_y * len(nodes) ** 0.5,
        )

    before = {nid: (float(node.x), float(node.y)) for nid, node in nodes.items()}

    if before == after:
        return False

    if not view.history.push(MoveNodesCommand(before, after)):
        return False

    view.fit_all_nodes()
    return True


# ---------------------------------------------------------------------------
# Hierarchical / tree-based layout
# ---------------------------------------------------------------------------

def organize_graph_hierarchical(view: NodeGraphView) -> bool:
    """
    Compact hierarchical / tree-based layout.

    - X = depth (distance from sources)
    - Y = compacted branch index (logical branch)
    - Category zones create vertical grouping without extreme separation
    - Disconnected components become separate horizontal areas
    """

    from ui.node_graph.node_layout import measure_node

    project = view.project
    nodes = project.nodes
    connections = project.connections

    if not nodes:
        return False

    adjacency = {nid: [] for nid in nodes}
    reverse_adj = {nid: [] for nid in nodes}

    for c in connections:
        adjacency[c.output_node_id].append(c.input_node_id)
        reverse_adj[c.input_node_id].append(c.output_node_id)

    components: List[List[str]] = []
    visited: set[str] = set()

    for nid in nodes:
        if nid in visited:
            continue
        stack = [nid]
        comp: List[str] = []
        visited.add(nid)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in adjacency[cur]:
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
            for parent in reverse_adj[cur]:
                if parent not in visited:
                    visited.add(parent)
                    stack.append(parent)
        components.append(comp)

    sizes: Dict[str, Tuple[int, int]] = {}
    for nid, node in nodes.items():
        item = view.node_items.get(nid)
        if item:
            m = measure_node(node)
            sizes[nid] = (m.width, m.height)
        else:
            sizes[nid] = (max(int(node.width), 160), max(int(node.height), 92))

    DEPTH_X = 260.0
    BRANCH_Y = 140.0
    CATEGORY_ZONE_SPACING = 3
    AREA_GAP_X = 600.0

    after: Dict[str, Tuple[float, float]] = {}
    area_offset_x = 0.0

    def zone(node: Node) -> int:
        t = node.node_type.lower()
        c = (node.node_category or "").lower()
        if "input" in t or "source" in t or "media" in c:
            return 0
        if "motion" in t or "transform" in t:
            return 1
        if "audio" in t or "sound" in c:
            return 2
        if "viewer" in t or "output" in t or "render" in t:
            return 3
        return 4

    for comp in components:
        roots = [nid for nid in comp if not reverse_adj[nid]]
        if not roots:
            roots = [comp[0]]

        depth: Dict[str, int] = {nid: 0 for nid in comp}
        queue: List[str] = list(roots)

        while queue:
            cur = queue.pop(0)
            for child in adjacency[cur]:
                if depth[child] < depth[cur] + 1:
                    depth[child] = depth[cur] + 1
                    queue.append(child)

        branch_index: Dict[str, int] = {}
        branch_counter = 0

        def dfs(nid: str) -> None:
            nonlocal branch_counter
            if nid in branch_index:
                return
            branch_index[nid] = branch_counter
            branch_counter += 1
            for child in adjacency[nid]:
                dfs(child)

        for r in roots:
            dfs(r)

        for nid in comp:
            if nid not in branch_index:
                branch_index[nid] = branch_counter
                branch_counter += 1

        for nid in comp:
            node = nodes[nid]
            branch_index[nid] += zone(node) * CATEGORY_ZONE_SPACING

        all_branches = list(branch_index.values())
        min_b = min(all_branches)
        max_b = max(all_branches)
        mid = (min_b + max_b) / 2.0

        for nid in comp:
            branch_index[nid] = branch_index[nid] - mid

        for nid in comp:
            d = depth[nid]
            b = branch_index[nid]
            w, h = sizes[nid]

            x = area_offset_x + d * DEPTH_X
            y = b * BRANCH_Y

            after[nid] = (x, y - h * 0.5)

        max_depth = max(depth.values()) if depth else 0
        area_offset_x += (max_depth + 2) * DEPTH_X + AREA_GAP_X

    before = {nid: (float(node.x), float(node.y)) for nid, node in nodes.items()}

    if before == after:
        return False

    if not view.history.push(MoveNodesCommand(before, after)):
        return False

    view.fit_all_nodes()
    return True


# ---------------------------------------------------------------------------
# Grid layout
# ---------------------------------------------------------------------------

def organize_graph_grid(view: NodeGraphView) -> bool:
    """Simple grid layout for readability and debugging."""

    project = view.project
    nodes = project.nodes

    if not nodes:
        return False

    GRID_X = 240.0
    GRID_Y = 160.0
    MAX_COL = 8

    after: Dict[str, Tuple[float, float]] = {}
    row = 0
    col = 0

    for nid in nodes:
        x = col * GRID_X
        y = row * GRID_Y
        after[nid] = (x, y)

        col += 1
        if col >= MAX_COL:
            col = 0
            row += 1

    before = {nid: (float(node.x), float(node.y)) for nid, node in nodes.items()}

    if before == after:
        return False

    if not view.history.push(MoveNodesCommand(before, after)):
        return False

    view.fit_all_nodes()
    return True


# ---------------------------------------------------------------------------
# DAG layered layout
# ---------------------------------------------------------------------------

def organize_graph_dag_layered(view: NodeGraphView) -> bool:
    """Classic DAG layered layout (Graphviz DOT style)."""

    project = view.project
    nodes = project.nodes
    connections = project.connections

    if not nodes:
        return False

    adjacency: Dict[str, List[str]] = {nid: [] for nid in nodes}
    indegree: Dict[str, int] = {nid: 0 for nid in nodes}

    for c in connections:
        adjacency[c.output_node_id].append(c.input_node_id)
        indegree[c.input_node_id] += 1

    queue: List[str] = [nid for nid in nodes if indegree[nid] == 0]
    topo: List[str] = []

    while queue:
        nid = queue.pop(0)
        topo.append(nid)
        for child in adjacency[nid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    depth: Dict[str, int] = {nid: 0 for nid in nodes}
    for nid in topo:
        for child in adjacency[nid]:
            depth[child] = max(depth[child], depth[nid] + 1)

    layers: Dict[int, List[str]] = {}
    for nid, d in depth.items():
        layers.setdefault(d, []).append(nid)

    LAYER_X = 260.0
    LAYER_Y = 160.0

    after: Dict[str, Tuple[float, float]] = {}
    for d, group in layers.items():
        for i, nid in enumerate(group):
            x = d * LAYER_X
            y = i * LAYER_Y
            after[nid] = (x, y)

    before = {nid: (float(node.x), float(node.y)) for nid, node in nodes.items()}

    if before == after:
        return False

    if not view.history.push(MoveNodesCommand(before, after)):
        return False

    view.fit_all_nodes()
    return True


# ---------------------------------------------------------------------------
# Node copy helper
# ---------------------------------------------------------------------------

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
