"""Selection-focused quick actions for the node graph.

``ui.node_graph.operations`` owns clipboard, insert, and auto-layout work.
This module holds the "act on whatever is currently selected" verbs: invert,
grow the selection along the graph, nudge, tidy, bypass, fit, and unhook
wires.

Every command goes through the shared :class:`~core.history.HistoryStack`, so
multi-node edits undo as a single step. Positional commands reuse
``MoveNodesCommand``'s coalescing, which means holding an arrow key produces
one undo entry instead of dozens.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum
from typing import TYPE_CHECKING

from core.events import Connection
from core.history import (CompositeCommand, DisconnectCommand,
                          MoveNodesCommand, SetPropertyCommand)
from PyQt6.QtCore import QRectF, Qt

if TYPE_CHECKING:
    from ui.node_graph.node_item import NodeItem
    from ui.node_graph.view import NodeGraphView

#: Toggle property that every bypassable effect node registers.
BYPASS_PROPERTY: str = "enabled"

#: Scene-space distance moved per arrow-key nudge.
NUDGE_STEP_PX: float = 12.0
NUDGE_STEP_COARSE_PX: float = 48.0

#: Gaps used when packing a selection into a tidy grid.
TIDY_COLUMN_GAP_PX: float = 56.0
TIDY_ROW_GAP_PX: float = 44.0
TIDY_MAX_COLUMNS: int = 6

#: Margin added around the selection bounds by :func:`fit_selection`.
FIT_MARGIN_PX: float = 120.0


class SelectionTraversal(Enum):
    """How far a selection should be expanded through the graph."""

    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    CONNECTED = "connected"


# ---------------------------------------------------------------------------
# Pure helpers (no Qt widgets — unit-testable in isolation)
# ---------------------------------------------------------------------------

def traversal_ids(
    connections: Iterable[Connection],
    seed_ids: Iterable[str],
    traversal: SelectionTraversal,
) -> set[str]:
    """Return ``seed_ids`` plus every node reachable in ``traversal`` order.

    Parameters:
        connections: Project connections describing the flow graph.
        seed_ids: Node ids the walk starts from (always included).
        traversal: Whether to walk against the flow, with the flow, or both.

    Returns:
        The set of node ids that should end up selected.
    """
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for connection in connections:
        forward.setdefault(connection.output_node_id, set()).add(
            connection.input_node_id
        )
        backward.setdefault(connection.input_node_id, set()).add(
            connection.output_node_id
        )

    def neighbours(node_id: str) -> set[str]:
        if traversal is SelectionTraversal.UPSTREAM:
            return backward.get(node_id, set())
        if traversal is SelectionTraversal.DOWNSTREAM:
            return forward.get(node_id, set())
        return forward.get(node_id, set()) | backward.get(node_id, set())

    visited: set[str] = {str(seed) for seed in seed_ids}
    queue: list[str] = list(visited)
    while queue:
        current = queue.pop()
        for neighbour in neighbours(current):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            queue.append(neighbour)
    return visited


def next_bypass_state(states: Sequence[bool]) -> bool:
    """Return the shared ``enabled`` value a selection should move to.

    A mixed or fully-bypassed selection turns back on; only a selection that is
    completely live gets bypassed, which matches how the toggle reads to a user.
    """
    if not states:
        return True
    return not all(bool(state) for state in states)


def tidy_columns(count: int, *, max_columns: int = TIDY_MAX_COLUMNS) -> int:
    """Return a pleasant column count for packing ``count`` nodes."""
    if count <= 0:
        return 0
    if count <= 3:
        return count
    limit = max(1, max_columns)
    columns = 1
    while columns < limit and columns * columns < count:
        columns += 1
    return min(columns, count)


def grid_positions(
    sizes: Sequence[tuple[float, float]],
    *,
    columns: int,
    column_gap: float,
    row_gap: float,
) -> list[tuple[float, float]]:
    """Return top-left offsets packing ``sizes`` into a column-major grid.

    Column widths and row heights follow the largest item they contain, so
    differently sized nodes never overlap.
    """
    if not sizes:
        return []
    count = len(sizes)
    cols = max(1, min(int(columns), count))
    rows = (count + cols - 1) // cols

    column_widths: list[float] = [0.0] * cols
    row_heights: list[float] = [0.0] * rows
    for index, (width, height) in enumerate(sizes):
        column = index % cols
        row = index // cols
        column_widths[column] = max(column_widths[column], float(width))
        row_heights[row] = max(row_heights[row], float(height))

    column_offsets: list[float] = []
    x = 0.0
    for width in column_widths:
        column_offsets.append(x)
        x += width + float(column_gap)
    row_offsets: list[float] = []
    y = 0.0
    for height in row_heights:
        row_offsets.append(y)
        y += height + float(row_gap)

    return [
        (column_offsets[index % cols], row_offsets[index // cols])
        for index in range(count)
    ]


def selection_bounds(items: Sequence[NodeItem]) -> QRectF | None:
    """Return the scene-space union of ``items``, or ``None`` when empty."""
    if not items:
        return None
    bounds = QRectF(items[0].sceneBoundingRect())
    for item in items[1:]:
        bounds = bounds.united(item.sceneBoundingRect())
    return bounds


# ---------------------------------------------------------------------------
# Selection expansion
# ---------------------------------------------------------------------------

def invert_selection(view: NodeGraphView) -> int:
    """Select every unselected node and deselect the rest. Returns the count."""
    items = list(view.node_items.values())
    invert: list[NodeItem] = [item for item in items if not item.isSelected()]
    view.scene.clearSelection()
    for item in invert:
        item.setSelected(True)
    return len(invert)


def select_related(view: NodeGraphView, traversal: SelectionTraversal) -> int:
    """Grow the selection along the graph to connected nodes."""
    seeds = [item.node_id for item in view.selected_nodes()]
    if not seeds:
        return 0
    return _select_ids(
        view,
        traversal_ids(view.project.connections, seeds, traversal),
    )


def select_same_type(view: NodeGraphView) -> int:
    """Select every node that shares a type with the current selection."""
    types = {
        node.node_type
        for node_id in (item.node_id for item in view.selected_nodes())
        if (node := view.project.nodes.get(node_id)) is not None
    }
    if not types:
        return 0
    matches = {
        node_id
        for node_id, node in view.project.nodes.items()
        if node.node_type in types
    }
    return _select_ids(view, matches)


def _select_ids(view: NodeGraphView, node_ids: Iterable[str]) -> int:
    """Replace the selection with the graph items matching ``node_ids``."""
    view.scene.clearSelection()
    selected = 0
    for node_id in node_ids:
        item = view.node_items.get(node_id)
        if item is None:
            continue
        item.setSelected(True)
        selected += 1
    return selected


# ---------------------------------------------------------------------------
# Geometry quick actions
# ---------------------------------------------------------------------------

def nudge_selection(
    view: NodeGraphView,
    items: Sequence[NodeItem],
    dx: float,
    dy: float,
) -> bool:
    """Translate the selection by a scene-space delta as one undo step."""
    if not items or (abs(dx) < 1e-6 and abs(dy) < 1e-6):
        return False
    before: dict[str, tuple[float, float]] = {}
    after: dict[str, tuple[float, float]] = {}
    for item in items:
        x = float(item.pos().x())
        y = float(item.pos().y())
        before[item.node_id] = (x, y)
        after[item.node_id] = (x + float(dx), y + float(dy))
    return view.history.push(MoveNodesCommand(before, after))


def tidy_selection(
    view: NodeGraphView,
    items: Sequence[NodeItem],
    *,
    columns: int | None = None,
) -> bool:
    """Pack the selection into a compact grid, preserving reading order."""
    if len(items) < 2:
        return False
    ordered = sorted(items, key=lambda item: (item.pos().y(), item.pos().x()))
    sizes = [
        (float(item.rect().width()), float(item.rect().height()))
        for item in ordered
    ]
    column_count = (
        tidy_columns(len(ordered)) if columns is None else max(1, int(columns))
    )
    offsets = grid_positions(
        sizes,
        columns=column_count,
        column_gap=TIDY_COLUMN_GAP_PX,
        row_gap=TIDY_ROW_GAP_PX,
    )
    origin_x = min(float(item.pos().x()) for item in ordered)
    origin_y = min(float(item.pos().y()) for item in ordered)

    before: dict[str, tuple[float, float]] = {}
    after: dict[str, tuple[float, float]] = {}
    for item, (offset_x, offset_y) in zip(ordered, offsets):
        before[item.node_id] = (float(item.pos().x()), float(item.pos().y()))
        after[item.node_id] = (origin_x + offset_x, origin_y + offset_y)
    return view.history.push(MoveNodesCommand(before, after))


def fit_selection(
    view: NodeGraphView,
    items: Sequence[NodeItem],
    *,
    margin: float = FIT_MARGIN_PX,
) -> bool:
    """Zoom the canvas so the selection fills the viewport."""
    bounds = selection_bounds(items)
    if bounds is None or bounds.isEmpty():
        return False
    padded = bounds.adjusted(-margin, -margin, margin, margin)
    view.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)
    return True


# ---------------------------------------------------------------------------
# Document quick actions
# ---------------------------------------------------------------------------

def toggle_selection_bypass(
    view: NodeGraphView,
    items: Sequence[NodeItem],
) -> int:
    """Flip the ``enabled`` toggle on every bypassable selected node."""
    targets: list[tuple[str, bool]] = []
    for item in items:
        node = view.project.nodes.get(item.node_id)
        if node is None:
            continue
        prop = node.get_property(BYPASS_PROPERTY)
        if prop is None:
            continue
        targets.append((item.node_id, bool(prop.value)))
    if not targets:
        return 0

    enabled = next_bypass_state([state for _, state in targets])
    commands = [
        SetPropertyCommand(node_id, BYPASS_PROPERTY, enabled)
        for node_id, _ in targets
    ]
    label = (
        f"Enable {len(commands)} Node" if enabled else f"Bypass {len(commands)} Node"
    )
    if len(commands) > 1:
        label += "s"
    view.history.push(
        commands[0] if len(commands) == 1 else CompositeCommand(commands, label)
    )
    return len(commands)


def remove_selection_wires(
    view: NodeGraphView,
    items: Sequence[NodeItem],
) -> int:
    """Disconnect every wire touching the selection, in one undo step."""
    node_ids = {item.node_id for item in items}
    if not node_ids:
        return 0
    wires = [
        connection
        for connection in view.project.connections
        if connection.output_node_id in node_ids or connection.input_node_id in node_ids
    ]
    if not wires:
        return 0
    commands = [DisconnectCommand(wire) for wire in wires]
    if len(commands) == 1:
        view.history.push(commands[0])
    else:
        view.history.push(
            CompositeCommand(commands, f"Disconnect {len(commands)} Wires")
        )
    return len(commands)
