"""Professional tracking node surfaces backed by the shared engine.

Heavy work is written by tracking workers into ``tracking_data``. Playback only
reads persisted results, so adding optional ML backends never blocks evaluation.
"""
from __future__ import annotations

from typing import Any

from core.nodes.base import NodeSocketType, NodeValue
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import choice_property, number_property, toggle_property
from core.tracking.backend import TrackingMode, TrackingTarget


class _StoredTrackingNode(FrameNode):
    node_category = "Tracking"
    node_color = (120, 92, 180)
    is_temporal = True

    def __init__(self, name: str | None = None) -> None:
        self.tracking_data: dict[int, dict[str, Any]] = {}
        super().__init__(name)

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)
        for output in ("x", "y", "confidence", "visible", "predicted", "state", "backend"):
            self.add_output(output, NodeSocketType.Number)
        self.set_property("mode", choice_property(TrackingMode.AUTO, priority=0, group="Tracking",
            label="Quality Mode", description="Automatic hybrid backend selection."))
        self.set_property("use_gpu", choice_property("Auto", priority=1, group="Tracking",
            label="Use GPU", description="Auto, CPU, CUDA, or DirectML when optional providers are installed."))
        self.set_property("deep_recovery", toggle_property(True, priority=2, group="Recovery",
            label="Deep Recovery", description="Allow optional deep backends during recovery."))
        self.set_property("reidentification", toggle_property(True, priority=3, group="Recovery",
            label="Re-identification", description="Verify returning targets against long-term visual memory."))

    def input_required(self, slot: str) -> bool:
        return slot != "frame"

    def _result(self, frame_num: int) -> dict[str, float]:
        data = self.tracking_data.get(frame_num, {})
        state = str(data.get("state", "LOST"))
        state_code = {"TRACKING": 1, "WEAK": 2, "PARTIALLY_VISIBLE": 3,
                      "PARTIALLY_OFFSCREEN": 3, "MOSTLY_OFFSCREEN": 4,
                      "PREDICTING": 5, "OFFSCREEN": 6, "OCCLUDED": 7,
                      "SEARCHING": 8, "SEARCHING_FOR_REENTRY": 8,
                      "VERIFYING": 9, "RECOVERING": 10,
                      "REACQUIRED": 11}.get(state, 0)
        return {"x": float(data.get("x", data.get("position_x", 0.0))),
                "y": float(data.get("y", data.get("position_y", 0.0))),
                "confidence": float(data.get("confidence", 0.0)),
                "visible": float(bool(data.get("visible", False))),
                "predicted": float(bool(data.get("predicted", False))),
                "state": float(state_code), "backend": float(data.get("backend_code", 0))}

    def evaluate(self, frame_num: int) -> NodeValue:
        return self._result(frame_num)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["tracking_data"] = self.tracking_data
        return data

    def apply_document(self, data: dict[str, Any]) -> None:
        super().apply_document(data)
        self.tracking_data = {int(key): value for key, value in (data.get("tracking_data") or {}).items()}


class SmartTrackerNode(_StoredTrackingNode):
    node_type = "Smart Tracker"
    node_description = "Hybrid tracker that switches optical flow, geometry, references, and optional ML backends."

    def _setup_sockets(self) -> None:
        super()._setup_sockets()
        self.set_property("target_type", choice_property(TrackingTarget.AUTO, priority=4, group="Target",
            label="Target Type", description="Auto, point, object, person, or planar surface."))


class ObjectTrackerNode(_StoredTrackingNode):
    node_type = "Object Tracker"
    node_description = "Long-term object tracker with motion prediction, appearance memory, and re-identification."


class DeepPointTrackerNode(_StoredTrackingNode):
    node_type = "Deep Point Tracker"
    node_description = "Optional CoTracker/TAPIR-style point backend with a CPU fallback."


class SegmentationTrackerNode(_StoredTrackingNode):
    node_type = "Segmentation Tracker"
    node_description = "Optional SAM/XMem-style identity mask tracker with occlusion-aware memory."


class CameraTrackerNode(_StoredTrackingNode):
    node_type = "Camera Tracker"
    node_description = "Dominant background motion tracker for camera movement and stabilization."

    def _setup_sockets(self) -> None:
        super()._setup_sockets()
        for output in ("translation_x", "translation_y", "rotation", "scale", "inliers"):
            self.add_output(output, NodeSocketType.Number)

    def _result(self, frame_num: int) -> dict[str, float]:
        result = super()._result(frame_num)
        data = self.tracking_data.get(frame_num, {})
        result.update({key: float(data.get(key, 0.0)) for key in
                       ("translation_x", "translation_y", "rotation", "scale", "inliers")})
        return result


class StabilizerNode(CameraTrackerNode):
    node_type = "Stabilizer"
    node_description = "Camera motion tracker with smoothed trajectory and crop recommendation outputs."


class FloorTrackerNode(SmartTrackerNode):
    node_type = "Floor Tracker"
    node_description = "Surface-specialized hybrid planar tracker for floors and roads."


class WallTrackerNode(SmartTrackerNode):
    node_type = "Wall Tracker"
    node_description = "Surface-specialized hybrid planar tracker for walls, signs, and screens."


class LargeAreaTrackerNode(SmartTrackerNode):
    node_type = "Large Area Tracker"
    node_description = "Distributed-feature tracker for large low-texture surfaces."


class PlanarSurfaceTrackerNode(SmartTrackerNode):
    node_type = "Planar Surface Tracker"
    node_description = "Dedicated four-corner surface tracker for compositing and corner pinning."


class PerspectiveTrackerNode(PlanarSurfaceTrackerNode):
    node_type = "Perspective Tracker"
    node_description = "Perspective-aware planar tracker with homography diagnostics."


class MaskTrackerNode(SegmentationTrackerNode):
    node_type = "Mask Tracker"
    node_description = "Perspective and segmentation-aware mask tracking facade."


class FaceTrackerNode(SegmentationTrackerNode):
    node_type = "Face Tracker"
    node_description = "Optional landmark/segmentation face tracker with CPU fallback."


class MotionPathTrackerNode(_StoredTrackingNode):
    node_type = "Motion Path Tracker"
    node_description = "Produces reusable, smoothed motion paths from tracker results."


PROFESSIONAL_TRACKING_NODE_TYPES = (
    SmartTrackerNode, DeepPointTrackerNode, ObjectTrackerNode, SegmentationTrackerNode,
    CameraTrackerNode, StabilizerNode, FloorTrackerNode, WallTrackerNode,
    LargeAreaTrackerNode, PlanarSurfaceTrackerNode, PerspectiveTrackerNode,
    MaskTrackerNode, FaceTrackerNode, MotionPathTrackerNode,
)
