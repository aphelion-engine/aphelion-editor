from dataclasses import dataclass

from core.node import Node


@dataclass
class NodeInfo:
    node_class: type[Node]
    category: str
    name: str
    description: str = ""
    color: tuple[int, int, int] = (100, 100, 100)

    def create_instance(self, *args, **kwargs) -> Node:
        return self.node_class(*args, **kwargs)


class NodeRegistry:
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

        info = NodeInfo(node_class, category, name, description, color)

        self._nodes[key] = info

        if category not in self._categories:
            self._categories[category] = []

        self._categories[category].append(name)

    def get_categories(self) -> list[str]:
        return self._categories.keys() # type: ignore

    def get_nodes_in_category(self, category: str) -> list[str]:
        return self._categories.get(category, [])

    def get_node_info(self, category: str, name: str) -> NodeInfo | None:
        key = f"{category}.{name}"
        return self._nodes.get(key)

    def create_node(self, name: str, category: str | None = None) -> Node | None:
        for n in self._nodes.values():
            if n.name == name:
                info = self.get_node_info(category or n.category, n.name)
                if info:
                    return info.create_instance()
        return None

    def get_all_nodes(self) -> dict[str, NodeInfo]:
        return self._nodes.copy()


global_node_registry = NodeRegistry()
