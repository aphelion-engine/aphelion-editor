"""Main editor window with dockable panels and professional styling."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QWidget,
)

from config.theme import DARK_THEME, DOCK_STYLE
from core.project import Project
from ui.node_graph import NodeGraphView
from ui.node_graph import operations as node_ops
from ui.timeline import TimelineWidget
from ui.widgets import PropertiesPanel, ViewportWidget
from ui.windows.menubar import build_menu_bar


class Editor(QMainWindow):
    """Primary application window hosting viewport, timeline, graph, and properties."""

    def __init__(
        self,
        project: Project,
        position: tuple[int, int] = (100, 100),
        size: tuple[int, int] = (1600, 1000),
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"Aphelion | {project.name}")
        self.setGeometry(position[0], position[1], size[0], size[1])
        
        self.apply_dark_theme()
        self.project = project
        self.setup_ui()

    def apply_dark_theme(self) -> None:
        """Apply shared dark theme stylesheet."""
        self.setStyleSheet(DARK_THEME)

    def setup_ui(self) -> None:
        """Create dockable panels and wire selection/playback signals."""
        central = QWidget()
        central.setStyleSheet("background-color: #1e1e1e;")
        self.setCentralWidget(central)
        central.hide()

        self.viewport = ViewportWidget(self.project)
        viewport_dock = self.create_dock("Viewport", self.viewport)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, viewport_dock)

        self.timeline = TimelineWidget(self.project)
        timeline_dock = self.create_dock("Timeline", self.timeline)
        timeline_dock.setMinimumHeight(140)
        timeline_dock.setMaximumHeight(220)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, timeline_dock)
        self.timeline.playback_changed.connect(self.viewport.set_playback_active)

        self.node_graph = NodeGraphView(self.project)
        node_graph_dock = self.create_dock("Node Graph", self.node_graph)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, node_graph_dock)

        self.resizeDocks(
            [viewport_dock, node_graph_dock],
            [400, 400],
            Qt.Orientation.Vertical,
        )
        self.resizeDocks([timeline_dock], [168], Qt.Orientation.Vertical)

        self.properties = PropertiesPanel(self.project)
        properties_dock = self.create_dock("Properties", self.properties)
        properties_dock.setMinimumWidth(250)
        properties_dock.setMaximumWidth(350)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, properties_dock)
        self.resizeDocks([properties_dock], [250], Qt.Orientation.Horizontal)

        self.node_graph.scene.selectionChanged.connect(self.on_graph_selection_changed)
        build_menu_bar(self)
        _ = self.statusBar()

    def create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        """Create a styled dock widget."""
        dock = QDockWidget(title)
        dock.setWidget(widget)
        dock.setStyleSheet(DOCK_STYLE)
        return dock

    def on_graph_selection_changed(self) -> None:
        """Sync properties panel (and active viewer) with graph selection."""
        selected_items = self.node_graph.scene.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        if not hasattr(item, "node_id"):
            return
        self.properties.set_node(item.node_id)
        node = self.project.nodes[item.node_id]
        if node.node_type == "Viewer":
            self.project.set_active_viewer(item.node_id)
            status = self.statusBar()
            if status is not None:
                status.showMessage(f"Active viewer: {node.name}", 2000)

    def insert_node_from_menu(self, name: str, category: str) -> None:
        """Insert a node at the graph view center from the menu bar."""
        self.node_graph.insert_node(name, category)
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"Added node: {name}", 2500)

    def delete_selected_nodes(self) -> None:
        """Delete all currently selected graph nodes."""
        items = self.node_graph.selected_nodes()
        if items:
            node_ops.delete_items(self.node_graph, items)

    def duplicate_selected_nodes(self) -> None:
        """Duplicate the current graph selection."""
        items = self.node_graph.selected_nodes()
        if items:
            node_ops.duplicate_items(self.node_graph, items)
