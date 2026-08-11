"""Bootloader window that streams staged editor-init logs."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.theme import BOOTLOADER_STYLE
from core.boot import BootRequest, BootStageResult, EditorBootDriver
from core.project import Project
from utils.paths import resource_path

STAGE_STEP_MS: int = 90


class BootloaderWindow(QWidget):
    """Runs ``EditorBootDriver`` stages and reports success or failure."""

    boot_succeeded = pyqtSignal(object)
    boot_failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        request: BootRequest,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("BootloaderWindow")
        self.setWindowTitle("Aphelion — Loading")
        self.setStyleSheet(BOOTLOADER_STYLE)
        self.setFixedSize(640, 420)

        icon_path = resource_path("icon.ico")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path.resolve())))

        self._driver: EditorBootDriver = EditorBootDriver(request)
        self._stage_index: int = 0
        self._cancelled: bool = False
        self._driver_done: bool = False
        self._handoff: bool = False
        self._timer: QTimer = QTimer(self)
        self._timer.setInterval(STAGE_STEP_MS)
        self._timer.timeout.connect(self._advance)

        self._log: QPlainTextEdit
        self._stage_label: QLabel
        self._status_label: QLabel
        self._progress: QProgressBar
        self._cancel_btn: QPushButton
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(10)

        title = QLabel("Starting Aphelion")
        title.setObjectName("BootloaderTitle")
        root.addWidget(title)

        self._stage_label = QLabel("Preparing…")
        self._stage_label.setObjectName("BootloaderStage")
        root.addWidget(self._stage_label)

        self._log = QPlainTextEdit()
        self._log.setObjectName("BootloaderLog")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        root.addWidget(self._log, 1)

        # +1 reserved for editor workspace construction in the session host.
        total = self._driver.stage_count + 1
        self._progress = QProgressBar()
        self._progress.setObjectName("BootloaderProgress")
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        footer = QHBoxLayout()
        self._status_label = QLabel("Initializing runtime…")
        self._status_label.setObjectName("BootloaderStatus")
        footer.addWidget(self._status_label, 1)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("BootloaderCancelButton")
        self._cancel_btn.clicked.connect(self._on_cancel)
        footer.addWidget(self._cancel_btn)
        root.addLayout(footer)

    def start(self) -> None:
        """Begin progressive stage execution."""
        self.append_log("Bootloader online.")
        self._timer.start()

    def append_log(self, line: str) -> None:
        """Append a line to the boot log view."""
        self._log.appendPlainText(line)
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)

    def set_stage(self, title: str, status: str) -> None:
        """Update the stage headline and footer status text."""
        self._stage_label.setText(title)
        self._status_label.setText(status)

    def set_progress_complete(self) -> None:
        """Fill the progress bar after the editor workspace is built."""
        self._progress.setValue(self._progress.maximum())

    def mark_handoff(self) -> None:
        """Mark that the editor is taking over (closing is not a cancel)."""
        self._handoff = True
        self._cancel_btn.setEnabled(False)

    def _advance(self) -> None:
        if self._cancelled or self._driver_done:
            self._timer.stop()
            return
        if self._stage_index >= self._driver.stage_count:
            self._timer.stop()
            self._finish_driver()
            return
        self._run_driver_stage()

    def _run_driver_stage(self) -> None:
        title = self._driver.stage_title(self._stage_index)
        self.set_stage(title, f"Running: {title}")
        result: BootStageResult = self._driver.run_stage(self._stage_index)
        self.append_log(f"[{title}] {result.message}")
        if result.detail:
            self.append_log(f"  · {result.detail}")
        self._stage_index += 1
        self._progress.setValue(self._stage_index)
        if not result.ok:
            self._fail(result.message)

    def _finish_driver(self) -> None:
        try:
            project: Project = self._driver.project
        except RuntimeError as exc:
            self._fail(str(exc))
            return
        self._driver_done = True
        self._cancel_btn.setEnabled(False)
        self.set_stage("Editor workspace", "Constructing editor workspace…")
        self.append_log("[Editor workspace] Driver stages complete.")
        self.boot_succeeded.emit(project)

    def _fail(self, message: str) -> None:
        self._timer.stop()
        self._driver_done = True
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("Boot failed")
        self.append_log(f"ERROR: {message}")
        self.boot_failed.emit(message)

    def _on_cancel(self) -> None:
        if self._driver_done or self._handoff:
            return
        self._cancelled = True
        self._timer.stop()
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("Cancelled")
        self.append_log("Boot cancelled by user.")
        self.cancelled.emit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Cancel an in-flight boot when the window is closed early."""
        if not self._handoff and not self._driver_done:
            self._on_cancel()
        super().closeEvent(event)
