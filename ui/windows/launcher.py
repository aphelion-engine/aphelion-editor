"""Startup project hub: create new, browse, or open a recent ``.aph``."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QShowEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_io.aph_format import APH_FILE_FILTER
from config.theme import LAUNCHER_STYLE
from core.boot import BootMode, BootRequest, RecentProjectEntry, RecentProjectsStore
from utils.logging_setup import get_logger
from utils.paths import resource_path

_LOG = get_logger("launcher")


class ProjectLauncher(QWidget):
    """First-run window for choosing how to start an editor session."""

    project_chosen = pyqtSignal(object)
    exit_requested = pyqtSignal()

    def __init__(
        self,
        recent: RecentProjectsStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectLauncher")
        self.setWindowTitle("Aphelion")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setStyleSheet(LAUNCHER_STYLE)
        self.setFixedSize(560, 480)
        self._recent: RecentProjectsStore = recent or RecentProjectsStore()
        self._handoff: bool = False
        self._shown_once: bool = False

        self._apply_window_icon()

        self._recent_list: QListWidget
        self._empty_label: QLabel
        self._build_ui()
        self.refresh_recent()

    def _apply_window_icon(self) -> None:
        """Set the launcher icon when the bundled asset is readable."""
        icon_path = resource_path("icon.ico")
        if not icon_path.is_file():
            return
        try:
            self.setWindowIcon(QIcon(str(icon_path.resolve())))
        except Exception:
            _LOG.warning("Failed to load launcher icon from %s", icon_path, exc_info=True)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(10)

        brand = QLabel("APHELION")
        brand.setObjectName("LauncherBrand")
        root.addWidget(brand)

        subtitle = QLabel("Open a project or start a new editing session.")
        subtitle.setObjectName("LauncherSubtitle")
        root.addWidget(subtitle)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        new_btn = QPushButton("New Project")
        new_btn.setObjectName("LauncherPrimaryButton")
        new_btn.clicked.connect(self._on_new_project)
        actions.addWidget(new_btn)

        open_btn = QPushButton("Open Project…")
        open_btn.setObjectName("LauncherSecondaryButton")
        open_btn.clicked.connect(self._on_browse_project)
        actions.addWidget(open_btn)
        root.addLayout(actions)

        recent_header = QLabel("RECENT PROJECTS")
        recent_header.setObjectName("LauncherRecentHeader")
        root.addWidget(recent_header)

        self._recent_list = QListWidget()
        self._recent_list.setObjectName("LauncherRecentList")
        self._recent_list.itemActivated.connect(self._on_recent_activated)
        root.addWidget(self._recent_list, 1)

        self._empty_label = QLabel("No recent projects yet.")
        self._empty_label.setObjectName("LauncherEmptyRecent")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty_label)

    def refresh_recent(self) -> None:
        """Reload the recent-projects list from disk."""
        self._recent_list.clear()
        entries = self._recent.list_entries()
        for entry in entries:
            item = QListWidgetItem(self._format_entry(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry.path)
            if not entry.exists:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._recent_list.addItem(item)
        has_items = self._recent_list.count() > 0
        self._recent_list.setVisible(has_items)
        self._empty_label.setVisible(not has_items)

    def _format_entry(self, entry: RecentProjectEntry) -> str:
        marker = "" if entry.exists else " (missing)"
        return f"{entry.name}{marker}\n{entry.path}"

    def _emit_request(self, request: BootRequest) -> None:
        self._handoff = True
        self.project_chosen.emit(request)

    def _on_new_project(self) -> None:
        self._emit_request(BootRequest(mode=BootMode.NEW))

    def _on_browse_project(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            APH_FILE_FILTER,
        )
        if not path:
            return
        self._emit_request(BootRequest(mode=BootMode.OPEN, path=str(Path(path))))

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            return
        if not Path(path).is_file():
            self._recent.remove(path)
            self.refresh_recent()
            return
        self._emit_request(BootRequest(mode=BootMode.OPEN, path=path))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Track that the hub has been presented at least once."""
        self._shown_once = True
        super().showEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Treat a user close as an app exit only after the hub was shown."""
        if not self._shown_once:
            event.ignore()
            _LOG.warning("Ignored premature launcher close before first show")
            return
        if not self._handoff:
            self.exit_requested.emit()
        super().closeEvent(event)
