"""Export dialog for rendering the active viewer to disk.

Owns its ``ExportWorker`` directly (rather than handing a request back to
the caller) so the progress bar, Cancel button, and completion state stay
visually connected to the same dialog the whole time the export runs.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.theme import EXPORT_DIALOG_STYLE
from core.project import Project
from render.export_worker import ExportFormat, ExportRequest, ExportWorker


class ExportDialog(QDialog):
    """Collect export parameters and run a background export worker."""

    def __init__(
        self,
        project: Project,
        *,
        in_point: int,
        out_point: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._in_point = in_point
        self._out_point = out_point
        self._worker: ExportWorker | None = None
        self._output_path: Path | None = None
        self._cancel_requested: bool = False

        self.setObjectName("ExportDialog")
        self.setWindowTitle("Export")
        self.setStyleSheet(EXPORT_DIALOG_STYLE)
        self.setModal(True)
        self.resize(460, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Export Sequence")
        title.setObjectName("ExportDialogTitle")
        root.addWidget(title)

        source = QGroupBox("Source")
        source_form = QFormLayout(source)
        viewer_label = QLabel(self._viewer_label())
        source_form.addRow("Viewer", viewer_label)
        source_form.addRow("Range", QLabel(f"Frames {in_point} – {out_point}"))
        root.addWidget(source)

        output = QGroupBox("Output")
        output_form = QFormLayout(output)
        self._format = QComboBox()
        self._format.addItem("MP4 Video", ExportFormat.MP4)
        self._format.addItem("PNG Sequence", ExportFormat.PNG_SEQUENCE)
        self._format.currentIndexChanged.connect(self._sync_output_placeholder)
        output_form.addRow("Format", self._format)

        path_row = QHBoxLayout()
        self._path = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self._path, 1)
        path_row.addWidget(browse)
        output_form.addRow("Destination", path_row)

        self._fps = QSpinBox()
        self._fps.setRange(1, 240)
        self._fps.setValue(int(project.fps))
        output_form.addRow("Frame Rate", self._fps)

        self._full_resolution = QCheckBox("Render at full project resolution")
        self._full_resolution.setChecked(True)
        self._full_resolution.setToolTip(
            "Bypasses the Viewer's interactive Proxy Width for this export."
        )
        output_form.addRow("Quality", self._full_resolution)
        root.addWidget(output)

        self._status_label = QLabel()
        self._status_label.setObjectName("ExportStatusLabel")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        root.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setObjectName("ExportProgress")
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._cancel_button = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._start_export)
        self._buttons.rejected.connect(self._on_cancel_clicked)
        root.addWidget(self._buttons)

        self._sync_output_placeholder()

    @property
    def exported_path(self) -> Path | None:
        """Destination written by a successfully completed export."""
        return self._output_path

    def _viewer_label(self) -> str:
        viewer_id = self._project.active_viewer
        if viewer_id is None:
            return "None (add a Viewer node)"
        node = self._project.nodes.get(viewer_id)
        if node is None:
            return viewer_id
        return f"{node.name} ({node.node_type})"

    def _sync_output_placeholder(self) -> None:
        if self._path.text().strip():
            return
        stem = Path(self._project.name).stem or "export"
        fmt = self._format.currentData()
        if fmt == ExportFormat.PNG_SEQUENCE:
            self._path.setPlaceholderText(f"{stem}_frames/")
        else:
            self._path.setPlaceholderText(f"{stem}.mp4")

    def _browse(self) -> None:
        fmt = self._format.currentData()
        if fmt == ExportFormat.PNG_SEQUENCE:
            path = QFileDialog.getExistingDirectory(self, "Export Folder")
            if path:
                self._path.setText(path)
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Video",
            self._path.text() or f"{self._project.name}.mp4",
            "MP4 Video (*.mp4)",
        )
        if path:
            self._path.setText(path)

    def _set_form_enabled(self, enabled: bool) -> None:
        """Lock the format/path/fps/quality inputs while a job is running."""
        for widget in (self._format, self._path, self._fps, self._full_resolution):
            widget.setEnabled(enabled)

    def _start_export(self) -> None:
        viewer_id = self._project.active_viewer
        if viewer_id is None:
            self._show_status("Select an active Viewer before exporting.")
            return

        raw_path = self._path.text().strip() or self._path.placeholderText()
        if not raw_path:
            self._show_status("Choose an export destination.")
            return

        fmt = self._format.currentData()
        if not isinstance(fmt, ExportFormat):
            return

        output = Path(raw_path)
        if fmt == ExportFormat.MP4 and output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")

        audio_prefs = None
        if self.parent() is not None and hasattr(self.parent(), "preferences_store"):
            audio_prefs = self.parent().preferences_store.preferences.audio

        request = ExportRequest(
            viewer_id=viewer_id,
            start_frame=self._in_point,
            end_frame=self._out_point,
            output_path=output,
            format=fmt,
            fps=self._fps.value(),
            full_resolution=self._full_resolution.isChecked(),
            export_audio_enabled=True if audio_prefs is None else bool(audio_prefs.export_audio_enabled),
            export_sample_rate=48000 if audio_prefs is None else int(audio_prefs.export_sample_rate),
            export_channels=2 if audio_prefs is None else int(audio_prefs.export_channels),
        )

        self._cancel_requested = False
        self._set_form_enabled(False)
        if self._ok_button is not None:
            self._ok_button.setEnabled(False)
        self._show_status(f"Exporting to {output.name}…")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setValue(0)

        worker = ExportWorker(self._project, request, parent=self)
        worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _wait_worker(self) -> None:
        """Join the export thread before dropping the worker reference."""
        worker = self._worker
        if worker is None:
            return
        if worker.isRunning() and not worker.wait(30000):
            worker.terminate()
            worker.wait(1000)

    def _on_worker_finished(self) -> None:
        """Qt thread finished hook; safe point to release the worker object."""
        worker = self._worker
        if worker is None:
            return
        worker.deleteLater()
        self._worker = None

    def _on_cancel_clicked(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            self._cancel_requested = True
            worker.cancel()
            if self._cancel_button is not None:
                self._cancel_button.setEnabled(False)
            self._show_status("Cancelling…")
            return
        self._wait_worker()
        self.reject()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._show_status(f"Exporting frame {current} of {total}…")

    def _on_finished(self, path: str) -> None:
        self._output_path = Path(path)
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._set_form_enabled(True)
        if self._ok_button is not None:
            self._ok_button.setEnabled(True)
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(True)
        self._wait_worker()
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._wait_worker()
        self._set_form_enabled(True)
        if self._ok_button is not None:
            self._ok_button.setEnabled(True)
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(True)
        self._progress.setVisible(False)
        if self._cancel_requested:
            self._show_status("Export cancelled.")
            return
        self._show_status("")
        QMessageBox.warning(self, "Export Failed", message)

    def _show_status(self, message: str) -> None:
        self._status_label.setText(message)
        self._status_label.setVisible(bool(message))

    def reject(self) -> None:
        """Block closing while a worker is actively running."""
        worker = self._worker
        if worker is not None and worker.isRunning():
            return
        self._wait_worker()
        super().reject()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Stop any running worker before the dialog window closes."""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.stop()
        else:
            self._wait_worker()
        super().closeEvent(a0)
