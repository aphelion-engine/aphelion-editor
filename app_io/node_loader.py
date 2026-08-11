"""Registers built-in node types into the global registry."""

from typing import ClassVar

from core.nodes import Node, VideoInputNode, ViewerNode, global_node_registry


class NodeLoader:
    """Bootstraps default node classes into ``global_node_registry``."""

    default_nodes: ClassVar[list[type[Node]]] = [
        VideoInputNode,
        ViewerNode,
    ]

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
