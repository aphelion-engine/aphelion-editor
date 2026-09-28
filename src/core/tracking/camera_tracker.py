"""Dominant background motion and stabilization tracking backend."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, asdict

import cv2
import numpy as np

from core.tracking.point_tracker import _safe_sample_frame, _to_gray_u8
from core.tracking.model import TrackingState


@dataclass(frozen=True)
class CameraMotionResult:
    frame_number: int
    transform: tuple[tuple[float, ...], ...]
    translation_x: float
    translation_y: float
    rotation: float
    scale: float
    confidence: float
    inlier_count: int
    state: TrackingState
    rejected_points: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state.value
        return data


def track_camera_motion_range(sample_frame: Callable[[int], np.ndarray | None],
                              frame_numbers: list[int], *, max_features: int = 1200,
                              reprojection_error: float = 3.0,
                              should_cancel: Callable[[], bool] | None = None,
                              on_progress: Callable[[int, int], None] | None = None) -> dict[int, CameraMotionResult]:
    """Estimate dominant projective background motion with moving-object rejection."""
    results: dict[int, CameraMotionResult] = {}
    if not frame_numbers:
        return results
    previous = _safe_sample_frame(sample_frame, int(frame_numbers[0]))
    if previous is None:
        return results
    previous_gray = _to_gray_u8(previous)
    detector = cv2.ORB_create(nfeatures=max_features, fastThreshold=10)
    keypoints, descriptors = detector.detectAndCompute(previous_gray, None)
    identity = np.eye(3, dtype=np.float64)
    results[int(frame_numbers[0])] = CameraMotionResult(int(frame_numbers[0]), tuple(map(tuple, identity)),
                                                         0.0, 0.0, 0.0, 1.0, 1.0, len(keypoints), TrackingState.TRACKING)
    cumulative = identity
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    for index, number_raw in enumerate(frame_numbers[1:], 1):
        if should_cancel and should_cancel():
            break
        number = int(number_raw)
        current = _safe_sample_frame(sample_frame, number)
        if current is None:
            results[number] = CameraMotionResult(number, tuple(map(tuple, cumulative)), 0, 0, 0, 1, 0,
                                                  TrackingState.WEAK)
            continue
        current_gray = _to_gray_u8(current)
        current_keypoints, current_descriptors = detector.detectAndCompute(current_gray, None)
        estimate = None
        if descriptors is not None and current_descriptors is not None:
            pairs = matcher.knnMatch(descriptors, current_descriptors, k=2)
            good = [m for m, n in pairs if m.distance < .78 * n.distance]
            if len(good) >= 6:
                source = np.asarray([keypoints[m.queryIdx].pt for m in good], np.float32)
                destination = np.asarray([current_keypoints[m.trainIdx].pt for m in good], np.float32)
                method = getattr(cv2, "USAC_MAGSAC", cv2.RANSAC)
                h, mask = cv2.findHomography(source, destination, method, reprojection_error)
                if h is not None and mask is not None:
                    inliers = mask.ravel().astype(bool)
                    if int(inliers.sum()) >= 6:
                        estimate = h, inliers, source, destination
        if estimate is None:
            result = CameraMotionResult(number, tuple(map(tuple, cumulative)), 0, 0, 0, 1, 0,
                                        TrackingState.WEAK, len(keypoints))
        else:
            h, inliers, source, destination = estimate
            cumulative = h @ cumulative
            affine, _ = cv2.estimateAffinePartial2D(source[inliers], destination[inliers])
            if affine is None:
                tx = float(h[0, 2]); ty = float(h[1, 2]); rotation = 0.; scale = 1.
            else:
                tx, ty = float(affine[0, 2]), float(affine[1, 2])
                scale = float(np.hypot(affine[0, 0], affine[1, 0]))
                rotation = float(np.arctan2(affine[1, 0], affine[0, 0]))
            confidence = float(np.clip(inliers.mean() * min(1., inliers.sum() / 80.), 0, 1))
            result = CameraMotionResult(number, tuple(tuple(float(v) for v in row) for row in cumulative),
                                        tx, ty, rotation, scale, confidence, int(inliers.sum()),
                                        TrackingState.TRACKING if confidence >= .45 else TrackingState.WEAK,
                                        len(source) - int(inliers.sum()))
        results[number] = result
        previous_gray, keypoints, descriptors = current_gray, current_keypoints, current_descriptors
        if on_progress:
            on_progress(index + 1, len(frame_numbers))
    return results


def smooth_camera_motion(results: dict[int, CameraMotionResult], radius: int = 3) -> dict[int, CameraMotionResult]:
    """Smooth translation/rotation while retaining raw projective transforms."""
    frames = sorted(results)
    if not frames or radius <= 0:
        return results
    tx = np.asarray([results[f].translation_x for f in frames], np.float64)
    ty = np.asarray([results[f].translation_y for f in frames], np.float64)
    kernel = np.ones(radius * 2 + 1) / (radius * 2 + 1)
    tx = np.convolve(np.pad(tx, (radius, radius), mode="edge"), kernel, mode="valid")
    ty = np.convolve(np.pad(ty, (radius, radius), mode="edge"), kernel, mode="valid")
    return {f: CameraMotionResult(r.frame_number, r.transform, float(x), float(y), r.rotation,
                                  r.scale, r.confidence, r.inlier_count, r.state, r.rejected_points)
            for f, r, x, y in zip(frames, (results[f] for f in frames), tx, ty)}
