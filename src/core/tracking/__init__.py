"""Shared tracking engines."""

from core.tracking.point_tracker import track_planar_range, track_point_range
from core.tracking.planar_tracker import (
    PlanarTrackingOptions,
    PlanarTrackingResult,
    TrackingReference,
    TrackingSession,
    repair_planar_gaps,
    track_planar_homography_range,
)
from core.tracking.backend import TrackingMode, TrackingTarget
from core.tracking.engine import (
    CameraMotionBackend,
    ClassicalFeatureBackend,
    DeepFeatureMatchingBackend,
    DeepPointTrackingBackend,
    OpticalFlowBackend,
    PlanarHomographyBackend,
    ReIdentificationBackend,
    SegmentationTrackingBackend,
    TrackingEngine,
)
from core.tracking.camera_tracker import CameraMotionResult, track_camera_motion_range
from core.tracking.object_tracker import ObjectTrackingResult, track_object_range
from core.tracking.benchmark import TrackingBenchmarkMetrics, benchmark_planar
from core.tracking.inference_queue import InferenceJob, InferenceQueue

__all__ = ["track_planar_range", "track_point_range", "track_planar_homography_range",
           "PlanarTrackingOptions", "PlanarTrackingResult", "TrackingReference",
           "TrackingSession", "repair_planar_gaps", "TrackingMode", "TrackingTarget",
           "TrackingEngine", "CameraMotionResult", "track_camera_motion_range",
           "ObjectTrackingResult", "track_object_range", "ClassicalFeatureBackend",
           "OpticalFlowBackend", "PlanarHomographyBackend", "CameraMotionBackend",
           "DeepPointTrackingBackend", "DeepFeatureMatchingBackend",
           "SegmentationTrackingBackend", "ReIdentificationBackend"]
__all__ += ["TrackingBenchmarkMetrics", "benchmark_planar"]
__all__ += ["InferenceJob", "InferenceQueue"]
