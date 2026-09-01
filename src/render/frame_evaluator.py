"""Background frame evaluation with latest-wins requests and prefetch."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from config.constants import DEFAULT_MAX_PREFETCH_FRAMES
from core.audio import FrameWithAudio

if TYPE_CHECKING:
    from core.project import Project


class FrameEvaluationWorker(QThread):
    """Evaluates frames off the UI thread; always prefers the newest request."""

    frame_ready = pyqtSignal(str, int, object)  # node_id, frame_num, ndarray | None

    def __init__(self, project: Project) -> None:
        super().__init__()
        self._project = project
        self._lock = threading.Lock()
        self._pending: tuple[str, int] | None = None
        self._playing = False
        self._running = True
        self._wake = threading.Event()
        # Global ceiling applied on top of the per-Viewer prefetch property;
        # tunable at runtime from Preferences without restarting playback.
        self._max_prefetch: int = DEFAULT_MAX_PREFETCH_FRAMES

    def set_max_prefetch(self, frame_count: int) -> None:
        """Cap prefetch-ahead frames regardless of the active Viewer's setting."""
        self._max_prefetch = max(0, int(frame_count))

    def request_frame(self, node_id: str, frame_num: int) -> None:
        """Queue a frame; replaces any older pending request (drop-on-lag)."""
        with self._lock:
            self._pending = (node_id, frame_num)
        self._wake.set()

    def set_playing(self, playing: bool) -> None:
        """Enable short prefetch ahead of the playhead while playing."""
        self._playing = playing

    def set_project(self, project: Project) -> None:
        """Point the worker at a newly loaded project document."""
        with self._lock:
            self._project = project
            self._pending = None
        self._wake.set()

    def stop(self) -> None:
        """Stop the worker thread and wait for the current evaluation to finish."""
        self._running = False
        self._wake.set()
        self.requestInterruption()
        if not self.wait(2000):
            self.terminate()
            self.wait(500)

    def run(self) -> None:
        while self._running and not self.isInterruptionRequested():
            request = self._take_pending()
            if request is None:
                self._wake.wait(0.05)
                self._wake.clear()
                continue

            node_id, frame_num = request
            frame = self._evaluate(node_id, frame_num)
            self.frame_ready.emit(node_id, frame_num, frame)

            if self._playing and self._has_no_pending():
                self._prefetch(node_id, frame_num)
                if self._has_no_pending():
                    self._wake.wait(0.001)

    def _take_pending(self) -> tuple[str, int] | None:
        with self._lock:
            request = self._pending
            self._pending = None
            return request

    def _has_no_pending(self) -> bool:
        with self._lock:
            return self._pending is None

    def _evaluate(self, node_id: str, frame_num: int) -> np.ndarray | FrameWithAudio | None:
        try:
            result = self._project.evaluate_node(node_id, frame_num)
        except Exception as exc:  # noqa: BLE001
            self._project.log_exception(exc)
            return None
        if isinstance(result, FrameWithAudio):
            return FrameWithAudio(
                frame=np.ascontiguousarray(result.frame),
                audio=result.audio,
            )
        if isinstance(result, np.ndarray):
            return np.ascontiguousarray(result)
        return None

    def _prefetch(self, node_id: str, frame_num: int) -> None:
        """Warm the cache for the next few frames while the UI displays."""
        settings = self._project.get_preview_settings()
        count = min(settings.prefetch_frames, self._max_prefetch)
        if count <= 0:
            return
        max_frame = self._project.max_frame
        for offset in range(1, count + 1):
            if not self._has_no_pending():
                return
            nxt = frame_num + offset
            if nxt > max_frame:
                return
            self._evaluate(node_id, nxt)
