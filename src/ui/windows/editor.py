"""Main editor window with dockable panels and professional styling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QWidget,
)

from app_io import APH_FILE_FILTER, AphFormatError, load_aph, save_aph
from app_io.plugin_loader import PluginLoader, plugin_registry_key
from config.constants import AUTOSAVE_INTERVAL_MS
from config.keybinds import KeybindStore
from config.theme import DARK_THEME
from config.theme_engine import ThemeStyles, build_theme_styles
from core.boot import RecentProjectsStore
from core.preferences import PreferencesStore
from core.preferences.applier import apply_preferences_to_editor
from core.events import DOCUMENT_DIRTY_EVENTS, ObserverEvent
from core.history import HistoryStack
from core.history.commands import SetProjectSettingsCommand
from core.nodes.roto_nodes import RotoNode
from core.nodes.tracking_nodes import PlanarTrackerNode, TrackerNode
from core.project import Project
from ui.dialogs import (
    AboutDialog,
    ExportDialog,
    PinBarDialog,
    PreferencesDialog,
    ProjectSettingsDialog,
    ShortcutsDialog,
)
from ui.dialogs.plugin_dialog import open_attached_dialog
from ui.keybinds import EditorActions, status_hint_line
from ui.node_graph import NodeGraphView
from ui.node_graph import operations as node_ops
from ui.timeline import TimelineWidget
from ui.widgets import (
    EditorStatusBar,
    KeyframesPanelWidget,
    LogViewerWidget,
    MediaPoolWidget,
    PropertiesPanel,
    ViewportWidget,
)
from ui.windows.layouts import EditorDocks, LayoutMode, apply_layout
from ui.windows.menubar import build_menu_bar
from ui.windows.plugin_panels import mount_plugin_panels
from ui.windows.toolbar import build_pin_bar, resolve_pinned_actions, sync_pin_bar
from aphelion_sdk.widgets.host import WidgetContext
from ui.widgets.plugin_host import EditorWidgetHost
from utils.logging_setup import get_logger
from utils.paths import resource_path

_LOG = get_logger("editor")


class Editor(QMainWindow):
    """Primary application window hosting viewport, timeline, graph, and properties."""

    def __init__(
        self,
        project: Project,
        position: tuple[int, int] = (100, 100),
        size: tuple[int, int] = (1600, 1000),
        *,
        recent_projects: RecentProjectsStore | None = None,
    ) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setGeometry(position[0], position[1], size[0], size[1])

        icon_path = str(resource_path("icon.ico").resolve())
        self.setWindowIcon(QIcon(icon_path))

        self.preferences_store = PreferencesStore()
        self.preferences_store.load()
        self.project = project
        self.history = HistoryStack(project)
        self.keybinds = KeybindStore()
        self.preferences_store.apply_keybinds(self.keybinds)
        self.preferences_store.apply_node_colors()
        self.theme_styles: ThemeStyles = build_theme_styles(
            self.preferences_store.preferences.theme.resolved_tokens()
        )
        self.recent_projects: RecentProjectsStore = (
            recent_projects or RecentProjectsStore()
        )
        self.layout_mode: LayoutMode = LayoutMode.DEFAULT
        self.layout_actions: dict[LayoutMode, QAction] = {}
        self.undo_action: QAction | None = None
        self.redo_action: QAction | None = None
        self.actions: EditorActions
        self.docks: EditorDocks
        self.plugin_docks: list[QDockWidget] = []
        self.pin_bar: QToolBar
        self._key_hint_label: QLabel | None = None
        self._status_bar: EditorStatusBar | None = None
        self._is_dirty: bool = False
        self._suspend_dirty: bool = False
        self._autosave_timer: QTimer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self.setup_ui()
        apply_preferences_to_editor(self, self.preferences_store.preferences)
        self.history.subscribe(self._on_history_changed)
        self.project.subscribe(self._on_project_dirty_event)
        self._sync_history_actions()
        self._mark_clean()
        self._autosave_timer.start()

    def apply_dark_theme(self) -> None:
        """Apply shared dark theme stylesheet."""
        self.setStyleSheet(DARK_THEME)

    def setup_ui(self) -> None:
        """Create dockable panels and wire selection/playback signals."""
        central = QWidget()
        central.setStyleSheet("background-color: #1e1e1e;")
        self.setCentralWidget(central)
        central.hide()

        self.viewport = ViewportWidget(self.project, self.history)
        self.timeline = TimelineWidget(self.project, self.keybinds)
        self.node_graph = NodeGraphView(self.project, self.history, self.keybinds)
        self.properties = PropertiesPanel(self.project, self.history)
        self.keyframes = KeyframesPanelWidget(self.project, self.history)
        self.log_viewer = LogViewerWidget()
        self.media_pool = MediaPoolWidget(self.project)

        viewport_dock = self.create_dock("Viewport", self.viewport)
        timeline_dock = self.create_dock("Timeline", self.timeline)
        node_graph_dock = self.create_dock("Node Graph", self.node_graph)
        properties_dock = self.create_dock("Properties", self.properties)
        keyframes_dock = self.create_dock("Keyframes", self.keyframes)
        logs_dock = self.create_dock("Logs", self.log_viewer)
        media_pool_dock = self.create_dock("Media Pool", self.media_pool)
        logs_dock.setVisible(False)
        keyframes_dock.setVisible(False)
        media_pool_dock.setVisible(True)

        self.docks = EditorDocks(
            viewport=viewport_dock,
            node_graph=node_graph_dock,
            timeline=timeline_dock,
            properties=properties_dock,
            keyframes=keyframes_dock,
            logs=logs_dock,
            media_pool=media_pool_dock,
        )

        self.timeline.playback_changed.connect(self.viewport.set_playback_active)
        # pyrefly: ignore [missing-attribute]
        self.node_graph.scene.selectionChanged.connect(self.on_graph_selection_changed)
        self.media_pool.media_selected.connect(self._focus_media_node)

        apply_layout(self, self.docks, LayoutMode.DEFAULT)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, logs_dock)
        self.tabifyDockWidget(timeline_dock, logs_dock)
        self.tabifyDockWidget(properties_dock, media_pool_dock)
        self.tabifyDockWidget(properties_dock, keyframes_dock)
        properties_dock.raise_()

        self.properties.set_widget_host_factory(
            lambda ctx: EditorWidgetHost(self, ctx)
        )
        self.properties.custom_editor_requested.connect(
            self._on_custom_property_editor
        )
        mount_plugin_panels(self)

        self.actions = EditorActions(self, self.keybinds)
        self.actions.build()
        self.pin_bar = build_pin_bar(self)
        sync_pin_bar(self)
        # pyrefly: ignore [missing-attribute]
        self.pin_bar.toggleViewAction().toggled.connect(
            self._persist_pin_bar_visibility
        )
        build_menu_bar(self)
        self._status_bar = EditorStatusBar(self)
        self._setup_status_key_hints()

    def _setup_status_key_hints(self) -> None:
        """Permanent status-bar keybind hints that track focus context."""
        status = self.statusBar()
        assert status is not None
        self._key_hint_label = QLabel()
        self._key_hint_label.setObjectName("StatusKeyHints")
        status.addPermanentWidget(self._key_hint_label)
        self._update_key_hints("default")
        for widget in (
            self.viewport,
            self.node_graph,
            self.timeline,
            self.properties,
        ):
            widget.installEventFilter(self)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if watched is not None and event is not None:
            if event.type() == QEvent.Type.FocusIn:
                if watched is self.node_graph:
                    self._update_key_hints("graph")
                elif watched is self.timeline:
                    self._update_key_hints("timeline")
                else:
                    self._update_key_hints("default")
        return super().eventFilter(watched, event)

    def _update_key_hints(self, context: str) -> None:
        if self._key_hint_label is None:
            return
        self._key_hint_label.setText(status_hint_line(self.keybinds, context=context))

    def create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        """Create a styled, movable dock widget."""
        dock = QDockWidget(title, self)
        dock.setObjectName(f"Dock_{title.replace(' ', '')}")
        dock.setWidget(widget)
        dock.setStyleSheet(self.theme_styles.dock)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        return dock

    def on_graph_selection_changed(self) -> None:
        """Sync properties panel, active viewer, and viewport edit target with selection."""
        selected_items = self.node_graph.scene.selectedItems()
        if not selected_items:
            self.viewport.set_edit_target(None)
            return
        item = selected_items[0]
        if not hasattr(item, "node_id"):
            return
        self.properties.set_node(item.node_id)
        node = self.project.nodes[item.node_id]
        # Roto and Tracker/Planar Tracker each get their own interactive
        # viewport overlay; ViewportWidget.set_edit_target fans this out to
        # both and each one ignores node types that aren't its own.
        editable = isinstance(node, (RotoNode, TrackerNode, PlanarTrackerNode))
        self.viewport.set_edit_target(item.node_id if editable else None)
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

    def create_node_from_slot(self, slot_id: str) -> None:
        """Create the node currently assigned to a create-keybind slot.

        Parameters:
            slot_id: Stable slot identifier from ``KeybindStore`` (e.g. ``slot_1``).

        Side effects:
            Inserts a node at the graph cursor when the slot target is bound.
        """
        slot = self.keybinds.get_node_create_slot(slot_id)
        if slot is None or not slot.target.is_bound:
            return
        self.node_graph.setFocus(Qt.FocusReason.ShortcutFocusReason)
        node_id = self.node_graph.insert_node(
            slot.target.node_type,
            slot.target.node_category,
            self.node_graph.cursor_scene_pos,
        )
        status = self.statusBar()
        if status is not None and node_id is not None:
            status.showMessage(f"Added node: {slot.target.node_type}", 2500)

    def _focus_media_node(self, node_id: str) -> None:
        """Select a media source in the graph and properties panel."""
        item = self.node_graph.node_items.get(node_id)
        if item is not None:
            self.node_graph.scene.clearSelection()
            item.setSelected(True)
            self.node_graph.centerOn(item)
        self.properties.set_node(node_id)
        self.keyframes.set_node(node_id)
        self.node_graph.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_about(self) -> None:
        """Open the about dialog."""
        dialog = AboutDialog(parent=self)
        dialog.exec()

    def show_project_settings(self) -> None:
        """Open project settings and apply accepted changes through history."""
        dialog = ProjectSettingsDialog(self.project, parent=self)
        if dialog.exec() != ProjectSettingsDialog.DialogCode.Accepted:
            return
        settings = dialog.settings
        if settings is None:
            return
        self.history.push(SetProjectSettingsCommand(settings))
        self._update_window_title()
        if self._status_bar is not None:
            self._status_bar.refresh_all()
        status = self.statusBar()
        if status is not None:
            status.showMessage("Project settings updated", 2500)

    def export_sequence(self) -> None:
        """Export the active viewer using the current in/out work range.

        The dialog owns its own ``ExportWorker`` and stays open with a live
        progress bar for the whole job; this method only reacts to the
        final outcome.
        """
        self.timeline.pause_playback()
        self.viewport.set_playback_active(False)
        controller = self.timeline.controller
        dialog = ExportDialog(
            self.project,
            in_point=controller.in_point,
            out_point=controller.out_point,
            parent=self,
        )
        try:
            if dialog.exec() != ExportDialog.DialogCode.Accepted:
                return
            status = self.statusBar()
            if status is not None and dialog.exported_path is not None:
                status.showMessage(
                    f"Export complete: {dialog.exported_path.name}",
                    5000,
                )
        finally:
            self.viewport.request_update()

    def clear_frame_cache(self) -> None:
        """Drop cached preview frames and refresh status metrics."""
        self.project.clear_cache()
        if self._status_bar is not None:
            self._status_bar.refresh_all()
        self.viewport.request_update()
        status = self.statusBar()
        if status is not None:
            status.showMessage("Frame cache cleared", 2000)

    def open_recent_project(self, path: str) -> None:
        """Open a project from the recent-projects list."""
        if not self._prompt_save_before_leave():
            return
        try:
            project = load_aph(path)
        except AphFormatError as exc:
            QMessageBox.critical(self, "Open Project", str(exc))
            self.recent_projects.remove(path)
            return
        self._replace_project(project)
        self._remember_current_project()
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"Opened {Path(path).name}", 3000)

    def show_preferences(self) -> None:
        """Open the preferences dialog and apply accepted changes."""
        dialog = PreferencesDialog(
            self.preferences_store.preferences,
            self.keybinds,
            parent=self,
        )
        dialog.applied.connect(
            lambda: self._apply_preferences_dialog(dialog, persist=False)
        )
        dialog.plugins_reloaded.connect(self._refresh_plugin_ui)
        if dialog.exec() != PreferencesDialog.DialogCode.Accepted:
            if dialog.plugins_were_reloaded:
                PluginLoader.reload(self.preferences_store.preferences.plugins)
                self._refresh_plugin_ui()
            return
        self._apply_preferences_dialog(dialog, persist=True)

    def _apply_preferences_dialog(
        self,
        dialog: PreferencesDialog,
        *,
        persist: bool,
    ) -> None:
        """Apply preferences edited in ``dialog`` to the live editor."""
        previous_plugins = self.preferences_store.preferences.plugins
        self.preferences_store.preferences = dialog.preferences
        self.preferences_store.capture_keybinds(dialog.keybinds)
        self.preferences_store.apply_keybinds(self.keybinds)
        self.actions.reapply_shortcuts()
        if previous_plugins != dialog.preferences.plugins:
            PluginLoader.reload(dialog.preferences.plugins)
        self._refresh_plugin_ui()
        apply_preferences_to_editor(self, self.preferences_store.preferences)
        if persist:
            self.preferences_store.save()

    def _refresh_plugin_ui(self, _count: int = 0) -> None:
        """Rebuild menus and plugin-attached docks after plugins change."""
        mount_plugin_panels(self)
        self.actions.refresh_node_create_actions()
        build_menu_bar(self)

    def open_plugin_dialog(
        self,
        widget_id: str,
        context: WidgetContext | None = None,
    ) -> bool:
        """Open a dialog widget attached to the plugin in ``context``."""
        bound = context or WidgetContext(project_name=self.project.name)
        host = EditorWidgetHost(self, bound)
        return open_attached_dialog(self, widget_id, host)

    def _on_custom_property_editor(
        self,
        node_id: str,
        prop_name: str,
        widget_id: str,
    ) -> None:
        """Open the parent plugin's dialog for a custom inspector property."""
        node = self.project.nodes.get(node_id)
        if node is None:
            return
        self.open_plugin_dialog(
            widget_id,
            context=WidgetContext(
                plugin_key=plugin_registry_key(type(node)),
                node_id=node_id,
                property_key=prop_name,
                project_name=self.project.name,
            ),
        )

    def set_pin_bar_visible(self, visible: bool) -> None:
        """Show or hide the pin bar (persistence handled by the toggle signal)."""
        self.pin_bar.setVisible(visible)

    def _persist_pin_bar_visibility(self, visible: bool) -> None:
        """Save pin bar visibility whenever it changes, from any source."""
        self.preferences_store.preferences.editor.show_pin_bar = visible
        self.preferences_store.save()

    def customize_pin_bar(self) -> None:
        """Open the pin bar picker and persist the resulting selection."""
        dialog = PinBarDialog(
            self.keybinds,
            resolve_pinned_actions(self),
            parent=self,
        )
        if dialog.exec() != PinBarDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_actions()
        self.preferences_store.preferences.pinned_actions = [
            action.value for action in selected
        ]
        self.preferences_store.save()
        sync_pin_bar(self)
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"Pin bar updated ({len(selected)} action(s))", 2500)

    def refresh_node_colors(self) -> None:
        """Refresh accent colors on all graph node items."""
        from PyQt6.QtGui import QColor

        from core.nodes.registry import global_node_registry

        for node_id, item in self.node_graph.node_items.items():
            node = self.project.nodes.get(node_id)
            if node is None:
                continue
            node.node_color = global_node_registry.resolve_color(
                node.node_category,
                node.node_type,
            )
            r, g, b = node.node_color
            item.accent_color = QColor(r, g, b)
            item.update()
        self.node_graph.refresh_theme()

    def show_keyboard_shortcuts(self) -> None:
        """Open the keyboard shortcuts reference dialog."""
        dialog = ShortcutsDialog(self.keybinds, parent=self)
        dialog.exec()

    def _update_window_title(self) -> None:
        """Reflect project name and dirty state (`*`) in the title bar."""
        dirty_mark = " *" if self._is_dirty else ""
        self.setWindowTitle(f"Aphelion | {self.project.name}{dirty_mark}")

    def _mark_dirty(self) -> None:
        """Flag the document as having unsaved changes."""
        if self._suspend_dirty or self._is_dirty:
            return
        self._is_dirty = True
        self._update_window_title()

    def _mark_clean(self) -> None:
        """Clear the unsaved-changes flag after load or successful save."""
        self._is_dirty = False
        self._update_window_title()

    def _on_history_changed(self) -> None:
        """Sync undo/redo chrome and mark dirty after document commands."""
        self._sync_history_actions()
        self._mark_dirty()

    def _on_project_dirty_event(self, event: ObserverEvent, _data: Any) -> None:
        """Mark dirty for document events that may bypass the history stack."""
        if event in DOCUMENT_DIRTY_EVENTS:
            self._mark_dirty()

    def _replace_project(self, project: Project) -> None:
        """Swap the live document and retarget every panel + history stack.

        Parameters:
            project: Newly created or loaded project to become active.

        Side effects:
            Closes the previous project's media handles and clears undo history.
        """
        previous = self.project
        self._suspend_dirty = True
        self.history.unsubscribe(self._on_history_changed)
        self.project.unsubscribe(self._on_project_dirty_event)
        self.project = project
        self.history = HistoryStack(project)
        self.viewport.set_project(project)
        self.timeline.set_project(project)
        self.node_graph.set_project(project, self.history)
        self.properties.set_project(project, self.history)
        self.keyframes.set_project(project, self.history)
        self.media_pool.set_project(project)
        self.history.subscribe(self._on_history_changed)
        self.project.subscribe(self._on_project_dirty_event)
        self._sync_history_actions()
        self._suspend_dirty = False
        self._mark_clean()
        if self._status_bar is not None:
            self._status_bar.attach_to_project()
        previous.close()

    def new_project(self) -> None:
        """Create a blank untitled project and replace the current document."""
        if not self._prompt_save_before_leave():
            return
        self._replace_project(Project("Untitled Project"))
        status = self.statusBar()
        if status is not None:
            status.showMessage("New project", 2000)

    def open_project(self) -> None:
        """Prompt for a ``.aph`` file and load it into the editor."""
        if not self._prompt_save_before_leave():
            return
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            APH_FILE_FILTER,
        )
        if not path:
            return
        try:
            project = load_aph(path)
        except AphFormatError as exc:
            QMessageBox.critical(self, "Open Project", str(exc))
            return
        self._replace_project(project)
        self._remember_current_project()
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"Opened {Path(path).name}", 3000)

    def save_project(self) -> bool:
        """Save to the current path, or prompt when the project is untitled.

        Returns:
            ``True`` when the document was written successfully.
        """
        if self.project.file_path:
            return self._write_aph(self.project.file_path)
        return self.save_project_as()

    def save_project_as(self) -> bool:
        """Prompt for a destination and write a ``.aph`` document.

        Returns:
            ``True`` when the user chose a path and the write succeeded.
        """
        suggested = self.project.file_path or f"{self.project.name}.aph"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Project",
            suggested,
            APH_FILE_FILTER,
        )
        if not path:
            return False
        return self._write_aph(path)

    def _write_aph(self, path: str, *, autosave: bool = False) -> bool:
        """Persist the active project and clear the dirty flag.

        Parameters:
            path: Destination file path (``.aph`` appended when missing).
            autosave: When ``True``, use a quieter status-bar message.

        Returns:
            ``True`` when the file was written.

        Side effects:
            Writes disk I/O; updates ``project.file_path`` / ``project.name``.
        """
        try:
            written = save_aph(path, self.project)
        except AphFormatError as exc:
            _LOG.error("Save failed (%s): %s", path, exc)
            if not autosave:
                QMessageBox.critical(self, "Save Project", str(exc))
            else:
                status = self.statusBar()
                if status is not None:
                    status.showMessage(f"Autosave failed: {exc}", 5000)
            return False
        self._remember_current_project()
        self._mark_clean()
        if autosave:
            _LOG.debug("Autosaved %s", written)
        else:
            _LOG.info("Saved project %s", written)
        status = self.statusBar()
        if status is not None:
            label = "Autosaved" if autosave else "Saved"
            status.showMessage(f"{label} {written.name}", 3000)
        return True

    def _autosave_tick(self) -> None:
        """Periodically write the project when dirty and already on disk."""
        if not self._is_dirty or not self.project.file_path:
            return
        self._write_aph(self.project.file_path, autosave=True)

    def _prompt_save_before_leave(self) -> bool:
        """Ask to save unsaved work before closing or replacing the document.

        Returns:
            ``True`` when it is safe to proceed (saved or discarded).
        """
        if not self._is_dirty:
            return True

        if self.project.file_path:
            text = f'Save changes to "{self.project.name}" before closing?'
        else:
            text = (
                "This project has not been saved.\n"
                "Do you wish to save?"
            )

        choice = QMessageBox.question(
            self,
            "Save Project",
            text,
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Discard:
            return True
        return self.save_project()

    def _shutdown(self) -> None:
        """Stop timers, playback, and background workers before exit."""
        self._autosave_timer.stop()
        self.timeline.pause_playback()
        if self._status_bar is not None:
            self._status_bar.shutdown()
        self.viewport.shutdown()
        self.properties.shutdown()
        self.log_viewer.shutdown()
        self.media_pool.shutdown()
        self.project.unsubscribe(self._on_project_dirty_event)
        self.project.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Prompt to save unsaved changes, then release project resources."""
        if not self._prompt_save_before_leave():
            _LOG.info("Close cancelled (unsaved changes retained)")
            event.ignore()
            return
        self._shutdown()
        _LOG.info("Closing editor for project '%s'", self.project.name)
        super().closeEvent(event)
        app: QApplication | None = QApplication.instance()
        if isinstance(app, QApplication):
            app.quit()

    def _remember_current_project(self) -> None:
        """Push the active project path onto the recent-projects list."""
        if self.project.file_path:
            self.recent_projects.remember(
                self.project.file_path,
                name=self.project.name,
            )

    def undo(self) -> None:
        """Undo the last document command."""
        if self.history.undo():
            status = self.statusBar()
            if status is not None:
                status.showMessage(
                    self.history.redo_text().replace("Redo", "Undid", 1),
                    2000,
                )

    def redo(self) -> None:
        """Redo the last undone document command."""
        if self.history.redo():
            status = self.statusBar()
            if status is not None:
                status.showMessage(
                    self.history.undo_text().replace("Undo", "Redid", 1),
                    2000,
                )

    def _sync_history_actions(self) -> None:
        """Keep Edit → Undo/Redo labels and enabled state in sync."""
        if self.undo_action is not None:
            self.undo_action.setEnabled(self.history.can_undo)
            self.undo_action.setText(self.history.undo_text())
        if self.redo_action is not None:
            self.redo_action.setEnabled(self.history.can_redo)
            self.redo_action.setText(self.history.redo_text())

    def copy_selected_nodes(self) -> None:
        """Copy the current graph selection to the graph clipboard."""
        self.node_graph.copy_selection()
        status = self.statusBar()
        if status is not None and not self.node_graph.clipboard.is_empty:
            status.showMessage("Copied nodes", 1500)

    def paste_nodes(self) -> None:
        """Paste graph clipboard contents into the node graph."""
        before = set(self.project.nodes.keys())
        self.node_graph.paste_clipboard()
        created_count = len(set(self.project.nodes.keys()) - before)
        status = self.statusBar()
        if status is not None and created_count > 0:
            status.showMessage(f"Pasted {created_count} node(s)", 1500)

    def delete_selected_nodes(self) -> None:
        """Delete selected wires or nodes in the graph."""
        self.node_graph.delete_selection()

    def duplicate_selected_nodes(self) -> None:
        """Duplicate the current graph selection."""
        items = self.node_graph.selected_nodes()
        if items:
            node_ops.duplicate_items(self.node_graph, items)

    def set_layout_mode(self, mode: LayoutMode) -> None:
        """Apply a named workspace layout preset."""
        self.layout_mode = mode
        apply_layout(self, self.docks, mode)
        self._sync_layout_action_checks()
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"Layout: {mode.value.replace('_', ' ').title()}", 2500)

    def reset_layout(self) -> None:
        """Restore the default dock arrangement."""
        self.set_layout_mode(LayoutMode.DEFAULT)

    def _sync_layout_action_checks(self) -> None:
        for mode, action in self.layout_actions.items():
            action.setChecked(mode == self.layout_mode)

    def show_all_panels(self) -> None:
        """Ensure every dock is visible and docked."""
        for dock in (*self.docks.all(), *self.docks.optional(), *self.plugin_docks):
            dock.show()
            dock.setFloating(False)
        status = self.statusBar()
        if status is not None:
            status.showMessage("All panels shown", 2000)

    def toggle_panel(self, dock: QDockWidget) -> None:
        """Show or hide a dock panel."""
        dock.setVisible(not dock.isVisible())

    def toggle_keyframes_panel(self) -> None:
        """Show or hide the keyframes dock."""
        self.toggle_panel(self.docks.keyframes)
        if self.docks.keyframes.isVisible():
            self.docks.keyframes.raise_()

    def toggle_logs_panel(self) -> None:
        """Show or hide the log viewer dock."""
        self.toggle_panel(self.docks.logs)
        if self.docks.logs.isVisible():
            self.docks.logs.raise_()

    def toggle_fullscreen(self) -> None:
        """Toggle window fullscreen mode."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
