"""Application session driver: launcher → bootloader → editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.boot import BootRequest, RecentProjectsStore
from core.project import Project
from ui.windows.launcher import ProjectLauncher
from utils.logging_setup import get_logger
from utils.qt_window import present_window

if TYPE_CHECKING:
    from ui.windows.bootloader import BootloaderWindow
    from ui.windows.editor import Editor

_LOG = get_logger("session")


class ApplicationSession(QObject):
    """Owns the startup pipeline and keeps window references alive."""

    def __init__(
        self,
        app: QApplication,
        recent: RecentProjectsStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app: QApplication = app
        self._recent: RecentProjectsStore = recent or RecentProjectsStore()
        self._launcher: ProjectLauncher | None = None
        self._bootloader: BootloaderWindow | None = None
        self._editor: Editor | None = None
        self._pending_project: Project | None = None
        self._shutting_down: bool = False

    def start(self, *, initial_request: BootRequest | None = None) -> None:
        """Schedule the first UI after the event loop is running.

        Parameters:
            initial_request: Optional boot request that skips the launcher hub.
        """
        if initial_request is not None:
            _LOG.info("Session start → direct boot (%s)", initial_request.mode.value)
            QTimer.singleShot(0, lambda: self._begin_boot(initial_request))
            return
        _LOG.info("Session start → project launcher")
        QTimer.singleShot(0, self._show_launcher)

    def _show_launcher(self) -> None:
        if self._shutting_down:
            return
        self._dispose_bootloader()
        launcher = ProjectLauncher(recent=self._recent)
        launcher.project_chosen.connect(self._on_project_chosen)
        launcher.exit_requested.connect(self._on_launcher_exit)
        self._launcher = launcher
        present_window(launcher)
        _LOG.info(
            "Launcher presented (visible=%s, geo=%s)",
            launcher.isVisible(),
            launcher.geometry().getRect(),
        )

    def _on_launcher_exit(self) -> None:
        if self._shutting_down:
            return
        _LOG.info("Launcher closed without a project — quitting")
        self._shutting_down = True
        self._app.quit()

    def _on_project_chosen(self, request: object) -> None:
        if not isinstance(request, BootRequest):
            _LOG.error("Ignored invalid boot request: %r", request)
            return
        _LOG.info(
            "Project chosen (mode=%s, path=%s)",
            request.mode.value,
            request.path or "(untitled)",
        )
        self._begin_boot(request)
        self._close_launcher()

    def _close_launcher(self) -> None:
        if self._launcher is None:
            return
        launcher = self._launcher
        self._launcher = None
        launcher.close()

    def _begin_boot(self, request: BootRequest) -> None:
        from ui.windows.bootloader import BootloaderWindow

        _LOG.info("Opening bootloader")
        bootloader = BootloaderWindow(request)
        bootloader.boot_succeeded.connect(self._on_boot_succeeded)
        bootloader.boot_failed.connect(self._on_boot_failed)
        bootloader.cancelled.connect(self._on_boot_cancelled)
        self._bootloader = bootloader
        present_window(bootloader)
        bootloader.start()

    def _on_boot_succeeded(self, project_obj: object) -> None:
        if not isinstance(project_obj, Project):
            self._on_boot_failed("Boot produced an invalid project object")
            return
        if self._bootloader is None:
            return
        self._pending_project = project_obj
        self._bootloader.append_log(
            "[Editor workspace] Building panels and bindings…"
        )
        self._bootloader.set_stage(
            "Editor workspace",
            "Constructing editor workspace…",
        )
        QTimer.singleShot(0, self._construct_editor)

    def _construct_editor(self) -> None:
        project = self._pending_project
        bootloader = self._bootloader
        self._pending_project = None
        if project is None or bootloader is None:
            return

        _LOG.info("Constructing editor for project '%s'", project.name)
        try:
            from ui.windows.editor import Editor

            editor = Editor(project, recent_projects=self._recent)
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("Editor construction failed")
            bootloader.append_log(f"ERROR: Editor construction failed: {exc}")
            self._on_boot_failed(str(exc))
            return

        bootloader.append_log("[Editor workspace] Editor ready.")
        bootloader.set_progress_complete()
        bootloader.mark_handoff()

        if project.file_path:
            self._recent.remember(project.file_path, name=project.name)

        self._editor = editor
        editor.destroyed.connect(self._on_editor_destroyed)
        present_window(editor)
        self._dispose_bootloader()
        _LOG.info("Editor shown for '%s'", project.name)

    def _on_editor_destroyed(self, *_args: object) -> None:
        if self._shutting_down:
            return
        _LOG.info("Editor destroyed — quitting application")
        self._shutting_down = True
        self._editor = None
        self._app.quit()

    def _on_boot_failed(self, message: str) -> None:
        _LOG.error("Boot failed: %s", message)
        parent = self._bootloader
        QMessageBox.critical(parent, "Boot Failed", message)
        self._dispose_bootloader()
        self._show_launcher()

    def _on_boot_cancelled(self) -> None:
        _LOG.info("Boot cancelled — returning to launcher")
        self._dispose_bootloader()
        self._show_launcher()

    def _dispose_bootloader(self) -> None:
        if self._bootloader is None:
            return
        bootloader = self._bootloader
        self._bootloader = None
        bootloader.mark_handoff()
        bootloader.close()
