
from PyQt6.QtWidgets import QMenu, QWidget
from PyQt6.QtCore import pyqtSignal, QPoint, QPointF
from core.node_registry import global_node_registry
from core.project import Project

class NodeContextMenu(QMenu):
    
    node_selected = pyqtSignal(str, str, QPointF)
    
    def __init__(
        self, 
        project: Project, 
        position: QPoint, 
        parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.project = project 
        self.position = position
        self.setWindowTitle("Add Node")
        
        self._populate_menu()
    
    def _populate_menu(self) -> None:
        for category in global_node_registry.get_categories():
            category_menu = self.addMenu(category)
            assert category_menu is not None, "category_menu is null"
            
            for node_name in global_node_registry.get_nodes_in_category(category):
                node_info = global_node_registry.get_node_info(category, node_name)
                
                if node_info:
                    action = category_menu.addAction(node_name)
                    assert action is not None, "action is null"
                    
                    action.setToolTip(node_info.description)
                    action.triggered.connect(
                        lambda checked=False, cat=category, name=node_name:
                            self.node_selected.emit(name, cat, self.position)
                    )
                    
                    
        
        