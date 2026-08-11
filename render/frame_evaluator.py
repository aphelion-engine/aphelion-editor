"""Background frame evaluation worker (keeps decode off the UI thread)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from core.project import Project


class FrameEvaluationWorker(QThread):
    """Evaluates one frame at a time on a background thread."""

    frame_ready = pyqtSignal(str, int, object)  # node_id, frame_num, ndarray | None

    def __init__(self, project: Project) -> None:
        super().__init__()
        self._project = project
        self._lock = threading.Lock()
        self._pending: tuple[str, int] | None = None
        self._running = True

    def request_frame(self, node_id: str, frame_num: int) -> None:
        with self._lock:
            self._pending = (node_id, frame_num)

    def stop(self) -> None:
        self._running = False
        self.requestInterruption()
        self.wait(2000)

    def run(self) -> None:
        while self._running and not self.isInterruptionRequested():
            request: tuple[str, int] | None
            with self._lock:
                request = self._pending
                self._pending = None

            if request is None:
                self.msleep(5)
                continue

            node_id, frame_num = request
            try:
                result = self._project.evaluate_node(node_id, frame_num)
            except Exception as exc:  # noqa: BLE001
                self._project.log_exception(exc)
                result = None

            if isinstance(result, np.ndarray):
                self.frame_ready.emit(node_id, frame_num, result)
            else:
                self.frame_ready.emit(node_id, frame_num, None)
