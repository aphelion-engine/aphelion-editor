"""Global node type registry."""

from __future__ import annotations

from dataclasses import dataclass

from core.nodes.base import Node


@dataclass
class NodeInfo:
    node_class: type[Node]
    category: str
    name: str
    description: str = ""
    color: tuple[int, int, int] = (100, 100, 100)

    def create_instance(self, *args: object, **kwargs: object) -> Node:
        return self.node_class(*args, **kwargs)


class NodeRegistry:
    """Stores available node types keyed by category and name."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeInfo] = {}
        self._categories: dict[str, list[str]] = {}

    def register(
        self,
        node_class: type[Node],
        category: str,
        name: str,
        description: str = "",
        color: tuple[int, int, int] = (100, 100, 100),
    ) -> None:
        key = f"{category}.{name}"
        self._nodes[key] = NodeInfo(node_class, category, name, description, color)
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(name)

    def get_categories(self) -> list[str]:
        return list(self._categories.keys())

    def get_nodes_in_category(self, category: str) -> list[str]:
        return self._categories.get(category, [])

    def get_node_info(self, category: str, name: str) -> NodeInfo | None:
        return self._nodes.get(f"{category}.{name}")

    def create_node(self, name: str, category: str | None = None) -> Node | None:
        for info in self._nodes.values():
            if info.name != name:
                continue
            resolved = self.get_node_info(category or info.category, info.name)
            if resolved is not None:
                return resolved.create_instance()
        return None

    def get_all_nodes(self) -> dict[str, NodeInfo]:
        return self._nodes.copy()


global_node_registry = NodeRegistry()
