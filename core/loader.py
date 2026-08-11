from typing import ClassVar 

from core.node_registry import global_node_registry
from core.node import (
    Node,
    VideoInputNode,
    ViewerNode
)

class Loader:
    
    default_nodes: ClassVar[list[type[Node]]] = [
        VideoInputNode,
        ViewerNode
    ]
    
    @staticmethod
    def add_node_class_to_defaults(node_class: type[Node]) -> None:
        Loader.default_nodes.append(node_class)
        
    @staticmethod
    def load_defaults_into_node_registry() -> None:
        for node_class in Loader.default_nodes:
            global_node_registry.register(
                node_class, 
                node_class.node_category, 
                node_class.node_type,
                node_class.node_description,
                node_class.node_color
            )
    
            