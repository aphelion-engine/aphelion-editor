"""Registers built-in node types into the global registry."""

from typing import ClassVar

from core.nodes import Node, global_node_registry
from core.nodes.catalog import BUILTIN_NODE_TYPES


class NodeLoader:
    """Bootstraps default node classes into ``global_node_registry``."""

    default_nodes: ClassVar[tuple[type[Node], ...]] = BUILTIN_NODE_TYPES

    @staticmethod
    def load_defaults() -> None:
        """Register all default node classes."""
        for node_class in NodeLoader.default_nodes:
            global_node_registry.register(
                node_class,
                node_class.node_category,
                node_class.node_type,
                node_class.node_description,
                node_class.node_color,
            )
