"""Main editor window with dockable panels and professional styling."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QWidget,
)

from config.theme import DARK_THEME, DOCK_STYLE, MENUBAR_STYLE
from core.project import Project
from ui.icons import AppIcon, make_icon
from ui.node_graph import NodeGraphView
from ui.timeline import TimelineWidget
from ui.widgets import PropertiesPanel, ViewportWidget


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

        self.node_graph.scene.selectionChanged.connect(self.on_node_selected)
        self.create_menu_bar()

    def create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        """Create a styled dock widget."""
        dock = QDockWidget(title)
        dock.setWidget(widget)
        dock.setStyleSheet(DOCK_STYLE)
        return dock

    def on_node_selected(self) -> None:
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

    def create_menu_bar(self) -> None:
        """Create application menu bar with icons and shortcuts."""
        menubar = self.menuBar()
        assert menubar is not None, "No menubar"
        menubar.setStyleSheet(MENUBAR_STYLE)

        file_menu = menubar.addMenu("File")
        assert file_menu is not None
        new_action = file_menu.addAction(make_icon(AppIcon.NEW_FILE), "New Project")
        new_action.setShortcut("Ctrl+N")
        open_action = file_menu.addAction(make_icon(AppIcon.OPEN_FILE), "Open Project")
        open_action.setShortcut("Ctrl+O")
        save_action = file_menu.addAction(make_icon(AppIcon.SAVE_FILE), "Save Project")
        save_action.setShortcut("Ctrl+S")
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Ctrl+Q")

        edit_menu = menubar.addMenu("Edit")
        assert edit_menu is not None
        undo_action = edit_menu.addAction(make_icon(AppIcon.UNDO), "Undo")
        undo_action.setShortcut("Ctrl+Z")
        redo_action = edit_menu.addAction(make_icon(AppIcon.REDO), "Redo")
        redo_action.setShortcut("Ctrl+Shift+Z")
        edit_menu.addSeparator()
        delete_action = edit_menu.addAction(make_icon(AppIcon.DELETE), "Delete Node")
        delete_action.setShortcut("Delete")
        delete_action.triggered.connect(self.delete_selected_node)

        view_menu = menubar.addMenu("View")
        assert view_menu is not None
        fit_action = view_menu.addAction(make_icon(AppIcon.FIT_VIEW), "Fit to Window")
        fit_action.setShortcut("Shift+F")

    def delete_selected_node(self) -> None:
        """Delete the currently selected graph node."""
        selected_items = self.node_graph.scene.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        if hasattr(item, "node_id"):
            self.project.remove_node(item.node_id)
