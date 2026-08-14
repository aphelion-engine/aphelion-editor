"""Global node type registry."""

from __future__ import annotations

from dataclasses import dataclass

from core.nodes.base import Node


@dataclass(frozen=True, slots=True)
class NodeInfo:
    """Registration metadata for one creatable node type."""

    node_class: type[Node]
    category: str
    name: str
    description: str = ""
    color: tuple[int, int, int] = (100, 100, 100)

    def create_instance(self) -> Node:
        """Construct a default instance of this registered type."""
        return self.node_class()


class NodeRegistry:
    """Stores available node types keyed by category and name."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeInfo] = {}
        self._categories: dict[str, list[str]] = {}
        self._color_overrides: dict[str, tuple[int, int, int]] = {}

    def set_color_overrides(
        self,
        overrides: dict[str, tuple[int, int, int]],
    ) -> None:
        """Replace user-defined node header color overrides."""
        self._color_overrides = dict(overrides)

    def color_overrides(self) -> dict[str, tuple[int, int, int]]:
        """Return a copy of active node color overrides."""
        return dict(self._color_overrides)

    def resolve_color(self, category: str, name: str) -> tuple[int, int, int]:
        """Return override, registered, or default color for a node type."""
        key = f"{category}.{name}"
        override = self._color_overrides.get(key)
        if override is not None:
            return override
        info = self.get_node_info(category, name)
        if info is not None:
            return info.color
        return (100, 100, 100)

    def register(
        self,
        node_class: type[Node],
        category: str,
        name: str,
        description: str = "",
        color: tuple[int, int, int] = (100, 100, 100),
    ) -> None:
        """Register a creatable node type, replacing any existing same key.

        Parameters:
            node_class: Concrete ``Node`` subclass to construct.
            category: Menu group shown in Add Node.
            name: Display name and type id within ``category``.
            description: Tooltip / search text.
            color: Default header RGB.

        Side effects:
            Mutates the in-memory registry.
        """
        key = f"{category}.{name}"
        self._nodes[key] = NodeInfo(node_class, category, name, description, color)
        if category not in self._categories:
            self._categories[category] = []
        if name not in self._categories[category]:
            self._categories[category].append(name)

    def unregister(self, category: str, name: str) -> bool:
        """Remove a registered node type.

        Parameters:
            category: Menu group the type was registered under.
            name: Display name / type id within ``category``.

        Returns:
            ``True`` when a type was removed; ``False`` if it was not registered.

        Side effects:
            Drops the type from lookup tables. Existing node instances are unchanged.
        """
        key = f"{category}.{name}"
        if key not in self._nodes:
            return False
        del self._nodes[key]
        names = self._categories.get(category, [])
        if name in names:
            names.remove(name)
        if not names:
            self._categories.pop(category, None)
        return True

    def get_categories(self) -> list[str]:
        return list(self._categories.keys())

    def get_nodes_in_category(self, category: str) -> list[str]:
        return self._categories.get(category, [])

    def get_node_info(self, category: str, name: str) -> NodeInfo | None:
        return self._nodes.get(f"{category}.{name}")

    def create_node(self, name: str, category: str | None = None) -> Node | None:
        """Create a node by exact category or unique-name fallback.

        The fallback keeps older project files loadable when a built-in node
        moves to a more precise category.
        """
        if category is not None:
            exact: NodeInfo | None = self.get_node_info(category, name)
            if exact is not None:
                node = exact.create_instance()
                node.node_color = self.resolve_color(category, name)
                return node
        matches: list[NodeInfo] = [
            info for info in self._nodes.values() if info.name == name
        ]
        if len(matches) == 1:
            info = matches[0]
            node = info.create_instance()
            node.node_color = self.resolve_color(info.category, info.name)
            return node
        return None

    def get_all_nodes(self) -> dict[str, NodeInfo]:
        return self._nodes.copy()


global_node_registry = NodeRegistry()
