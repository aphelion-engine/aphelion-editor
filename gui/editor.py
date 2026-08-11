"""
Main editor window with dockable panels and professional styling
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QWidget,
)

from core.project import Project
from gui.node_graph import NodeGraphView
from gui.properties import PropertiesPanel
from gui.timeline import TimelineWidget
from gui.viewport import ViewportWidget


class Editor(QMainWindow):
    def __init__(
        self,
        project: Project,
        position: tuple[int, int] = (100, 100),
        size: tuple[int, int] = (1600, 1000),
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"Aphelion | {project.name}")
        self.setGeometry(position[0], position[1], size[0], size[1])

        # Apply dark theme
        self.apply_dark_theme()

        self.project = project
        self.setup_ui()

    def apply_dark_theme(self) -> None:
        """Apply dark professional theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QDockWidget {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                titlebar-close-icon: url(none);
                titlebar-normal-icon: url(none);
            }
            QDockWidget::title {
                background-color: #3a3a3a;
                color: #ffffff;
                padding: 6px;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }
            QDockWidget::close-button, QDockWidget::float-button {
                background-color: #3a3a3a;
                border: none;
                padding: 0px;
                margin-right: 2px;
            }
            QDockWidget::close-button:hover, QDockWidget::float-button:hover {
                background-color: #444444;
            }
            QMenuBar {
                background-color: #2a2a2a;
                color: #ffffff;
                border-bottom: 1px solid #3a3a3a;
                spacing: 8px;
            }
            QMenuBar::item:selected {
                background-color: #0078d4;
                padding: 4px 12px;
                border-radius: 0px;
            }
            QMenu {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                padding: 4px 0px;
            }
            QMenu::item:selected {
                background-color: #0078d4;
                padding: 4px 16px;
            }
            QMenu::separator {
                background-color: #3a3a3a;
                height: 1px;
                margin: 4px 0px;
            }
            QScrollBar:vertical {
                width: 12px;
                background-color: #2a2a2a;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)

    def setup_ui(self) -> None:
        """Setup main UI with dockable panels"""
        # Create a dummy central widget (required for QMainWindow)
        central = QWidget()
        central.setStyleSheet("background-color: #1e1e1e;")
        self.setCentralWidget(central)
        central.hide()

        # Viewport Dock (Left Top)
        self.viewport = ViewportWidget(self.project)
        viewport_dock = self.create_dock("Viewport", self.viewport)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, viewport_dock)

        # Timeline Dock (Thin, between viewport and node graph)
        self.timeline = TimelineWidget(self.project)
        timeline_dock = self.create_dock("Timeline", self.timeline)
        timeline_dock.setMaximumHeight(120)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, timeline_dock)

        # Node Graph Dock (Left Bottom)
        self.node_graph = NodeGraphView(self.project)
        node_graph_dock = self.create_dock("Node Graph", self.node_graph)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, node_graph_dock)

        # Split the left side: viewport on top, node graph on bottom, timeline between
        self.resizeDocks(
            [viewport_dock, node_graph_dock],
            [400, 400],
            Qt.Orientation.Vertical
        )
        self.resizeDocks(
            [timeline_dock],
            [60],
            Qt.Orientation.Vertical
        )

        # Properties Dock (Right)
        self.properties = PropertiesPanel(self.project)
        properties_dock = self.create_dock("Properties", self.properties)
        properties_dock.setMinimumWidth(250)
        properties_dock.setMaximumWidth(350)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, properties_dock)

        # Set properties dock to be narrower
        self.resizeDocks([properties_dock], [250], Qt.Orientation.Horizontal)

        # Connect node selection to properties panel
        self.node_graph.scene.selectionChanged.connect(self.on_node_selected)

        self.create_menu_bar()

    def create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        """Create a styled dock widget"""
        dock = QDockWidget(title)
        dock.setWidget(widget)
        dock.setStyleSheet("""
            QDockWidget {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
            }
            QDockWidget::title {
                background-color: #3a3a3a;
                color: #ffffff;
                padding: 6px;
                border: none;
                font-weight: bold;
                font-size: 12px;
                border-bottom: 1px solid #4a4a4a;
            }
        """)
        return dock

    def on_node_selected(self) -> None:
        """Handle node selection in graph"""
        selected_items = self.node_graph.scene.selectedItems()
        if selected_items:
            item = selected_items[0]
            if hasattr(item, "node_id"):
                self.properties.set_node(item.node_id)
                node = self.project.nodes[item.node_id]
                if node.node_type == "Viewer":
                    self.project.set_active_viewer(item.node_id)

    def create_menu_bar(self) -> None:
        """Create application menu bar with professional styling"""
        menubar = self.menuBar()
        assert menubar is not None, "No menubar"

        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #2a2a2a;
                color: #ffffff;
                border-bottom: 1px solid #3a3a3a;
                spacing: 12px;
                padding: 0px 8px;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 12px;
                border-radius: 4px;
                font-weight: 500;
            }
            QMenuBar::item:selected {
                background-color: #0078d4;
                border-radius: 4px;
            }
            QMenuBar::item:pressed {
                background-color: #006abb;
            }
        """)

        # File Menu
        file_menu = menubar.addMenu("File")
        assert file_menu is not None, "Error creating file_menu"

        new_action = file_menu.addAction("New Project")
        new_action.setShortcut("Ctrl+N")

        open_action = file_menu.addAction("Open Project")
        open_action.setShortcut("Ctrl+O")

        save_action = file_menu.addAction("Save Project")
        save_action.setShortcut("Ctrl+S")

        file_menu.addSeparator()

        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Ctrl+Q")

        # Edit Menu
        edit_menu = menubar.addMenu("Edit")
        assert edit_menu is not None, "Error creating edit_menu"

        undo_action = edit_menu.addAction("Undo")
        undo_action.setShortcut("Ctrl+Z")

        redo_action = edit_menu.addAction("Redo")
        redo_action.setShortcut("Ctrl+Shift+Z")

        edit_menu.addSeparator()

        delete_action = edit_menu.addAction("Delete Node")
        delete_action.setShortcut("Delete")
        delete_action.triggered.connect(self.delete_selected_node)

        # View Menu
        view_menu = menubar.addMenu("View")
        assert view_menu is not None, "Error creating view_menu"

        fit_action = view_menu.addAction("Fit to Window")
        fit_action.setShortcut("Shift+F")

    def delete_selected_node(self) -> None:
        """Delete the currently selected node"""
        selected_items = self.node_graph.scene.selectedItems()
        if selected_items:
            item = selected_items[0]
            if hasattr(item, "node_id"):
                self.project.remove_node(item.node_id)