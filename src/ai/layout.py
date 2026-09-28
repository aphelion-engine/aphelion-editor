"""Graph layout for AI-created nodes.

A workflow the assistant builds should look designed, not scattered. This
module computes positions for *only* the nodes the assistant touched, so the
result satisfies the two rules that matter most:

* generated nodes flow left to right in the order data actually moves, and
* the user's existing layout is left exactly as it was.

Nothing here moves a node the user placed. New nodes are inserted into the
space next to whatever they connect to, and if that space is taken the engine
finds the nearest free slot rather than pushing someone else's work aside.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

#: Default node footprint (px) when a node does not report its own size.
DEFAULT_NODE_WIDTH: float = 220.0
DEFAULT_NODE_HEIGHT: float = 140.0


@dataclass(frozen=True)
class LayoutMetrics:
    """Spacing rules for generated layouts."""

    #: Horizontal gap between a node and the node it feeds.
    column_gap: float = 300.0
    #: Vertical step used when a lane is already occupied.
    row_gap: float = 170.0
    #: Vertical offset applied to sibling branches off the same node.
    lane_gap: float = 90.0
    #: Minimum clearance kept around every node.
    clearance: float = 40.0
    #: How many vertical slots to try before starting a new column.
    max_slots: int = 40
    #: Where a graph with no content starts.
    origin_x: float = 80.0
    origin_y: float = 80.0


Rect = tuple[float, float, float, float]  # x, y, x2, y2


def _size(node: Any) -> tuple[float, float]:
    width = float(getattr(node, "width", 0) or DEFAULT_NODE_WIDTH)
    height = float(getattr(node, "height", 0) or DEFAULT_NODE_HEIGHT)
    if width <= 1:
        width = DEFAULT_NODE_WIDTH
    if height <= 1:
        height = DEFAULT_NODE_HEIGHT
    return width, height


def _rect(x: float, y: float, width: float, height: float, clearance: float) -> Rect:
    return (x - clearance, y - clearance, x + width + clearance, y + height + clearance)


def _overlaps(a: Rect, b: Rect) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


class AIGraphLayoutEngine:
    """Computes clean positions for a set of nodes."""

    def __init__(self, metrics: LayoutMetrics | None = None) -> None:
        self.metrics = metrics or LayoutMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def place(
        self,
        project: Any,
        node_ids: Iterable[str],
        *,
        respect: Iterable[str] | None = None,
    ) -> dict[str, tuple[float, float]]:
        """Return new positions for ``node_ids`` only.

        Args:
            project: the live project.
            node_ids: nodes to position (normally newly created ones).
            respect: extra node ids to treat as fixed obstacles (defaults to
                every node in the project that is not being positioned).

        Returns:
            ``{node_id: (x, y)}`` for the nodes that need to move.
        """
        targets = [nid for nid in node_ids if nid in project.nodes]
        if not targets:
            return {}
        target_set = set(targets)
        fixed = set(respect) if respect is not None else set(project.nodes)
        fixed -= target_set

        occupied: list[Rect] = []
        for node_id in fixed:
            node = project.nodes.get(node_id)
            if node is None:
                continue
            width, height = _size(node)
            occupied.append(
                _rect(
                    float(node.x),
                    float(node.y),
                    width,
                    height,
                    self.metrics.clearance,
                )
            )

        connections = list(project.connections)
        positions: dict[str, tuple[float, float]] = {}
        ordered = self._order(targets, connections)

        for index, node_id in enumerate(ordered):
            node = project.nodes[node_id]
            width, height = _size(node)
            proposed = self._anchor_position(
                project, node_id, connections, positions, target_set, index
            )
            x, y = self._free_slot(proposed, width, height, occupied)
            positions[node_id] = (x, y)
            occupied.append(_rect(x, y, width, height, self.metrics.clearance))

        return positions

    def plan_moves(
        self,
        project: Any,
        node_ids: Iterable[str],
        *,
        respect: Iterable[str] | None = None,
    ) -> dict[str, tuple[float, float]]:
        """Positions for the target nodes that actually need to change."""
        moves: dict[str, tuple[float, float]] = {}
        for node_id, (x, y) in self.place(project, node_ids, respect=respect).items():
            node = project.nodes.get(node_id)
            if node is None:
                continue
            if (round(float(node.x)), round(float(node.y))) != (round(x), round(y)):
                moves[node_id] = (x, y)
        return moves

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _order(self, targets: list[str], connections: list[Any]) -> list[str]:
        """Topologically order the targets so upstream nodes are placed first."""
        target_set = set(targets)
        incoming: dict[str, int] = {node_id: 0 for node_id in targets}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in targets}
        for connection in connections:
            source = str(getattr(connection, "output_node_id", "") or "")
            sink = str(getattr(connection, "input_node_id", "") or "")
            if source in target_set and sink in target_set:
                outgoing[source].append(sink)
                incoming[sink] = incoming.get(sink, 0) + 1

        ready = sorted(node_id for node_id in targets if incoming.get(node_id, 0) == 0)
        result: list[str] = []
        while ready:
            node_id = ready.pop(0)
            result.append(node_id)
            for sink in outgoing.get(node_id, []):
                incoming[sink] -= 1
                if incoming[sink] == 0:
                    ready.append(sink)
            ready.sort()
        # Cycles (or disconnected leftovers) keep a stable alphabetical tail
        # instead of being dropped.
        result.extend(sorted(node_id for node_id in targets if node_id not in result))
        return result

    def _anchor_position(
        self,
        project: Any,
        node_id: str,
        connections: list[Any],
        positions: dict[str, tuple[float, float]],
        target_set: set[str],
        index: int,
    ) -> tuple[float, float]:
        """Where a node wants to be, before collision resolution."""
        metrics = self.metrics
        upstream: list[str] = []
        downstream: list[str] = []
        for connection in connections:
            source = str(getattr(connection, "output_node_id", "") or "")
            sink = str(getattr(connection, "input_node_id", "") or "")
            if sink == node_id and source and source != node_id:
                upstream.append(source)
            if source == node_id and sink and sink != node_id:
                downstream.append(sink)

        anchor = self._first_anchored(upstream, positions, project, target_set)
        if anchor is not None:
            anchor_id, anchor_x, anchor_y = anchor
            width, _height = _size(project.nodes[anchor_id])
            siblings = self._sibling_count(anchor_id, downstream, connections)
            y = anchor_y + siblings * metrics.lane_gap
            return anchor_x + width + metrics.column_gap, y

        anchor = self._first_anchored(downstream, positions, project, target_set)
        if anchor is not None:
            anchor_id, anchor_x, anchor_y = anchor
            width, _height = _size(project.nodes[node_id])
            return anchor_x - metrics.column_gap - width, anchor_y

        # Nothing to attach to: continue the flow to the right of everything.
        right_edge, top_edge = self._content_extent(project, target_set)
        width, _height = _size(project.nodes[node_id])
        if right_edge is None:
            return (
                metrics.origin_x + index * (DEFAULT_NODE_WIDTH + metrics.column_gap),
                metrics.origin_y + index * metrics.lane_gap,
            )
        return right_edge + metrics.column_gap, float(top_edge or metrics.origin_y)

    def _first_anchored(
        self,
        candidates: list[str],
        positions: dict[str, tuple[float, float]],
        project: Any,
        target_set: set[str],
    ) -> tuple[str, float, float] | None:
        """The first candidate whose position is known (placed or pre-existing)."""
        for candidate in candidates:
            if candidate in positions:
                x, y = positions[candidate]
                return candidate, x, y
            node = project.nodes.get(candidate)
            if node is not None and candidate not in target_set:
                return candidate, float(node.x), float(node.y)
        return None

    @staticmethod
    def _sibling_count(anchor_id: str, downstream: list[str], connections: list[Any]) -> int:
        """How many other moved nodes already hang off ``anchor_id``."""
        count = 0
        for connection in connections:
            if str(getattr(connection, "output_node_id", "") or "") == anchor_id:
                if str(getattr(connection, "input_node_id", "") or "") in downstream:
                    count += 1
        return max(0, count - 1)

    @staticmethod
    def _content_extent(
        project: Any, target_set: set[str]
    ) -> tuple[float | None, float | None]:
        right_edge: float | None = None
        top_edge: float | None = None
        for node_id, node in project.nodes.items():
            if node_id in target_set:
                continue
            width, _height = _size(node)
            edge = float(node.x) + width
            right_edge = edge if right_edge is None else max(right_edge, edge)
            y = float(node.y)
            top_edge = y if top_edge is None else min(top_edge, y)
        return right_edge, top_edge

    def _free_slot(
        self,
        proposed: tuple[float, float],
        width: float,
        height: float,
        occupied: list[Rect],
    ) -> tuple[float, float]:
        """Step vertically until the node no longer collides with anything."""
        metrics = self.metrics
        x, y = proposed
        for slot in range(metrics.max_slots):
            candidate = _rect(x, y, width, height, metrics.clearance)
            if not any(_overlaps(candidate, other) for other in occupied):
                return x, y
            y += metrics.row_gap
        # Nothing free in this column: start a fresh column well clear of it.
        far_right = max((rect[2] for rect in occupied), default=x + width)
        return far_right + metrics.column_gap, proposed[1]


def layout_new_nodes(
    project: Any,
    new_node_ids: Iterable[str],
    *,
    metrics: LayoutMetrics | None = None,
) -> dict[str, tuple[float, float]]:
    """Convenience wrapper: positions for newly created nodes."""
    return AIGraphLayoutEngine(metrics).plan_moves(project, new_node_ids)


__all__ = [
    "AIGraphLayoutEngine",
    "LayoutMetrics",
    "layout_new_nodes",
]
