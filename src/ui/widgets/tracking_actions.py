"""Shared tracking-job runner used by the viewport overlay and Properties panel.

Running a track shows a modal progress dialog and, on success, commits the
result through the undo stack — kept here so any UI surface (viewport
overlay, properties panel, future toolbar buttons) triggers tracking the
same way instead of re-implementing the worker/dialog wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.animation import AnimationCurve
from core.history import SetPlanarTrackCommand, SetTrackCommand
from core.nodes.tracking_nodes import PlanarTrackerNode, TrackerNode
from render.tracking_worker import (
    PlanarTrackingWorker,
    PointTrackingWorker,
    TrackingRequest,
)

if TYPE_CHECKING:
    from core.history import HistoryStack
    from core.project import Project
    from PyQt6.QtWidgets import QWidget

CORNER_NAMES: tuple[str, str, str, str] = (
    "top_left",
    "top_right",
    "bottom_right",
    "bottom_left",
)


def split_xy_curves(
    result: dict[int, tuple[float, float]],
) -> tuple[AnimationCurve, AnimationCurve]:
    """Split a tracker's ``{frame: (x, y)}`` result into two curves."""
    curve_x = AnimationCurve()
    curve_y = AnimationCurve()
    for frame_num, (x, y) in result.items():
        curve_x.set_keyframe(frame_num, x)
        curve_y.set_keyframe(frame_num, y)
    return curve_x, curve_y


def run_tracking(
    node: TrackerNode | PlanarTrackerNode,
    node_id: str,
    project: Project,
    history: HistoryStack,
    *,
    direction: int,
    parent: QWidget,
) -> bool:
    """Track ``node`` forward or backward from the current frame.

    Shows a modal progress dialog for the duration of the job and, on
    success, commits the result through an undoable command.

    Parameters:
        direction: ``1`` to track to the end of the project, ``-1`` to
            track back to frame 0.
        parent: Widget the progress/error dialogs are parented to.

    Returns:
        ``True`` when a tracking result was committed.
    """
    # Deferred imports: both pull in ``ui.dialogs``, which transitively
    # imports this package (via ``ui.widgets`` re-exports) — importing them
    # at module scope would create a circular import.
    from PyQt6.QtWidgets import QMessageBox

    from ui.dialogs import TrackingProgressDialog

    start = project.current_frame
    end = project.max_frame if direction > 0 else 0
    frame_numbers = (
        list(range(start, end + 1))
        if direction > 0
        else list(range(start, end - 1, -1))
    )
    if len(frame_numbers) < 2:
        QMessageBox.information(
            parent, "Tracking", "Nothing to track from the current frame."
        )
        return False

    request = TrackingRequest(
        node_id=node_id,
        frame_numbers=frame_numbers,
        region_size=node.region_size_normalized(),
        search_radius=node.search_radius_normalized(),
    )

    if isinstance(node, PlanarTrackerNode):
        worker = PlanarTrackingWorker(project, request, node.seed_corners())
        dialog = TrackingProgressDialog(worker, title=f"Tracking {node.name}", parent=parent)
        if not dialog.run_modal():
            if dialog.error:
                QMessageBox.warning(parent, "Tracking Failed", dialog.error)
            return False
        raw = dialog.result or {}
        corner_curves = {
            corner: split_xy_curves(raw.get(corner, {})) for corner in CORNER_NAMES
        }
        history.push(SetPlanarTrackCommand(node_id, corner_curves))
        return True

    worker = PointTrackingWorker(project, request, node.seed_position())
    dialog = TrackingProgressDialog(worker, title=f"Tracking {node.name}", parent=parent)
    if not dialog.run_modal():
        if dialog.error:
            QMessageBox.warning(parent, "Tracking Failed", dialog.error)
        return False
    curve_x, curve_y = split_xy_curves(dialog.result or {})
    history.push(SetTrackCommand(node_id, curve_x, curve_y))
    return True


def clear_tracking(
    node: TrackerNode | PlanarTrackerNode,
    node_id: str,
    history: HistoryStack,
) -> None:
    """Remove all tracked keyframes from ``node``, keeping its seed position."""
    if isinstance(node, PlanarTrackerNode):
        empty_curves = {
            corner: (AnimationCurve(), AnimationCurve()) for corner in CORNER_NAMES
        }
        history.push(SetPlanarTrackCommand(node_id, empty_curves))
        return
    history.push(SetTrackCommand(node_id, AnimationCurve(), AnimationCurve()))
