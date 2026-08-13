"""In-memory clipboard for node graph copy / paste."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.events import Connection
from core.history.snapshots import NodeSnapshot
from core.project import Project


@dataclass
class GraphClipboard:
    """Stores node snapshots and wires that stay inside the copied set."""

    snapshots: list[NodeSnapshot] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.snapshots

    def clear(self) -> None:
        self.snapshots.clear()
        self.connections.clear()

    def capture(self, project: Project, node_ids: list[str]) -> bool:
        """Snapshot ``node_ids`` with positions normalized to a (0, 0) origin.

        Parameters:
            project: Active project providing nodes and connections.
            node_ids: Selected node identifiers to copy.

        Returns:
            ``True`` when at least one node was captured.
        """
        unique_ids = list(dict.fromkeys(node_ids))
        if not unique_ids:
            self.clear()
            return False

        id_set = set(unique_ids)
        snapshots: list[NodeSnapshot] = []
        for node_id in unique_ids:
            node = project.nodes.get(node_id)
            if node is None:
                continue
            snapshots.append(NodeSnapshot.from_node(node_id, node))

        if not snapshots:
            self.clear()
            return False

        min_x = min(snap.x for snap in snapshots)
        min_y = min(snap.y for snap in snapshots)
        normalized: list[NodeSnapshot] = [
            NodeSnapshot(
                node_id=snap.node_id,
                node_type=snap.node_type,
                node_category=snap.node_category,
                name=snap.name,
                x=snap.x - min_x,
                y=snap.y - min_y,
                properties=dict(snap.properties),
            )
            for snap in snapshots
        ]

        internal = [
            conn
            for conn in project.connections
            if conn.output_node_id in id_set and conn.input_node_id in id_set
        ]

        self.snapshots = normalized
        self.connections = list(internal)
        return True
