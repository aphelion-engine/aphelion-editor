from typing import Any

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.events import ObserverEvent
from core.project import Project
from render.frame_evaluator import FrameEvaluationWorker


class ViewportWidget(QWidget):
    """Video preview viewport with background frame evaluation."""

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._pending_request: tuple[str, int] | None = None
        self._displayed_frame = -1
        self._image_buffer: np.ndarray | None = None

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(200, 100)
        layout.addWidget(self.label)
        self.setLayout(layout)

        self._worker = FrameEvaluationWorker(project)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.start()

        self._playback_timer = QTimer()
        self._playback_timer.timeout.connect(self.request_update)

        self.project.subscribe(self.on_project_changed)
        self.request_update()

    def on_project_changed(self, event: ObserverEvent, _data: Any) -> None:
        if event in {
            ObserverEvent.FrameChanged,
            ObserverEvent.NodeModified,
            ObserverEvent.ConnectionCreated,
            ObserverEvent.ConnectionRemoved,
            ObserverEvent.NodeAdded,
            ObserverEvent.NodeRemoved,
        }:
            self.request_update()

    def request_update(self) -> None:
        viewer_id = self.project.active_viewer
        frame_num = self.project.current_frame

        if not viewer_id:
            self.display_frame(self._blank_frame())
            return

        cached = self.project.dependency_graph.get_cached(viewer_id, frame_num, "frame")
        if cached is not None:
            self._displayed_frame = frame_num
            self.display_frame(cached)
            return

        self._pending_request = (viewer_id, frame_num)
        self._worker.request_frame(viewer_id, frame_num)

    def _on_frame_ready(self, node_id: str, frame_num: int, frame: object) -> None:
        if self._pending_request != (node_id, frame_num):
            return
        if frame_num != self.project.current_frame or node_id != self.project.active_viewer:
            return

        self._pending_request = None
        self._displayed_frame = frame_num

        if isinstance(frame, np.ndarray):
            self.display_frame(frame)
        else:
            self.display_frame(self._blank_frame())

    def _blank_frame(self) -> np.ndarray:
        return np.zeros((self.project.height, self.project.width, 3), dtype=np.uint8)

    def display_frame(self, frame: np.ndarray) -> None:
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)

        h, w = frame.shape[:2]

        if len(frame.shape) == 3 and frame.shape[2] == 3:
            frame_rgb = np.ascontiguousarray(frame[:, :, ::-1])
            bytes_per_line = 3 * w
            q_img = QImage(
                frame_rgb.data,
                w,
                h,
                bytes_per_line,
                QImage.Format.Format_RGB888,
            )
        else:
            gray = np.ascontiguousarray(frame)
            bytes_per_line = w
            q_img = QImage(
                gray.data,
                w,
                h,
                bytes_per_line,
                QImage.Format.Format_Grayscale8,
            )

        pixmap = QPixmap.fromImage(q_img.copy())
        target_width = self.label.width() if self.label.width() > 0 else 800
        self.label.setPixmap(
            pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
        )

    def set_playback_active(self, active: bool) -> None:
        if active:
            interval = max(1, 1000 // self.project.fps)
            self._playback_timer.start(interval)
        else:
            self._playback_timer.stop()

    def closeEvent(self, event) -> None:
        self._worker.stop()
        super().closeEvent(event)
