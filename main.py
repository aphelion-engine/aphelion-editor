"""Aphelion application entry point."""

import sys

from PyQt6.QtWidgets import QApplication

from app_io.node_loader import NodeLoader
from core.project import Project
from ui.windows.editor import Editor


if __name__ == "__main__":
    app = QApplication(sys.argv)

    NodeLoader.load_defaults()

    project = Project()
    editor = Editor(project)
    editor.show()

    sys.exit(app.exec())
