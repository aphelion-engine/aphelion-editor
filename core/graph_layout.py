"""Pure graph layout: layer nodes by data flow and snap to a grid."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from config.constants import (
    GRAPH_LAYOUT_COLUMN_GAP_PX,
    GRAPH_LAYOUT_COMPONENT_GAP_PX,
    GRAPH_LAYOUT_GRID_PX,
    GRAPH_LAYOUT_ORIGIN_X,
    GRAPH_LAYOUT_ORIGIN_Y,
    GRAPH_LAYOUT_ROW_GAP_PX,
)
from core.events import Connection
from core.nodes import Node


def compute_graph_layout(
    nodes: dict[str, Node],
    connections: Iterable[Connection],
    *,
    sizes: dict[str, tuple[int, int]],
) -> dict[str, tuple[float, float]]:
    """Return snapped ``(x, y)`` positions for every node in ``nodes``.

    Nodes are arranged left-to-right by dependency depth (sources on the
    left, sinks on the right). Disconnected subgraphs are stacked vertically
    with spacing so they do not overlap.

    Parameters:
        nodes: All node ids and models to place.
        connections: Directed edges ``output -> input``.
        sizes: ``node_id -> (width, height)`` in scene pixels.

    Returns:
        A position map covering every key in ``nodes``.
    """
    if not nodes:
        return {}

    upstream: dict[str, list[str]] = defaultdict(list)
    for connection in connections:
        if (
            connection.output_node_id not in nodes
            or connection.input_node_id not in nodes
        ):
            continue
        upstream[connection.input_node_id].append(connection.output_node_id)

    components: list[list[str]] = _connected_components(nodes.keys(), connections)
    positions: dict[str, tuple[float, float]] = {}
    cursor_y: float = GRAPH_LAYOUT_ORIGIN_Y

    for component in components:
        block = _layout_component(component, nodes, upstream, sizes)
        if not block:
            continue
        min_y = min(y for _, y in block.values())
        offset_y = cursor_y - min_y
        for node_id, (x, y) in block.items():
            positions[node_id] = (_snap(x), _snap(y + offset_y))
        block_height = max(
            y + sizes.get(node_id, (160, 92))[1]
            for node_id, (_, y) in block.items()
        )
        cursor_y = max(cursor_y, block_height) + GRAPH_LAYOUT_COMPONENT_GAP_PX

    for node_id in nodes:
        positions.setdefault(
            node_id,
            (_snap(GRAPH_LAYOUT_ORIGIN_X), _snap(GRAPH_LAYOUT_ORIGIN_Y)),
        )
    return positions


def _layout_component(
    node_ids: list[str],
    nodes: dict[str, Node],
    upstream: dict[str, list[str]],
    sizes: dict[str, tuple[int, int]],
) -> dict[str, tuple[float, float]]:
    """Lay out one connected component into layered columns."""
    layers: dict[str, int] = _assign_layers(node_ids, upstream)
    grouped: dict[int, list[str]] = defaultdict(list)
    for node_id in node_ids:
        grouped[layers[node_id]].append(node_id)

    positions: dict[str, tuple[float, float]] = {}
    column_x: float = GRAPH_LAYOUT_ORIGIN_X
    max_layer: int = max(grouped.keys(), default=0)

    for layer in range(max_layer + 1):
        column_nodes: list[str] = sorted(
            grouped.get(layer, []),
            key=lambda node_id: _sort_key(nodes[node_id], node_id),
        )
        if not column_nodes:
            continue

        column_width: int = max(
            sizes.get(node_id, (160, 92))[0] for node_id in column_nodes
        )
        row_heights: list[int] = [
            sizes.get(node_id, (160, 92))[1] for node_id in column_nodes
        ]
        total_height: float = sum(row_heights) + GRAPH_LAYOUT_ROW_GAP_PX * max(
            0, len(column_nodes) - 1
        )
        row_y: float = GRAPH_LAYOUT_ORIGIN_Y - total_height / 2.0

        for node_id, height in zip(column_nodes, row_heights, strict=True):
            positions[node_id] = (column_x, row_y)
            row_y += height + GRAPH_LAYOUT_ROW_GAP_PX

        column_x += column_width + GRAPH_LAYOUT_COLUMN_GAP_PX

    return positions


def _assign_layers(node_ids: list[str], upstream: dict[str, list[str]]) -> dict[str, int]:
    """Assign each node a column index based on longest upstream path."""
    layers: dict[str, int] = {node_id: 0 for node_id in node_ids}
    changed: bool = True
    while changed:
        changed = False
        for node_id in node_ids:
            for parent_id in upstream.get(node_id, []):
                if parent_id not in layers:
                    continue
                candidate: int = layers[parent_id] + 1
                if candidate > layers[node_id]:
                    layers[node_id] = candidate
                    changed = True
    return layers


def _connected_components(
    node_ids: Iterable[str],
    connections: Iterable[Connection],
) -> list[list[str]]:
    """Return undirected connected components sorted largest-first."""
    ids: list[str] = list(node_ids)
    adjacency: dict[str, set[str]] = defaultdict(set)
    for node_id in ids:
        adjacency[node_id] = set()

    for connection in connections:
        if connection.output_node_id not in adjacency:
            continue
        if connection.input_node_id not in adjacency:
            continue
        adjacency[connection.output_node_id].add(connection.input_node_id)
        adjacency[connection.input_node_id].add(connection.output_node_id)

    remaining: set[str] = set(ids)
    components: list[list[str]] = []
    while remaining:
        start: str = min(remaining)
        stack: list[str] = [start]
        component: list[str] = []
        remaining.discard(start)
        while stack:
            current: str = stack.pop()
            component.append(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor in remaining:
                    remaining.discard(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))

    components.sort(key=len, reverse=True)
    return components


def _sort_key(node: Node, node_id: str) -> tuple[str, str, str]:
    """Stable ordering within a layout column."""
    return (node.node_category, node.node_type, node_id)


def _snap(value: float) -> float:
    """Snap a coordinate to the graph grid."""
    grid: float = float(GRAPH_LAYOUT_GRID_PX)
    return round(value / grid) * grid
