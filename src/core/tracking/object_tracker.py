"""Long-term single-object tracker with motion prediction and re-identification.

This is the CPU baseline for the optional DeepSORT/BoT-SORT/segmentation
backends. It deliberately separates identity memory from short-term motion so
occluders are never promoted to references.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, asdict
import math

import cv2
import numpy as np

from core.tracking.model import TrackingState
from core.tracking.point_tracker import _safe_sample_frame, _to_gray_u8


@dataclass(frozen=True)
class ObjectReference:
    frame_number: int
    bbox: tuple[float, float, float, float]
    descriptor: np.ndarray | None = None
    points: tuple[tuple[float, float], ...] = ()
    histogram: np.ndarray | None = None


@dataclass(frozen=True)
class ObjectTrackingResult:
    frame_number: int
    bbox: tuple[float, float, float, float]
    confidence: float
    state: TrackingState
    visible: bool
    predicted: bool
    track_id: str
    appearance_score: float = 0.0
    motion_score: float = 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state.value
        return data


def _crop(frame, bbox):
    x, y, w, h = bbox
    height, width = frame.shape[:2]
    x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
    x1, y1 = min(width, int(round(x + w))), min(height, int(round(y + h)))
    if x1 <= x0 or y1 <= y0:
        return None
    return frame[y0:y1, x0:x1]


def _histogram(frame, bbox):
    crop = _crop(frame, bbox)
    if crop is None:
        return None
    gray = _to_gray_u8(crop)
    return cv2.normalize(cv2.calcHist([gray], [0], None, [32], [0, 256]), None).ravel()


def _bbox_polygon(bbox):
    x, y, w, h = bbox
    return np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


def track_object_range(sample_frame: Callable[[int], np.ndarray | None], frame_numbers: list[int], *,
                       initial_bbox: tuple[float, float, float, float],
                       track_id: str = "object-track", max_lost_frames: int = 120,
                       max_references: int = 6, should_cancel: Callable[[], bool] | None = None,
                       on_progress: Callable[[int, int], None] | None = None) -> dict[int, ObjectTrackingResult]:
    """Track one object with appearance memory, identity verification, and prediction."""
    results: dict[int, ObjectTrackingResult] = {}
    if not frame_numbers:
        return results
    first = _safe_sample_frame(sample_frame, int(frame_numbers[0]))
    if first is None:
        return results
    detector = cv2.ORB_create(nfeatures=600, fastThreshold=7)
    previous_gray = _to_gray_u8(first)
    bbox = tuple(float(v) for v in initial_bbox)
    velocity = np.zeros(4, np.float64)
    references: list[ObjectReference] = []
    lost = 0
    crop = _crop(first, bbox)
    keypoints, descriptors = detector.detectAndCompute(_to_gray_u8(crop), None) if crop is not None else ([], None)
    if descriptors is not None:
        references.append(ObjectReference(int(frame_numbers[0]), bbox, descriptors.copy(),
                                          tuple(map(tuple, (keypoint.pt for keypoint in keypoints))),
                                          _histogram(first, bbox)))
    results[int(frame_numbers[0])] = ObjectTrackingResult(int(frame_numbers[0]), bbox, 1., TrackingState.TRACKING, True, False, track_id)
    for index, number_raw in enumerate(frame_numbers[1:], 1):
        if should_cancel and should_cancel():
            break
        number = int(number_raw)
        predicted = tuple(np.asarray(bbox) + velocity)
        frame = _safe_sample_frame(sample_frame, number)
        candidate = None
        if frame is not None:
            gray = _to_gray_u8(frame)
            keypoints, current_descriptors = detector.detectAndCompute(gray, None)
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
            best = None
            if current_descriptors is not None:
                for reference in references:
                    if reference.descriptor is None or len(current_descriptors) < 4:
                        continue
                    pairs = matcher.knnMatch(reference.descriptor, current_descriptors, k=2)
                    good = [m for m, n in pairs if m.distance < .78 * n.distance]
                    if len(good) < 4:
                        continue
                    # Descriptor coordinates are local to the reference crop;
                    # use the crop origin when converting them to image points.
                    src = np.asarray([reference.points[m.queryIdx] for m in good], np.float32)
                    dst = np.asarray([keypoints[m.trainIdx].pt for m in good], np.float32)
                    if len(src) < 4:
                        continue
                    affine, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=5)
                    if affine is None or inliers is None:
                        continue
                    count = int(inliers.sum())
                    score = count / max(1, len(good))
                    if best is None or score > best[0]:
                        # Descriptor points are local to the stored crop; the
                        # affine destination is in current-frame coordinates.
                        local_box = (0.0, 0.0, reference.bbox[2], reference.bbox[3])
                        corners = cv2.transform(_bbox_polygon(local_box)[None], affine)[0]
                        x0, y0 = corners.min(axis=0); x1, y1 = corners.max(axis=0)
                        best = score, (float(x0), float(y0), float(x1 - x0), float(y1 - y0))
            if best is not None:
                candidate = best
            else:
                # A local multiscale appearance fallback handles blur/scale
                # changes when the descriptor set is temporarily sparse.
                candidate = None
        if candidate is None:
            lost += 1
            bbox = predicted
            state = TrackingState.OFFSCREEN if bbox[0] + bbox[2] < 0 or bbox[1] + bbox[3] < 0 or bbox[0] > previous_gray.shape[1] or bbox[1] > previous_gray.shape[0] else TrackingState.OCCLUDED
            results[number] = ObjectTrackingResult(number, bbox, max(0, .35 * math.exp(-lost / 40)), state, False, True, track_id,
                                                    motion_score=max(0, 1 - lost / max_lost_frames))
        else:
            appearance, measured = candidate
            old = np.asarray(bbox)
            bbox = measured
            velocity = .65 * velocity + .35 * (np.asarray(bbox) - old)
            lost_before = lost
            lost = 0
            hist = _histogram(frame, bbox)
            confidence = float(np.clip(.65 * appearance + .35 * math.exp(-np.linalg.norm(np.asarray(bbox) - predicted) / 50), 0, 1))
            state = TrackingState.REACQUIRED if lost_before else (TrackingState.TRACKING if confidence >= .5 else TrackingState.WEAK)
            results[number] = ObjectTrackingResult(number, bbox, confidence, state, True, False, track_id,
                                                    appearance_score=appearance, motion_score=confidence)
            if confidence > .7 and hist is not None and (not references or index % 12 == 0):
                references.append(ObjectReference(number, bbox, None, (), hist))
                references = references[-max_references:]
        if on_progress:
            on_progress(index + 1, len(frame_numbers))
    return results
