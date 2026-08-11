"""Serializable snapshots used to restore nodes after undo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.events import Connection
from core.nodes import Node, global_node_registry
from core.nodes.base import NodeProperty


@dataclass(frozen=True)
class NodeSnapshot:
    """Enough data to recreate a node with a stable id."""

    node_id: str
    node_type: str
    node_category: str
    name: str
    x: float
    y: float
    properties: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_node(cls, node_id: str, node: Node) -> NodeSnapshot:
        props: dict[str, Any] = {}
        for key, prop in node.properties.items():
            if key.startswith("_input_"):
                continue
            if isinstance(prop, NodeProperty):
                props[key] = prop.value
        return cls(
            node_id=node_id,
            node_type=node.node_type,
            node_category=node.node_category,
            name=node.name,
            x=float(node.x),
            y=float(node.y),
            properties=props,
        )

    def create_node(self) -> Node | None:
        """Instantiate a fresh node matching this snapshot."""
        node = global_node_registry.create_node(
            self.node_type,
            category=self.node_category,
        )
        if node is None:
            return None
        node.name = self.name
        node.x = self.x
        node.y = self.y
        for key, value in self.properties.items():
            node.set_property(key, value)
        return node


def connections_touching(
    connections: set[Connection],
    node_ids: set[str],
) -> list[Connection]:
    """Return connections that reference any id in ``node_ids``."""
    return [
        conn
        for conn in connections
        if conn.output_node_id in node_ids or conn.input_node_id in node_ids
    ]
