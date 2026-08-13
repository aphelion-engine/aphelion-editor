"""Modal progress dialog shared by the point and planar tracking workers."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from config.theme import TRACKING_DIALOG_STYLE


class TrackingProgressDialog(QDialog):
    """Runs a tracking ``QThread`` worker while showing live progress.

    Reuses the export dialog's visual style since the shape (title, progress
    bar, Cancel-while-running) is identical.
    """

    def __init__(
        self,
        worker: Any,
        *,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker = worker
        self._cancel_requested = False
        self.result: dict[str, Any] | None = None
        self.error: str | None = None

        self.setObjectName("TrackingProgressDialog")
        self.setWindowTitle(title)
        self.setStyleSheet(TRACKING_DIALOG_STYLE)
        self.setModal(True)
        self.resize(360, 140)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("ExportDialogTitle")
        root.addWidget(heading)

        self._status_label = QLabel("Starting…")
        self._status_label.setObjectName("ExportStatusLabel")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setObjectName("ExportProgress")
        self._progress.setRange(0, 0)
        root.addWidget(self._progress)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self._on_cancel_clicked)
        root.addWidget(buttons)

        worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)

    def run_modal(self) -> bool:
        """Start the worker and block until it finishes; returns success."""
        self._worker.start()
        self.exec()
        return self.result is not None

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(current)
        self._status_label.setText(f"Tracking frame {current} of {total}…")

    def _on_finished(self, result: dict[str, Any]) -> None:
        if self._worker.isRunning():
            self._worker.wait(30000)
        self.result = result
        self.accept()

    def _on_failed(self, message: str) -> None:
        if self._worker.isRunning():
            self._worker.wait(30000)
        self.error = message
        self.reject()

    def _on_cancel_clicked(self) -> None:
        self._cancel_requested = True
        self._worker.cancel()
        self._status_label.setText("Cancelling…")

    def reject(self) -> None:
        """Block closing while the worker is actively running."""
        if self._worker.isRunning() and not self._cancel_requested:
            self._cancel_requested = True
            self._worker.cancel()
            return
        if self._worker.isRunning():
            self._worker.wait(3000)
        super().reject()
