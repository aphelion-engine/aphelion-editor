
import sys 
from PyQt6.QtWidgets import QApplication
from gui.editor import Editor 

from core.project import Project
from core.loader import Loader 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    Loader.load_defaults_into_node_registry()
    
    project = Project()
    
    editor = Editor(project)
    editor.show()
    
    sys.exit(app.exec())
    