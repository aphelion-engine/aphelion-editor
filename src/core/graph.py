"""High-performance dependency graph for project evaluation."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from core.cache import FrameCache
from core.events import Connection

if TYPE_CHECKING:
    from core.nodes import Node


class DependencyGraph:
    """Precomputed dependency graph used by the frame evaluator.

    The graph is rebuilt only when connections change.

    Runtime frame evaluation should therefore perform simple dictionary
    lookups rather than traversing the project graph repeatedly.
    """

    __slots__ = (
        "nodes",
        "connections",
        "cache",
        "_downstream",
        "_upstream_inputs",
        "_input_by_slot",
        "_topological_order",
        "_topological_index",
    )

    def __init__(
        self,
        nodes: dict[str, Node],
        connections: set[Connection],
        cache: FrameCache | None = None,
    ) -> None:
        self.nodes = nodes
        self.connections = connections
        self.cache = cache or FrameCache()

        self._downstream: dict[
            str,
            list[str],
        ] = {}

        self._upstream_inputs: dict[
            str,
            list[Connection],
        ] = {}

        self._input_by_slot: dict[
            str,
            dict[str, Connection],
        ] = {}

        self._topological_order: list[str] = []
        self._topological_index: dict[
            str,
            int,
        ] = {}

        self._rebuild_adjacency()

    # ==================================================================
    # Graph construction
    # ==================================================================

    def _rebuild_adjacency(self) -> None:
        """Build all runtime lookup tables in one pass."""

        downstream: dict[
            str,
            list[str],
        ] = defaultdict(list)

        upstream: dict[
            str,
            list[Connection],
        ] = defaultdict(list)

        input_by_slot: dict[
            str,
            dict[str, Connection],
        ] = defaultdict(dict)

        for conn in self.connections:
            output_id = conn.output_node_id
            input_id = conn.input_node_id
            input_slot = conn.input_slot

            downstream[output_id].append(
                input_id
            )

            upstream[input_id].append(
                conn
            )

            input_by_slot[input_id][
                input_slot
            ] = conn

        self._downstream = dict(
            downstream
        )

        self._upstream_inputs = dict(
            upstream
        )

        self._input_by_slot = {
            node_id: dict(slots)
            for node_id, slots
            in input_by_slot.items()
        }

        self._build_topological_order()

    def update(
        self,
        nodes: dict[str, Node],
        connections: set[Connection],
    ) -> None:
        """Refresh graph structure while preserving frame cache."""

        self.nodes = nodes
        self.connections = connections

        self._rebuild_adjacency()

    # ==================================================================
    # Topological order
    # ==================================================================

    def _build_topological_order(self) -> None:
        """Build a topological ordering of the current graph.

        The graph is expected to be acyclic because Project.connect_nodes()
        rejects cycles.

        Kahn's algorithm is used here so the result is O(V + E).
        """

        nodes = self.nodes
        downstream = self._downstream

        indegree: dict[str, int] = {
            node_id: 0
            for node_id in nodes
        }

        for output_id, children in downstream.items():
            if output_id not in nodes:
                continue

            for child_id in children:
                if child_id in indegree:
                    indegree[child_id] += 1

        queue = [
            node_id
            for node_id, degree in indegree.items()
            if degree == 0
        ]

        order: list[str] = []

        index = 0

        while index < len(queue):
            node_id = queue[index]
            index += 1

            order.append(node_id)

            for child_id in downstream.get(
                node_id,
                (),
            ):
                if child_id not in indegree:
                    continue

                indegree[child_id] -= 1

                if indegree[child_id] == 0:
                    queue.append(child_id)

        # If something somehow slipped through the cycle validation,
        # don't silently lose nodes.
        if len(order) != len(nodes):
            seen = set(order)

            for node_id in nodes:
                if node_id not in seen:
                    order.append(node_id)

        self._topological_order = order

        self._topological_index = {
            node_id: index
            for index, node_id in enumerate(order)
        }

    def get_topological_order(
        self,
    ) -> tuple[str, ...]:
        """Return the precomputed graph execution order."""

        return tuple(
            self._topological_order
        )

    def get_topological_index(
        self,
        node_id: str,
    ) -> int:
        """Return a node's topological position."""

        return self._topological_index.get(
            node_id,
            -1,
        )

    # ==================================================================
    # Adjacency
    # ==================================================================

    def get_downstream_nodes(
        self,
        node_id: str,
    ) -> list[str]:
        """Return all downstream nodes.

        This remains recursive because callers use it for cache
        invalidation and cycle checks rather than per-frame evaluation.
        """

        downstream = self._downstream

        result: list[str] = []
        visited: set[str] = set()

        stack = [node_id]

        while stack:
            current = stack.pop()

            if current in visited:
                continue

            visited.add(current)

            for child_id in downstream.get(
                current,
                (),
            ):
                if child_id in visited:
                    continue

                result.append(child_id)
                stack.append(child_id)

        return result

    def get_input_connections(
        self,
        node_id: str,
    ) -> list[Connection]:
        """Return precomputed upstream connections."""

        return self._upstream_inputs.get(
            node_id,
            (),
        )

    def get_input_connection(
        self,
        node_id: str,
        input_slot: str,
    ) -> Connection | None:
        """Return one input connection directly by socket name."""

        return (
            self._input_by_slot
            .get(node_id, {})
            .get(input_slot)
        )

    # ==================================================================
    # Cache
    # ==================================================================

    def get_cached(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str,
    ):
        """Thread-safe cache access."""

        return self.cache.get(
            (
                node_id,
                frame_num,
                output_slot,
            )
        )

    def get_cached_fast(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str,
    ):
        """Fast cache access for Project evaluation.

        Project.evaluate_node() already owns the project evaluation lock,
        so taking another lock around every cache lookup is unnecessary.
        """

        return self.cache.get_fast(
            (
                node_id,
                frame_num,
                output_slot,
            )
        )

    def set_cached(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str,
        value,
    ) -> None:
        """Thread-safe cache write."""

        self.cache.set(
            (
                node_id,
                frame_num,
                output_slot,
            ),
            value,
        )

    def set_cached_fast(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str,
        value,
    ) -> None:
        """Fast cache write for Project evaluation."""

        self.cache.set_fast(
            (
                node_id,
                frame_num,
                output_slot,
            ),
            value,
        )

    # ==================================================================
    # Invalidation
    # ==================================================================

    def invalidate_node(
        self,
        node_id: str,
    ) -> None:
        """Invalidate a node and everything downstream."""

        cache = self.cache

        cache.invalidate_node(
            node_id
        )

        downstream = self._downstream

        visited: set[str] = set()
        stack = list(
            downstream.get(
                node_id,
                (),
            )
        )

        while stack:
            current = stack.pop()

            if current in visited:
                continue

            visited.add(current)

            cache.invalidate_node(
                current
            )

            stack.extend(
                downstream.get(
                    current,
                    (),
                )
            )

    def clear_cache(self) -> None:
        self.cache.clear()
