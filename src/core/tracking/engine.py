"""Unified tracking orchestration and backend capability registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from core.tracking.backend import (
    BackendCapabilities,
    BackendHealth,
    BackendProposal,
    BackendStatus,
    TrackingBackend,
    TrackingMode,
    TrackingTarget,
)
from core.tracking.neural import MLInferenceEngine
from core.tracking.camera_tracker import track_camera_motion_range
from core.tracking.planar_tracker import (
    PlanarTrackingOptions,
    TrackingSession,
    track_planar_homography_range,
)


@dataclass(frozen=True)
class TargetAnalysis:
    target_type: TrackingTarget
    texture_score: float
    edge_score: float
    planar_score: float
    scale: float
    recommendations: tuple[str, ...]


@dataclass
class FusedTrackingDecision:
    frame_number: int
    proposal: BackendProposal | None
    confidence: float
    backends: dict[str, float] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)


class ConfidenceFusion:
    """Fuse independent backend evidence without allowing one bad proposal to win."""

    @staticmethod
    def score(proposal: BackendProposal) -> float:
        diagnostics = proposal.diagnostics
        weights = {
            "flow": .16,
            "forward_backward": .14,
            "inlier_ratio": .16,
            "reprojection": .14,
            "reference": .14,
            "motion": .10,
            "visibility": .08,
            "reid": .08,
        }
        score = proposal.confidence
        total = 1.0
        for key, weight in weights.items():
            if key in diagnostics:
                score = score * (1.0 - weight) + float(np.clip(diagnostics[key], 0, 1)) * weight
        if not proposal.visible:
            score *= .85
        return float(np.clip(score / total, 0, 1))

    def choose(self, proposals: list[BackendProposal], frame_number: int) -> FusedTrackingDecision:
        if not proposals:
            return FusedTrackingDecision(frame_number, None, 0.0)
        scored = [(self.score(item), item) for item in proposals]
        scored.sort(key=lambda item: item[0], reverse=True)
        winner_score, winner = scored[0]
        rejected = [item.backend for score, item in scored[1:] if score < winner_score * .72]
        winner.accepted = True
        return FusedTrackingDecision(frame_number, winner, winner_score,
                                     {item.backend: score for score, item in scored}, rejected)


class ClassicalFeatureBackend:
    capabilities = BackendCapabilities(
        "classical_features", BackendStatus.AVAILABLE,
        (TrackingTarget.POINT, TrackingTarget.OBJECT, TrackingTarget.SURFACE,
         TrackingTarget.FLOOR, TrackingTarget.WALL, TrackingTarget.SCREEN),
        tuple(TrackingMode),
    )

    def __init__(self, max_features: int = 600) -> None:
        self.detector = cv2.ORB_create(nfeatures=max_features, fastThreshold=7)

    def propose(self, frame_number: int, frame: np.ndarray, context: dict[str, Any]) -> BackendProposal | None:
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame[..., :3], cv2.COLOR_RGB2GRAY)
        keypoints = self.detector.detect(gray, context.get("mask"))
        confidence = min(1.0, len(keypoints) / 80.0)
        return BackendProposal(frame_number, self.capabilities.name, confidence, bool(keypoints),
                               points=np.asarray([keypoint.pt for keypoint in keypoints], np.float32),
                               diagnostics={"reference": confidence, "visibility": float(bool(keypoints))},
                               state="TRACKING" if keypoints else "WEAK")

    def reset(self) -> None:
        return None


class OpticalFlowBackend(ClassicalFeatureBackend):
    capabilities = BackendCapabilities(
        "optical_flow", BackendStatus.AVAILABLE,
        (TrackingTarget.POINT, TrackingTarget.OBJECT, TrackingTarget.SURFACE),
        (TrackingMode.AUTO, TrackingMode.FAST, TrackingMode.BALANCED, TrackingMode.ACCURATE),
    )


class PlanarHomographyBackend:
    capabilities = BackendCapabilities(
        "planar_homography", BackendStatus.AVAILABLE,
        (TrackingTarget.SURFACE, TrackingTarget.FLOOR, TrackingTarget.WALL,
         TrackingTarget.SCREEN, TrackingTarget.LARGE_AREA),
        tuple(TrackingMode),
    )

    def propose(self, frame_number: int, frame: np.ndarray, context: dict[str, Any]) -> BackendProposal | None:
        # Planar work is an offline range operation; frame proposals are made
        # by ``track_range`` so references and motion history are shared.
        return None

    def track_range(self, sample_frame, frame_numbers, initial_corners, **kwargs):
        return track_planar_homography_range(sample_frame, frame_numbers,
                                             initial_corners=initial_corners, **kwargs)

    def reset(self) -> None:
        return None


class CameraMotionBackend:
    capabilities = BackendCapabilities(
        "camera_motion", BackendStatus.AVAILABLE,
        (TrackingTarget.AUTO, TrackingTarget.LARGE_AREA), tuple(TrackingMode),
    )

    def propose(self, frame_number: int, frame: np.ndarray, context: dict[str, Any]) -> BackendProposal | None:
        return None

    def track_range(self, sample_frame, frame_numbers, **kwargs):
        return track_camera_motion_range(sample_frame, frame_numbers, **kwargs)

    def reset(self) -> None:
        return None


class OptionalDeepBackend:
    """Capability-aware adapter for CoTracker/LightGlue/SAM-style ONNX models.

    The adapter is deliberately model-agnostic: installing a model provider is
    optional, and geometry still validates any future neural proposal.
    """

    def __init__(self, name: str, target_types: tuple[TrackingTarget, ...], inference: MLInferenceEngine | None = None) -> None:
        self.inference = inference or MLInferenceEngine()
        self.capabilities = BackendCapabilities(
            name,
            BackendStatus.OPTIONAL if self.inference.available else BackendStatus.UNAVAILABLE,
            target_types, (TrackingMode.ACCURATE, TrackingMode.MAXIMUM, TrackingMode.DEEP),
            requires_model=name, reason="Optional ONNX model/provider is not installed" if not self.inference.available else "")

    def propose(self, frame_number: int, frame: np.ndarray, context: dict[str, Any]) -> BackendProposal | None:
        # Model-specific adapters plug in here; never claim a neural result when
        # no verified model is available.
        return None

    def reset(self) -> None:
        return None


class DeepPointTrackingBackend(OptionalDeepBackend):
    def __init__(self, inference: MLInferenceEngine | None = None) -> None:
        super().__init__("deep_point", (TrackingTarget.POINT,), inference)


class DeepFeatureMatchingBackend(OptionalDeepBackend):
    def __init__(self, inference: MLInferenceEngine | None = None) -> None:
        super().__init__("deep_matching", (TrackingTarget.SURFACE, TrackingTarget.OBJECT), inference)


class SegmentationTrackingBackend(OptionalDeepBackend):
    def __init__(self, inference: MLInferenceEngine | None = None) -> None:
        super().__init__("segmentation", (TrackingTarget.OBJECT, TrackingTarget.PERSON), inference)


class ReIdentificationBackend(OptionalDeepBackend):
    def __init__(self, inference: MLInferenceEngine | None = None) -> None:
        super().__init__("reidentification", (TrackingTarget.OBJECT, TrackingTarget.PERSON), inference)


class TrackingEngine:
    """Backend registry, automatic mode selection, fusion, and planar facade."""

    def __init__(self, mode: TrackingMode = TrackingMode.AUTO, *, use_gpu: str = "auto") -> None:
        self.mode = mode
        self.inference = MLInferenceEngine(use_gpu)
        self.backends: dict[str, TrackingBackend] = {}
        self.health: dict[str, BackendHealth] = {}
        self.fusion = ConfidenceFusion()
        self.register(OpticalFlowBackend())
        self.register(ClassicalFeatureBackend())
        self.register(PlanarHomographyBackend())
        self.register(CameraMotionBackend())
        self.register(DeepPointTrackingBackend(self.inference))
        self.register(DeepFeatureMatchingBackend(self.inference))
        self.register(SegmentationTrackingBackend(self.inference))
        self.register(ReIdentificationBackend(self.inference))

    def register(self, backend: TrackingBackend) -> None:
        name = backend.capabilities.name
        self.backends[name] = backend
        self.health[name] = BackendHealth()

    def capabilities(self) -> list[BackendCapabilities]:
        return [backend.capabilities for backend in self.backends.values()]

    def analyze_target(self, frame: np.ndarray, mask: np.ndarray | None = None) -> TargetAnalysis:
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame[..., :3], cv2.COLOR_RGB2GRAY)
        region = gray[mask > 0] if mask is not None and np.any(mask) else gray
        texture = float(np.clip(np.std(region) / 64.0, 0, 1))
        edges = cv2.Canny(gray, 60, 160)
        edge_score = float(np.clip(np.mean(edges > 0) * 8, 0, 1))
        planar = float(np.clip(.45 * texture + .55 * edge_score, 0, 1))
        target = TrackingTarget.SURFACE if planar > .45 else TrackingTarget.OBJECT
        recommendations = ("optical_flow", "homography") if target == TrackingTarget.SURFACE else ("motion_model", "reidentification")
        return TargetAnalysis(target, texture, edge_score, planar, 1.0, recommendations)

    def propose(self, frame_number: int, frame: np.ndarray, *, target: TrackingTarget = TrackingTarget.AUTO,
                context: dict[str, Any] | None = None) -> FusedTrackingDecision:
        context = dict(context or {})
        if target == TrackingTarget.AUTO:
            target = self.analyze_target(frame, context.get("mask")).target_type
        proposals: list[BackendProposal] = []
        for name, backend in self.backends.items():
            capabilities = backend.capabilities
            if target not in capabilities.target_types:
                continue
            if self.mode not in capabilities.modes and self.mode not in (TrackingMode.AUTO, TrackingMode.BALANCED):
                continue
            proposal = backend.propose(frame_number, frame, context)
            if proposal is not None:
                proposals.append(proposal)
                self.health[name].observe(proposal.confidence, frame_number, proposal.visible)
        return self.fusion.choose(proposals, frame_number)

    def track_planar(self, sample_frame, frame_numbers, initial_corners, *, options=None,
                     session: TrackingSession | None = None, **kwargs):
        """Use the enterprise session-backed planar specialist."""
        if options is None:
            options = PlanarTrackingOptions()
        return track_planar_homography_range(sample_frame, frame_numbers,
                                             initial_corners=initial_corners,
                                             options=options, session=session, **kwargs)
