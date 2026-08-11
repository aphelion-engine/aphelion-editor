"""Video preview viewport — aspect-aware display, async evaluation only."""

from __future__ import annotations

from typing import Any

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.events import ObserverEvent
from core.project import Project
from render.frame_evaluator import FrameEvaluationWorker
from render.preview import ViewportFitMode


class ViewportWidget(QWidget):
    """Shows the active Viewer output without blocking the UI thread."""

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._pending_request: tuple[str, int] | None = None
        self._displayed_frame = -1
        self._image_buffer: np.ndarray | None = None

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setObjectName("ViewportLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(200, 100)
        layout.addWidget(self.label)
        self.setLayout(layout)
        self._apply_background()

        self._worker = FrameEvaluationWorker(project)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.start()

        self.project.subscribe(self.on_project_changed)
        self.request_update()

    def set_project(self, project: Project) -> None:
        """Retarget this viewport at a newly loaded project."""
        self.project.unsubscribe(self.on_project_changed)
        self.project = project
        self._worker.set_project(project)
        self._pending_request = None
        self._displayed_frame = -1
        self._image_buffer = None
        self.project.subscribe(self.on_project_changed)
        self._apply_background()
        self.request_update()

    def on_project_changed(self, event: ObserverEvent, _data: Any) -> None:
        if event in {
            ObserverEvent.FrameChanged,
            ObserverEvent.NodeModified,
            ObserverEvent.ConnectionCreated,
            ObserverEvent.ConnectionRemoved,
            ObserverEvent.NodeAdded,
            ObserverEvent.NodeRemoved,
            ObserverEvent.ActiveViewerChanged,
            ObserverEvent.ProjectModified,
        }:
            if event in {
                ObserverEvent.NodeModified,
                ObserverEvent.ActiveViewerChanged,
                ObserverEvent.ProjectModified,
            }:
                self._apply_background()
            self.request_update()

    def _apply_background(self) -> None:
        """Match letterbox color to the active Viewer background property."""
        hex_color = self.project.get_preview_settings().background_hex
        self.label.setStyleSheet(
            f"QLabel#ViewportLabel {{ background-color: {hex_color}; color: #666666; }}"
        )

    def request_update(self) -> None:
        viewer_id = self.project.active_viewer
        frame_num = self.project.current_frame

        if not viewer_id:
            self._image_buffer = None
            self._apply_background()
            self.label.setText("No active Viewer")
            self.label.setPixmap(QPixmap())
            return

        self._pending_request = (viewer_id, frame_num)
        self._worker.request_frame(viewer_id, frame_num)

    def _on_frame_ready(self, node_id: str, frame_num: int, frame: object) -> None:
        if self._pending_request != (node_id, frame_num):
            return
        if (
            frame_num != self.project.current_frame
            or node_id != self.project.active_viewer
        ):
            return

        self._pending_request = None
        self._displayed_frame = frame_num

        if isinstance(frame, np.ndarray):
            self.display_frame(frame)
        else:
            self.display_frame(self._blank_frame())

    def _blank_frame(self) -> np.ndarray:
        settings = self.project.get_preview_settings()
        width = max(16, settings.max_width)
        height = max(16, int(round(width * 9 / 16)))
        return np.zeros((height, width, 3), dtype=np.uint8)

    def display_frame(self, frame: np.ndarray) -> None:
        """Present ``frame`` with Viewer fit mode; never stretch by default."""
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)

        h, w = frame.shape[:2]
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            frame_rgb = np.ascontiguousarray(frame)
            self._image_buffer = frame_rgb
            q_img = QImage(
                frame_rgb.data,
                w,
                h,
                3 * w,
                QImage.Format.Format_RGB888,
            )
        else:
            gray = np.ascontiguousarray(frame)
            self._image_buffer = gray
            q_img = QImage(
                gray.data,
                w,
                h,
                w,
                QImage.Format.Format_Grayscale8,
            )

        # Copy once into Qt-owned memory so the numpy buffer can be reused.
        pixmap = QPixmap.fromImage(q_img.copy())
        self.label.setText("")
        self.label.setPixmap(self._fit_pixmap(pixmap))

    def _fit_pixmap(self, pixmap: QPixmap) -> QPixmap:
        target = self.label.size()
        if target.width() <= 1 or target.height() <= 1:
            return pixmap

        fit_mode = self.project.get_preview_settings().fit_mode
        # FastTransformation keeps playback fluid; proxy frames are already small.
        xform = Qt.TransformationMode.FastTransformation

        if fit_mode == ViewportFitMode.Stretch:
            return pixmap.scaled(
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                xform,
            )
        if fit_mode == ViewportFitMode.Fill:
            return pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                xform,
            )
        return pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            xform,
        )

    def set_playback_active(self, active: bool) -> None:
        """Hint the worker to prefetch; timeline alone drives frame changes."""
        self._worker.set_playing(active)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        if self._image_buffer is not None:
            self.display_frame(self._image_buffer)

    def closeEvent(self, event: Any) -> None:
        self._worker.stop()
        super().closeEvent(event)
