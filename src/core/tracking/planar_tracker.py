"""Persistent, perspective-aware planar tracking.

This module intentionally treats visibility as an observation quality, not as
the lifetime of a track.  A session keeps its last geometry and motion model
when the target is outside the image, then verifies re-entry against immutable
reference views before accepting it again.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
import math
import uuid

import cv2
import numpy as np

from core.tracking.model import TrackingState
from core.tracking.point_tracker import _is_valid_frame, _safe_sample_frame, _to_gray_u8

FrameSampler = Callable[[int], np.ndarray | None]
CancelPoll = Callable[[], bool]
ProgressCallback = Callable[[int, int], None]
Point = tuple[float, float]
Polygon = tuple[Point, Point, Point, Point]


@dataclass(frozen=True)
class PlanarTrackingOptions:
    feature_backend: str = "auto"
    max_features: int = 1000
    min_features: int = 10
    min_inliers: int = 6
    flow_fb_error: float = 2.5
    reprojection_error: float = 4.0
    min_inlier_ratio: float = 0.35
    max_lost_frames: int = 120
    reference_interval: int = 10
    max_references: int = 6
    reference_viewpoint_change: float = 0.18
    min_visible_fraction: float = 0.08
    trusted_visible_fraction: float = 0.70
    max_area_ratio: tuple[float, float] = (0.005, 40.0)
    max_corner_jump: float = 2.0
    recovery_radius: float = 0.35
    verify_frames: int = 2
    feature_grid: tuple[int, int] = (6, 6)
    max_reference_disagreement: float = 0.08
    minimum_coverage: float = 0.12


@dataclass(frozen=True)
class TrackingReference:
    frame_number: int
    image_shape: tuple[int, int]
    polygon: Polygon
    quality: float
    points: tuple[Point, ...] = ()
    descriptors: np.ndarray | None = field(default=None, repr=False, compare=False)
    seed_homography: tuple[tuple[float, ...], ...] | None = None
    parent_frame: int | None = None

    def to_dict(self) -> dict:
        return {"frame_number": self.frame_number, "image_shape": self.image_shape,
                "polygon": self.polygon, "quality": self.quality,
                "points": self.points, "seed_homography": self.seed_homography,
                "parent_frame": self.parent_frame}


@dataclass(frozen=True)
class PlanarTrackingResult:
    frame_number: int
    polygon: Polygon | None
    homography: tuple[tuple[float, ...], ...] | None
    confidence: float
    inlier_count: int
    inlier_ratio: float
    reprojection_error: float
    status: TrackingState
    valid: bool
    predicted: bool = False
    recovered: bool = False
    reference_frame: int | None = None
    visible: bool = True
    visible_fraction: float = 1.0
    track_id: str = ""
    time_since_observation: int = 0
    reason: str = ""
    raw_polygon: Polygon | None = None
    drift_score: float = 0.0
    feature_coverage: float = 0.0
    correction_applied: bool = False

    @property
    def predicted_polygon(self) -> Polygon | None:
        return self.polygon if self.predicted else None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["predicted_polygon"] = self.predicted_polygon
        return data


@dataclass
class TrackingSession:
    """State that survives invisible frames and can be persisted by a node."""

    track_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    references: list[TrackingReference] = field(default_factory=list)
    history: dict[int, PlanarTrackingResult] = field(default_factory=dict)
    last_polygon: Polygon | None = None
    last_good_result: PlanarTrackingResult | None = None
    last_good_polygon: Polygon | None = None
    predicted_polygon: Polygon | None = None
    velocity: np.ndarray = field(default_factory=lambda: np.zeros((4, 2), np.float64), repr=False)
    acceleration: np.ndarray = field(default_factory=lambda: np.zeros((4, 2), np.float64), repr=False)
    last_frame: int | None = None
    last_observed_frame: int | None = None
    time_since_observation: int = 0
    state: TrackingState = TrackingState.TRACKING
    last_raw_polygon: Polygon | None = None
    drift_score: float = 0.0


def _detector(options: PlanarTrackingOptions):
    name = options.feature_backend.lower()
    if name == "sift" and hasattr(cv2, "SIFT_create"):
        return cv2.SIFT_create(nfeatures=options.max_features), "sift"
    if name == "akaze":
        return cv2.AKAZE_create(), "akaze"
    # ORB is the default because it is fast, redistributable, and available in
    # the headless OpenCV package used by the editor.
    return cv2.ORB_create(nfeatures=options.max_features, fastThreshold=7), "orb"


def _polygon_array(polygon) -> np.ndarray:
    return np.asarray(polygon, dtype=np.float32)


def _inside_mask(shape, polygon):
    mask = np.zeros(shape[:2], np.uint8)
    # fillPoly clips naturally, which is important for partially off-screen
    # surfaces while preserving the original, unclipped polygon in the model.
    cv2.fillPoly(mask, [np.round(_polygon_array(polygon)).astype(np.int32)], 255)
    return mask


def _features(gray, polygon, detector, options: PlanarTrackingOptions):
    keypoints, descriptors = detector.detectAndCompute(gray, _inside_mask(gray.shape, polygon))
    if not keypoints or descriptors is None:
        return np.empty((0, 2), np.float32), None
    # Spatial binning prevents all new points being taken from one textured
    # corner, which makes projective estimation fragile under foreshortening.
    rows, cols = options.feature_grid
    h, w = gray.shape[:2]
    bins: dict[tuple[int, int], tuple[cv2.KeyPoint, int]] = {}
    for index, keypoint in enumerate(keypoints):
        col = min(cols - 1, max(0, int(keypoint.pt[0] / max(1, w) * cols)))
        row = min(rows - 1, max(0, int(keypoint.pt[1] / max(1, h) * rows)))
        key = (row, col)
        if key not in bins or keypoint.response > bins[key][0].response:
            bins[key] = (keypoint, index)
    selected = sorted(bins.values(), key=lambda item: item[0].response, reverse=True)
    if len(selected) < options.max_features:
        used = {index for _, index in selected}
        selected.extend((kp, i) for i, kp in sorted(enumerate(keypoints), key=lambda p: p[1].response, reverse=True)
                        if i not in used and len(selected) < options.max_features)
    return (np.asarray([kp.pt for kp, _ in selected], np.float32),
            np.asarray([descriptors[i] for _, i in selected]))


def _matcher(kind):
    return cv2.BFMatcher(cv2.NORM_L2 if kind == "sift" else cv2.NORM_HAMMING)


def _estimate(src, dst, options):
    if len(src) < 4:
        return None
    method = getattr(cv2, "USAC_MAGSAC", cv2.RANSAC)
    try:
        h, mask = cv2.findHomography(src, dst, method, options.reprojection_error,
                                     maxIters=5000, confidence=.995)
    except (cv2.error, TypeError):
        h, mask = cv2.findHomography(src, dst, cv2.RANSAC, options.reprojection_error)
    if h is None or mask is None or not np.isfinite(h).all():
        return None
    inliers = mask.ravel().astype(bool)
    if int(inliers.sum()) < options.min_inliers:
        return None
    projected = cv2.perspectiveTransform(src.reshape(-1, 1, 2), h).reshape(-1, 2)
    error = float(np.mean(np.linalg.norm(projected[inliers] - dst[inliers], axis=1)))
    ratio = float(inliers.mean())
    if ratio < options.min_inlier_ratio or error > options.reprojection_error * 2:
        return None
    return h.astype(np.float64), inliers, ratio, error


def _apply(h, polygon):
    transformed = cv2.perspectiveTransform(_polygon_array(polygon).reshape(-1, 1, 2), h).reshape(-1, 2)
    return tuple(tuple(float(v) for v in xy) for xy in transformed)


def _homography_for_polygon(seed, polygon):
    h = cv2.getPerspectiveTransform(_polygon_array(seed).astype(np.float32), _polygon_array(polygon).astype(np.float32))
    return tuple(tuple(float(v) for v in row) for row in h)


def _clip_fraction(polygon, shape):
    points = _polygon_array(polygon)
    area = abs(float(cv2.contourArea(points)))
    if area < 1e-6:
        return 0.0
    h, w = shape[:2]
    rect = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    try:
        intersection, _ = cv2.intersectConvexConvex(points, rect)
        return float(np.clip(abs(float(intersection)) / area, 0.0, 1.0))
    except cv2.error:
        return 0.0


def _valid_geometry(polygon, shape, previous, options):
    points = _polygon_array(polygon)
    if not np.isfinite(points).all() or abs(float(cv2.contourArea(points))) < 4:
        return False
    if not cv2.isContourConvex(points):
        return False
    if previous is not None:
        old_area = abs(float(cv2.contourArea(_polygon_array(previous))))
        area = abs(float(cv2.contourArea(points)))
        if old_area <= 0 or not options.max_area_ratio[0] <= area / old_area <= options.max_area_ratio[1]:
            return False
        # Permit an object to cross the frame in a single valid transform. The
        # limit is relative to the image diagonal, not the old visible ROI.
        if np.max(np.linalg.norm(points - _polygon_array(previous), axis=1)) > max(shape) * options.max_corner_jump:
            return False
    return True


def _confidence(inliers, ratio, error, feature_count, flow_error=0.0, visible_fraction=1.0):
    value = (.28 * min(1.0, inliers / 35.0) + .25 * ratio +
             .20 * math.exp(-error / 6.0) + .12 * min(1.0, feature_count / 80.0) +
             .10 * math.exp(-flow_error / 3.0) + .05 * visible_fraction)
    return float(np.clip(value, 0.0, 1.0))


def _feature_coverage(points, polygon, shape, options):
    """Measure how widely support is distributed over the visible plane."""
    if points is None or len(points) == 0:
        return 0.0
    rows, cols = options.feature_grid
    mask = _inside_mask(shape, polygon)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return 0.0
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    occupied = set()
    for x, y in np.asarray(points):
        if x0 <= x < x1 and y0 <= y < y1:
            occupied.add((min(cols - 1, int((x - x0) / max(1, x1 - x0) * cols)),
                          min(rows - 1, int((y - y0) / max(1, y1 - y0) * rows))))
    return float(len(occupied) / max(1, rows * cols))


def _descriptor_candidates(gray, polygon, references, detector, kind, options, predicted,
                           search_region=None):
    """Return the strongest geometrically verified reference match."""
    h, w = gray.shape[:2]
    whole = ((0., 0.), (float(w), 0.), (float(w), float(h)), (0., float(h)))
    points, descriptors = _features(gray, search_region or whole, detector, options)
    if descriptors is None:
        return None
    matcher = _matcher(kind)
    best = None
    for reference in references:
        if reference.descriptors is None or len(reference.descriptors) < options.min_features:
            continue
        forward = matcher.knnMatch(reference.descriptors, descriptors, k=2)
        reverse = matcher.knnMatch(descriptors, reference.descriptors, k=2)
        ratio = .72 if kind == "sift" else .78
        forward_good = {m.trainIdx: m for m, n in forward if m.distance < ratio * n.distance}
        reverse_good = {m.queryIdx: m for m, n in reverse if m.distance < ratio * n.distance}
        matches = [m for m in forward_good.values() if reverse_good.get(m.trainIdx) is not None and
                   reverse_good[m.trainIdx].trainIdx == m.queryIdx]
        if len(matches) < options.min_features:
            continue
        src = np.asarray([reference.points[m.queryIdx] for m in matches], np.float32)
        dst = np.asarray([points[m.trainIdx] for m in matches], np.float32)
        estimated = _estimate(src, dst, options)
        if estimated is None:
            continue
        h_match, inlier_mask, inlier_ratio, error = estimated
        polygon = _apply(h_match, reference.polygon)
        fraction = _clip_fraction(polygon, gray.shape)
        # When the predicted polygon is visible, reject a descriptor match that
        # lands on a different object despite having a plausible homography.
        if predicted is not None and _clip_fraction(predicted, gray.shape) > options.min_visible_fraction:
            distance = np.mean(np.linalg.norm(_polygon_array(polygon) - _polygon_array(predicted), axis=1))
            if distance > max(w, h) * (options.recovery_radius + .15):
                continue
        score = inlier_ratio * math.exp(-error / 8.0) * (0.5 + .5 * fraction)
        if best is None or score > best[0]:
            best = (score, h_match, inlier_mask, inlier_ratio, error,
                    dst[inlier_mask], reference, polygon, fraction)
    return best


def _reentry_search_region(predicted, shape, missing_frames):
    """Return a staged border/local ROI without clipping the tracked polygon."""
    height, width = shape[:2]
    points = _polygon_array(predicted)
    center = points.mean(axis=0)
    # A target predicted beyond a border is searched from its predicted entry
    # border, not from its impossible off-image center.
    center[0] = np.clip(center[0], 0, width)
    center[1] = np.clip(center[1], 0, height)
    radius = max(width, height) * min(1.0, .18 + .045 * missing_frames)
    if radius >= max(width, height):
        return None
    return ((float(center[0] - radius), float(center[1] - radius)),
            (float(center[0] + radius), float(center[1] - radius)),
            (float(center[0] + radius), float(center[1] + radius)),
            (float(center[0] - radius), float(center[1] + radius)))


def _state_for_prediction(polygon, shape, lost, options):
    fraction = _clip_fraction(polygon, shape)
    if fraction <= 1e-5:
        return (TrackingState.SEARCHING_FOR_REENTRY if lost > options.max_lost_frames
                else TrackingState.OFFSCREEN), fraction
    if fraction <= .20:
        return TrackingState.MOSTLY_OFFSCREEN, fraction
    if fraction <= .70:
        return TrackingState.PARTIALLY_OFFSCREEN, fraction
    if fraction < options.trusted_visible_fraction:
        return TrackingState.PREDICTING, fraction
    if lost:
        return TrackingState.OCCLUDED, fraction
    return TrackingState.PARTIALLY_VISIBLE, fraction


def _make_result(session, frame, polygon, status, *, confidence=0.0, inliers=0,
                 ratio=0.0, error=0.0, observed=False, recovered=False,
                 reference_frame=None, shape=None, reason="", raw_polygon=None,
                 drift_score=0.0, feature_coverage=0.0, correction_applied=False):
    fraction = _clip_fraction(polygon, shape) if polygon is not None and shape is not None else 0.0
    homography = _homography_for_polygon(session.references[0].polygon, polygon) if polygon is not None and session.references else None
    output_polygon = None
    if polygon is not None and shape is not None:
        width = max(1, shape[1])
        height = max(1, shape[0])
        output_polygon = tuple((float(x) / width, float(y) / height) for x, y in polygon)
    result = PlanarTrackingResult(
        frame, output_polygon, homography, confidence, inliers, ratio, error, status,
        observed, predicted=not observed, recovered=recovered,
        reference_frame=reference_frame, visible=fraction > 1e-5,
        visible_fraction=fraction, track_id=session.track_id,
        time_since_observation=session.time_since_observation, reason=reason,
        raw_polygon=(tuple((float(x) / max(1, shape[1]), float(y) / max(1, shape[0])) for x, y in raw_polygon)
                     if raw_polygon is not None and shape is not None else None),
        drift_score=drift_score, feature_coverage=feature_coverage,
        correction_applied=correction_applied)
    session.history[frame] = result
    session.state = status
    session.last_frame = frame
    if observed:
        session.last_good_result = result
        session.last_good_polygon = polygon
    return result


def track_planar_homography_range(
    sample_frame: FrameSampler, frame_numbers: list[int], *,
    initial_corners: tuple[Point, Point, Point, Point],
    should_cancel: CancelPoll | None = None,
    on_progress: ProgressCallback | None = None,
    options: PlanarTrackingOptions | None = None,
    session: TrackingSession | None = None,
) -> dict[int, PlanarTrackingResult]:
    """Track a plane while retaining identity through off-screen intervals."""
    options = options or PlanarTrackingOptions()
    session = session or TrackingSession()
    if not frame_numbers:
        return {}
    first_number = int(frame_numbers[0])
    first = _safe_sample_frame(sample_frame, first_number)
    if first is None or not _is_valid_frame(first):
        return {}
    first_gray = _to_gray_u8(first)
    detector, kind = _detector(options)
    h_img, w_img = first_gray.shape[:2]
    seed = tuple((float(x) * w_img, float(y) * h_img) for x, y in initial_corners)
    points, descriptors = _features(first_gray, seed, detector, options)
    if len(points) < options.min_features:
        return {int(n): _make_result(session, int(n), seed, TrackingState.LOST,
                                     shape=first_gray.shape, reason="insufficient_features") for n in frame_numbers}
    reference = TrackingReference(first_number, first_gray.shape, seed, 1.0,
                                  tuple(map(tuple, points)), descriptors.copy(),
                                  _homography_for_polygon(seed, seed))
    session.references = [reference]
    session.last_polygon = seed
    session.last_good_polygon = seed
    session.predicted_polygon = seed
    session.last_frame = first_number
    session.last_observed_frame = first_number
    session.time_since_observation = 0
    _make_result(session, first_number, seed, TrackingState.TRACKING, confidence=1.0,
                 inliers=len(points), ratio=1.0, observed=True, shape=first_gray.shape)
    active_points, active_gray = points, first_gray
    last_quality = 1.0

    for index, number_raw in enumerate(frame_numbers[1:], 1):
        if should_cancel and should_cancel():
            break
        number = int(number_raw)
        previous_frame = session.last_frame if session.last_frame is not None else number - 1
        dt = max(1, abs(number - previous_frame))
        # Continue from the latest prediction during an invisible run; the
        # trusted observation remains separately available as last_good_polygon.
        old_polygon = session.predicted_polygon or session.last_polygon or seed
        predicted_points = (_polygon_array(old_polygon) + session.velocity * dt +
                            .5 * session.acceleration * (dt ** 2))
        predicted_polygon = tuple(map(tuple, predicted_points))
        session.predicted_polygon = predicted_polygon
        frame = _safe_sample_frame(sample_frame, number)
        candidate = None
        current_gray = None
        candidate_polygon = None
        raw_candidate_polygon = None
        reference_disagreement = 0.0
        correction_applied = False
        if frame is not None and _is_valid_frame(frame):
            current_gray = _to_gray_u8(frame)
            # Points outside the current image are inactive, not bad matches.
            # Never send them into LK/RANSAC while the target is crossing a
            # border or is being predicted off-screen.
            height, width = current_gray.shape[:2]
            visible_points = ((active_points[:, 0] >= 0) & (active_points[:, 0] < width) &
                              (active_points[:, 1] >= 0) & (active_points[:, 1] < height))
            flow_points = active_points[visible_points]
            if len(flow_points) >= 4 and current_gray.shape == active_gray.shape:
                nxt, status, _ = cv2.calcOpticalFlowPyrLK(
                    active_gray, current_gray, flow_points.reshape(-1, 1, 2), None,
                    winSize=(21, 21), maxLevel=4,
                    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, .01))
                if nxt is not None and status is not None:
                    back, back_status, _ = cv2.calcOpticalFlowPyrLK(current_gray, active_gray, nxt, None,
                                                                     winSize=(21, 21), maxLevel=4)
                    good = status.ravel().astype(bool) & back_status.ravel().astype(bool)
                    backward_error = 99.0
                    if back is not None:
                        backward_error = np.linalg.norm(flow_points - back.reshape(-1, 2), axis=1)
                        good &= backward_error <= options.flow_fb_error
                    new_points = nxt.reshape(-1, 2)
                    estimate = _estimate(flow_points[good], new_points[good], options)
                    if estimate is not None:
                        h_flow, mask, ratio, error = estimate
                        inlier_points = new_points[good][mask]
                        candidate = (h_flow, ratio, error, int(mask.sum()), inlier_points,
                                     current_gray, None, backward_error[good][mask].mean() if good.any() else 0.)
                        raw_candidate_polygon = _apply(h_flow, old_polygon)
            # Periodic reference comparison corrects accumulated flow drift;
            # weak/lost frames always use the bank and not a stale template.
            lost = session.time_since_observation > 0
            if candidate is None or lost or index % max(1, options.reference_interval) == 0:
                reference_candidate = _descriptor_candidates(current_gray, predicted_polygon,
                                                              session.references, detector, kind,
                                                              options, predicted_polygon,
                                                              _reentry_search_region(
                                                                  predicted_polygon, current_gray.shape,
                                                                  session.time_since_observation) if lost else None)
                flow_candidate = candidate
                flow_polygon = raw_candidate_polygon
                if reference_candidate is not None:
                    _, h_ref, mask, ratio, error, inlier_points, ref, polygon, fraction = reference_candidate
                    ref_quality = float(ratio * math.exp(-error / 8.0))
                    flow_quality = (float(flow_candidate[1] * math.exp(-flow_candidate[2] / 8.0))
                                    if flow_candidate is not None else -1.0)
                    if flow_polygon is not None:
                        reference_disagreement = float(np.mean(
                            np.linalg.norm(_polygon_array(flow_polygon) - _polygon_array(polygon), axis=1)
                        ) / max(current_gray.shape))
                    # Absolute reference evidence wins when it is comparable
                    # or when incremental flow has begun to disagree visibly.
                    if flow_candidate is None or ref_quality >= flow_quality * .90 or reference_disagreement > options.max_reference_disagreement:
                        candidate = (h_ref, ratio, error, int(mask.sum()), inlier_points,
                                     current_gray, ref, 0.)
                        candidate_polygon = polygon
                        correction_applied = flow_candidate is not None and reference_disagreement > .02
                    else:
                        candidate_polygon = None

        if candidate is not None:
            h_update, ratio, error, inliers, new_points, current_gray, ref, flow_error = candidate
            if ref is None:
                proposed_polygon = _apply(h_update, old_polygon)
            else:
                proposed_polygon = candidate_polygon or _apply(h_update, ref.polygon)
            # A descriptor-verified re-entry may be far from the extrapolated
            # polygon after a long off-screen interval.  Its reference geometry
            # is the temporal gate in that case; comparing it to the stale
            # prediction would reject the very recovery we need.
            valid_geometry = _valid_geometry(proposed_polygon, current_gray.shape,
                                             None if ref is not None else old_polygon, options)
            candidate_fraction = _clip_fraction(proposed_polygon, current_gray.shape)
            # A sliver with too little support is not a trustworthy measured
            # surface. Preserve the last-good transform and let prediction
            # carry it until a meaningful visible portion returns.
            if candidate_fraction < options.min_visible_fraction:
                valid_geometry = False
            # A match can be correct while the visible polygon has become very
            # thin. Area collapse alone is not rejection when inliers support it.
            if valid_geometry:
                new_array = _polygon_array(proposed_polygon)
                old_array = _polygon_array(old_polygon)
                measured_velocity = (new_array - old_array) / dt
                session.acceleration = .5 * session.acceleration + .5 * (measured_velocity - session.velocity) / dt
                session.velocity = .65 * session.velocity + .35 * measured_velocity
                session.last_polygon = proposed_polygon
                session.predicted_polygon = proposed_polygon
                session.last_observed_frame = number
                session.time_since_observation = 0
                active_points = new_points
                # Refresh from the currently visible plane; do not refresh from
                # a predicted/off-screen result or from a recovery candidate.
                active_gray = current_gray
                fraction = _clip_fraction(proposed_polygon, current_gray.shape)
                coverage = _feature_coverage(new_points, proposed_polygon, current_gray.shape, options)
                confidence = _confidence(inliers, ratio, error, len(new_points), flow_error, fraction)
                if coverage < options.minimum_coverage:
                    confidence *= max(.25, coverage / max(options.minimum_coverage, 1e-6))
                was_hidden = (session.state in (TrackingState.OFFSCREEN, TrackingState.PREDICTING,
                                                TrackingState.SEARCHING, TrackingState.SEARCHING_FOR_REENTRY,
                                                TrackingState.OCCLUDED, TrackingState.MOSTLY_OFFSCREEN) or
                              _clip_fraction(old_polygon, current_gray.shape) <= options.min_visible_fraction)
                status = TrackingState.REACQUIRED if was_hidden else (TrackingState.CORRECTING if correction_applied else (
                    TrackingState.PARTIALLY_VISIBLE if fraction < .999 else
                    TrackingState.WEAK if confidence < .55 else TrackingState.TRACKING))
                if correction_applied:
                    session.last_raw_polygon = raw_candidate_polygon
                session.drift_score = reference_disagreement
                result = _make_result(session, number, proposed_polygon, status,
                                      confidence=confidence, inliers=inliers, ratio=ratio,
                                      error=error, observed=True, recovered=was_hidden,
                                      reference_frame=(ref.frame_number if ref else None),
                                      shape=current_gray.shape, raw_polygon=raw_candidate_polygon,
                                      drift_score=reference_disagreement, feature_coverage=coverage,
                                      correction_applied=correction_applied)
                last_quality = confidence
                if (not was_hidden and index % max(1, options.reference_interval) == 0 and
                        status == TrackingState.TRACKING and confidence > .65 and
                        fraction >= options.trusted_visible_fraction):
                    p, d = _features(current_gray, proposed_polygon, detector, options)
                    if len(p) >= options.min_features and d is not None:
                        session.references.append(TrackingReference(
                            number, current_gray.shape, proposed_polygon, confidence,
                            tuple(map(tuple, p)), d.copy(),
                            _homography_for_polygon(seed, proposed_polygon),
                            ref.frame_number if ref else (session.references[-1].frame_number if session.references else None)))
                        session.references = sorted(session.references, key=lambda item: item.quality, reverse=True)[:options.max_references]
                if on_progress: on_progress(index + 1, len(frame_numbers))
                continue

        # No verified observation. Preserve and advance the mathematical track.
        session.time_since_observation += dt
        state, fraction = _state_for_prediction(predicted_polygon,
                                                 current_gray.shape if current_gray is not None else first_gray.shape,
                                                 session.time_since_observation, options)
        if current_gray is not None and fraction > .70:
            state = (TrackingState.OCCLUDED if session.time_since_observation <= options.max_lost_frames
                     else TrackingState.SEARCHING)
        elif session.time_since_observation > options.max_lost_frames and fraction <= .20:
            state = TrackingState.SEARCHING_FOR_REENTRY
        # Keep the measured state immutable. Only the prediction advances;
        # last_polygon/last_good_polygon remain the last trusted observation.
        _make_result(session, number, predicted_polygon, state,
                     confidence=max(0.0, last_quality * math.exp(-session.time_since_observation / 45.0)),
                     observed=False, shape=current_gray.shape if current_gray is not None else first_gray.shape,
                     reason="offscreen_prediction" if state in (TrackingState.OFFSCREEN, TrackingState.PREDICTING) else "no_verified_observation")
        if on_progress: on_progress(index + 1, len(frame_numbers))
    return session.history


def repair_planar_gaps(results: dict[int, PlanarTrackingResult]) -> dict[int, PlanarTrackingResult]:
    """Repair short prediction gaps when measured results bracket both sides."""
    frames = sorted(results)
    for index, frame in enumerate(frames):
        item = results[frame]
        if not item.predicted or index == 0 or index == len(frames) - 1:
            continue
        before = results[frames[index - 1]]
        after = results[frames[index + 1]]
        if before.polygon is None or after.polygon is None or not before.visible or not after.visible:
            continue
        t = (frame - frames[index - 1]) / max(1, frames[index + 1] - frames[index - 1])
        polygon = tuple(tuple(float(v) for v in a + (b - a) * t) for a, b in zip(_polygon_array(before.polygon), _polygon_array(after.polygon)))
        results[frame] = PlanarTrackingResult(frame, polygon, item.homography, max(item.confidence, .35),
                                               item.inlier_count, item.inlier_ratio, item.reprojection_error,
                                               TrackingState.RECOVERING, False, predicted=True, recovered=True,
                                               reference_frame=item.reference_frame, visible=True,
                                               visible_fraction=item.visible_fraction, track_id=item.track_id,
                                               time_since_observation=item.time_since_observation, reason="gap_repaired")
    return results


def planar_results_to_corners(results: dict[int, PlanarTrackingResult]) -> dict[str, dict[int, tuple[float, float]]]:
    names = ("top_left", "top_right", "bottom_right", "bottom_left")
    output = {name: {} for name in names}
    for frame, result in results.items():
        # Predicted/off-screen geometry is deliberately exported too. Downstream
        # compositors clip it; they must not receive a fake frame-edge clamp.
        if result.polygon:
            for name, point in zip(names, result.polygon):
                output[name][frame] = point
    return output
