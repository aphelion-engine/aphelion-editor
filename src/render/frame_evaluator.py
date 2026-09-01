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
    """
    Background frame evaluator optimized for interactive playback.

    Design goals:
    - Latest request always wins.
    - Avoid unnecessary locking in the hot path.
    - Avoid unnecessary ndarray copies.
    - Prefetch sequentially while the UI is idle.
    - Never allow stale prefetch work to starve a newer request.
    """

    frame_ready = pyqtSignal(str, int, object)

    def __init__(self, project: Project) -> None:
        super().__init__()

        self._project = project

        # The request lock is extremely short-lived.
        self._request_lock = threading.Lock()

        self._pending: tuple[str, int] | None = None

        # These are only written by the controlling/UI thread and read by
        # the worker. CPython's simple bool/int reads are atomic enough here.
        self._playing = False
        self._running = True
        self._max_prefetch = DEFAULT_MAX_PREFETCH_FRAMES

        self._wake = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_max_prefetch(self, frame_count: int) -> None:
        """Set the maximum number of frames prefetched ahead."""
        self._max_prefetch = max(0, int(frame_count))

    def request_frame(self, node_id: str, frame_num: int) -> None:
        """
        Request a frame.

        Latest-wins semantics mean that if the worker is busy, only the
        newest request matters.
        """
        with self._request_lock:
            self._pending = (node_id, int(frame_num))

        self._wake.set()

    def set_playing(self, playing: bool) -> None:
        """Enable/disable playback prefetch."""
        self._playing = bool(playing)

        # Wake the worker immediately when playback starts.
        if playing:
            self._wake.set()

    def set_project(self, project: Project) -> None:
        """Switch the worker to a new project."""
        with self._request_lock:
            self._project = project
            self._pending = None

        self._wake.set()

    def stop(self) -> None:
        """Stop the worker and wait for the active evaluation."""
        self._running = False
        self.requestInterruption()
        self._wake.set()

        if not self.wait(2000):
            self.terminate()
            self.wait(500)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main worker loop.

        We intentionally avoid polling every 50 ms. Event-driven wakeups
        make idle playback essentially free.
        """
        while self._running and not self.isInterruptionRequested():
            request = self._take_pending()

            if request is None:
                self._wake.wait()
                self._wake.clear()
                continue

            node_id, frame_num = request

            frame = self._evaluate(node_id, frame_num)

            # Do not emit stale frames if a newer request arrived while
            # evaluation was running.
            if self._has_pending():
                continue

            self.frame_ready.emit(node_id, frame_num, frame)

            if self._playing:
                self._prefetch(node_id, frame_num)

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def _take_pending(self) -> tuple[str, int] | None:
        with self._request_lock:
            request = self._pending
            self._pending = None
            return request

    def _has_pending(self) -> bool:
        """
        Cheap latest-request check.

        This is called frequently during prefetch, so keep it tiny.
        """
        with self._request_lock:
            return self._pending is not None

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        node_id: str,
        frame_num: int,
    ) -> np.ndarray | FrameWithAudio | None:
        """
        Evaluate one frame.

        Avoid copying arrays unless they are actually non-contiguous.
        """
        try:
            result = self._project.evaluate_node(node_id, frame_num)

        except Exception as exc:  # noqa: BLE001
            self._project.log_exception(exc)
            return None

        if isinstance(result, FrameWithAudio):
            frame = result.frame

            if isinstance(frame, np.ndarray) and not frame.flags.c_contiguous:
                frame = np.ascontiguousarray(frame)

            return FrameWithAudio(
                frame=frame,
                audio=result.audio,
            )

        if isinstance(result, np.ndarray):
            if result.flags.c_contiguous:
                return result

            return np.ascontiguousarray(result)

        return None

    # ------------------------------------------------------------------
    # Prefetch
    # ------------------------------------------------------------------

    def _prefetch(self, node_id: str, frame_num: int) -> None:
        """
        Warm sequential frames ahead of playback.

        Prefetch is deliberately interruptible: the instant the UI asks
        for another frame, prefetching stops.
        """
        if self._max_prefetch <= 0:
            return

        project = self._project

        # Read settings once rather than once per frame.
        settings = project.get_preview_settings()

        count = min(
            max(0, int(settings.prefetch_frames)),
            self._max_prefetch,
        )

        if count <= 0:
            return

        max_frame = project.max_frame

        # Clamp once rather than checking the upper bound every iteration.
        end_frame = min(frame_num + count, max_frame)

        for next_frame in range(frame_num + 1, end_frame + 1):
            # New UI request always wins.
            if self._has_pending():
                return

            # Don't waste time after shutdown.
            if not self._running or self.isInterruptionRequested():
                return

            self._evaluate(node_id, next_frame)
