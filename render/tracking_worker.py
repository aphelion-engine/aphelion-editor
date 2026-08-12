"""Background 2D/planar point tracking off the UI thread."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from core.tracking import track_planar_range, track_point_range

if TYPE_CHECKING:
    from core.project import Project

NormalizedPoint = tuple[float, float]


@dataclass(frozen=True, slots=True)
class TrackingRequest:
    """Parameters for a single tracking job."""

    node_id: str
    frame_numbers: list[int]
    region_size: NormalizedPoint
    search_radius: float


class PointTrackingWorker(QThread):
    """Track a single ``TrackerNode`` point across a frame range."""

    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        project: Project,
        request: TrackingRequest,
        initial_center: NormalizedPoint,
    ) -> None:
        super().__init__()
        self._project = project
        self._request = request
        self._initial_center = initial_center
        self._cancelled = False

    def cancel(self) -> None:
        """Request a graceful stop after the current frame."""
        self._cancelled = True

    def run(self) -> None:
        try:
            sampler = _build_frame_sampler(self._project, self._request.node_id)
        except LookupError as exc:
            self.failed.emit(str(exc))
            return

        result = track_point_range(
            sampler,
            self._request.frame_numbers,
            initial_center=self._initial_center,
            region_size=self._request.region_size,
            search_radius=self._request.search_radius,
            should_cancel=lambda: self._cancelled,
            on_progress=lambda done, total: self.progress.emit(done, total),
        )
        if not result:
            self.failed.emit("Tracking failed: no frames could be matched.")
            return
        self.finished_ok.emit(result)


class PlanarTrackingWorker(QThread):
    """Track a ``PlanarTrackerNode``'s four corners across a frame range."""

    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        project: Project,
        request: TrackingRequest,
        initial_corners: tuple[
            NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint
        ],
    ) -> None:
        super().__init__()
        self._project = project
        self._request = request
        self._initial_corners = initial_corners
        self._cancelled = False

    def cancel(self) -> None:
        """Request a graceful stop after the current frame."""
        self._cancelled = True

    def run(self) -> None:
        try:
            sampler = _build_frame_sampler(self._project, self._request.node_id)
        except LookupError as exc:
            self.failed.emit(str(exc))
            return

        top_left, top_right, bottom_right, bottom_left = track_planar_range(
            sampler,
            self._request.frame_numbers,
            initial_corners=self._initial_corners,
            region_size=self._request.region_size,
            search_radius=self._request.search_radius,
            should_cancel=lambda: self._cancelled,
            on_progress=lambda done, total: self.progress.emit(done, total),
        )
        if not any((top_left, top_right, bottom_right, bottom_left)):
            self.failed.emit("Tracking failed: no frames could be matched.")
            return
        self.finished_ok.emit(
            {
                "top_left": top_left,
                "top_right": top_right,
                "bottom_right": bottom_right,
                "bottom_left": bottom_left,
            }
        )


def _build_frame_sampler(
    project: Project, node_id: str
) -> Callable[[int], "np.ndarray | None"]:
    """Return a callable sampling the tracker node's upstream "frame" plate.

    Raises:
        LookupError: When the node has no connected "frame" input.
    """
    frame_connection = next(
        (
            conn
            for conn in project.dependency_graph.get_input_connections(node_id)
            if conn.input_slot == "frame"
        ),
        None,
    )
    if frame_connection is None:
        raise LookupError("Connect a frame input before tracking.")

    def sample(frame_num: int) -> np.ndarray | None:
        result = project.evaluate_node(
            frame_connection.output_node_id, frame_num, frame_connection.output_slot
        )
        return result if isinstance(result, np.ndarray) else None

    return sample
