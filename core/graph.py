"""Dependency graph with precomputed adjacency for fast evaluation."""

from __future__ import annotations

from collections import defaultdict

from core.cache import FrameCache
from core.events import Connection
from core.nodes import Node


class DependencyGraph:
    """Tracks node connections and provides cached upstream/downstream lookups."""

    def __init__(
        self,
        nodes: dict[str, Node],
        connections: set[Connection],
        cache: FrameCache | None = None,
    ) -> None:
        self.nodes = nodes
        self.connections = connections
        self.cache = cache or FrameCache()
        self._downstream: dict[str, list[str]] = defaultdict(list)
        self._upstream_inputs: dict[str, list[Connection]] = defaultdict(list)
        self._rebuild_adjacency()

    def _rebuild_adjacency(self) -> None:
        self._downstream = defaultdict(list)
        self._upstream_inputs = defaultdict(list)

        for conn in self.connections:
            self._downstream[conn.output_node_id].append(conn.input_node_id)
            self._upstream_inputs[conn.input_node_id].append(conn)

    def update(self, nodes: dict[str, Node], connections: set[Connection]) -> None:
        """Refresh graph structure while preserving the frame cache."""
        self.nodes = nodes
        self.connections = connections
        self._rebuild_adjacency()

    def get_downstream_nodes(self, node_id: str) -> list[str]:
        downstream: list[str] = []
        visited: set[str] = set()

        def traverse(nid: str) -> None:
            if nid in visited:
                return
            visited.add(nid)
            for child_id in self._downstream.get(nid, []):
                downstream.append(child_id)
                traverse(child_id)

        traverse(node_id)
        return downstream

    def get_input_connections(self, node_id: str) -> list[Connection]:
        return self._upstream_inputs.get(node_id, [])

    def invalidate_node(self, node_id: str) -> None:
        self.cache.invalidate_node(node_id)
        for downstream_id in self.get_downstream_nodes(node_id):
            self.cache.invalidate_node(downstream_id)

    def get_cached(self, node_id: str, frame_num: int, output_slot: str):
        return self.cache.get((node_id, frame_num, output_slot))

    def set_cached(self, node_id: str, frame_num: int, output_slot: str, value) -> None:
        self.cache.set((node_id, frame_num, output_slot), value)

    def clear_cache(self) -> None:
        self.cache.clear()
