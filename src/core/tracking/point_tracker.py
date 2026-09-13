"""Fixed-template tracking with measured gaps and bounded motion-guided recovery.

Matching processes only local search windows; larger searches are split into
cancellable tiles. Point and planar workers share the same tracking engine.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from core.tracking.model import TrackingOptions, TrackingSample, TrackingState

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Slightly higher floor for more reliable matches.
_MATCH_CONFIDENCE_FLOOR: float = 0.45

_MIN_HALF_EXTENT_PX: int = 4

_MIN_TEMPLATE_STDDEV: float = 1.0


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

FrameSampler = Callable[[int], np.ndarray | None]
CancelPoll = Callable[[], bool]
ProgressCallback = Callable[[int, int], None]

NormalizedPoint = tuple[float, float]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def track_point_range(
    sample_frame: FrameSampler, frame_numbers: list[int], *,
    initial_center: NormalizedPoint, region_size: NormalizedPoint,
    search_radius: float, should_cancel: CancelPoll | None = None,
    on_progress: ProgressCallback | None = None, options: TrackingOptions | None = None,
) -> dict[int, TrackingSample]:
    """Return measured and explicitly missing samples in processing order."""
    return {sample.frame_number:sample for sample in _track_point_samples(
        sample_frame,frame_numbers,initial_center=initial_center,region_size=region_size,
        search_radius=search_radius,should_cancel=should_cancel,on_progress=on_progress,
        options=options)}


def _track_point_samples(
    sample_frame: FrameSampler,
    frame_numbers: list[int],
    *, initial_center: NormalizedPoint, region_size: NormalizedPoint,
    search_radius: float, should_cancel: CancelPoll | None = None,
    on_progress: ProgressCallback | None = None,
    options: TrackingOptions | None = None,
):
    """Track fixed appearance with explicit loss, bounded recovery, and raw gaps."""
    options = options or TrackingOptions()
    log = logging.getLogger(__name__)
    if not frame_numbers or (should_cancel and should_cancel()):
        return
    seed_number = int(frame_numbers[0])
    seed = _safe_sample_frame(sample_frame,seed_number)
    valid_seed = seed is not None and _is_valid_frame(seed)
    width,height = (seed.shape[1],seed.shape[0]) if valid_seed else (0,0)
    center = tuple(float(v) for v in initial_center)
    valid_center = all(np.isfinite(v) and 0 <= v <= 1 for v in center)
    template = (_extract_patch(seed,center,region_size,width,height)
                if valid_seed and valid_center and all(np.isfinite(v) and v > 0 for v in region_size) else None)
    if template is not None:
        template = _preprocess_template(template)
    if template is None or _template_is_degenerate(template):
        for index, number in enumerate(frame_numbers):
            if should_cancel and should_cancel():
                break
            yield TrackingSample(number,None,None,0,False,state=TrackingState.LOST,reason="invalid_template")
            if on_progress:
                on_progress(index+1,len(frame_numbers))
        log.debug("Tracker rejected seed at frame %s: invalid/low-variance template",seed_number)
        return
    yield TrackingSample(seed_number,*center,1.0,True)
    if on_progress:
        on_progress(1,len(frame_numbers))
    last_frame,last_position = seed_number,np.array(center)
    velocity = np.zeros(2)
    lost = 0
    confirmations = 0
    candidate_previous = None
    state = TrackingState.TRACKING
    previous_radius = None
    normal_radius = max(0.001,abs(float(search_radius)))
    for index, number in enumerate(frame_numbers[1:],1):
        if should_cancel and should_cancel():
            break
        number = int(number)
        elapsed = number-last_frame
        predicted = last_position+velocity*elapsed
        confidence = 0.0
        candidate = None
        reason = "no_match"
        if lost <= options.max_lost_frames:
            radius = normal_radius * min(options.max_search_multiplier,2 ** min(lost//2,4))
            if lost and radius != previous_radius:
                log.debug("Reacquisition radius increased to %.0f px",radius*width)
            previous_radius = radius
            if lost and state != TrackingState.REACQUIRING:
                log.debug("Entering reacquisition at frame %s",number)
            state = TrackingState.REACQUIRING if lost else TrackingState.TRACKING
            frame = _safe_sample_frame(sample_frame,number)
            if should_cancel and should_cancel():
                break
            if frame is not None and _is_valid_frame(frame) and frame.shape[:2] == (height,width):
                candidate,confidence = _match_candidate(frame,template,predicted,radius,
                    options.ambiguity_margin,should_cancel)
            else:
                reason = "unavailable_frame"
            if should_cancel and should_cancel():
                break
            if not lost and not all(0 <= v <= 1 for v in predicted):
                candidate,reason = None,"out_of_frame"
            threshold = options.reacquire_threshold if lost else options.track_threshold
            if candidate is not None:
                deviation = float(np.linalg.norm(np.array(candidate)-predicted))
                # Expanding the search is not permission to accept an impossible jump.
                if deviation > options.max_jump:
                    log.debug("Candidate rejected at frame %s: excessive position jump",number)
                    candidate,reason = None,"position_jump"
                elif confidence < threshold:
                    candidate,reason = None,"low_confidence"
                elif lost:
                    if candidate_previous is not None:
                        old_number,old_position = candidate_previous
                        consistent = np.linalg.norm(np.array(candidate)-old_position-velocity*(number-old_number)) <= options.max_jump/2
                        confirmations = confirmations+1 if consistent else 1
                    else:
                        confirmations = 1
                    candidate_previous = number,np.array(candidate)
                    if confirmations < options.confirmation_frames:
                        candidate,reason = None,"confirming"
            if candidate is None and reason != "confirming":
                confirmations,candidate_previous = 0,None
        else:
            reason = "timeout"
        if candidate is not None:
            new_position = np.array(candidate)
            if elapsed:
                velocity = (new_position-last_position)/elapsed
            reacquired = lost > 0
            if reacquired:
                log.debug("Tracker reacquired at frame %s, confidence=%.3f",number,confidence)
            last_position,last_frame = new_position,number
            lost,confirmations,candidate_previous = 0,0,None
            state = TrackingState.TRACKING
            yield TrackingSample(number,*candidate,confidence,True,reacquired=reacquired)
        else:
            lost += abs(number-int(frame_numbers[index-1]))
            if lost == abs(number-int(frame_numbers[index-1])):
                log.debug("Tracker lost at frame %s, confidence=%.3f",number,confidence)
                state = TrackingState.LOST
            elif lost > options.max_lost_frames:
                if state != TrackingState.LOST:
                    log.debug("Reacquisition expired at frame %s",number)
                state = TrackingState.LOST
            yield TrackingSample(number,None,None,confidence,False,
                state=state,predicted_x=float(predicted[0]),predicted_y=float(predicted[1]),reason=reason)
        if on_progress:
            on_progress(index+1,len(frame_numbers))
    return


def _match_candidate(frame, template, predicted, radius, ambiguity_margin, should_cancel):
    """Bounded, tiled correlation; check cancellation between OpenCV calls."""
    height,width = frame.shape[:2]
    th,tw = template.shape
    cx,cy = predicted[0]*width,predicted[1]*height
    x0,x1 = max(0,int(cx-radius*width-tw/2)),min(width,int(cx+radius*width+tw/2)+1)
    y0,y1 = max(0,int(cy-radius*height-th/2)),min(height,int(cy+radius*height+th/2)+1)
    if x1-x0 < tw or y1-y0 < th:
        return None,0.0
    # Convert only the ROI, never the full frame; retain the fixed template.
    window = cv2.GaussianBlur(_to_gray_u8(frame[y0:y1,x0:x1]),(3,3),0)
    peaks = []
    for ty in range(0,window.shape[0]-th+1,128):
        for tx in range(0,window.shape[1]-tw+1,128):
            if should_cancel and should_cancel():
                return None,0.0
            tile = window[ty:ty+128+th-1,tx:tx+128+tw-1]
            correlation = cv2.matchTemplate(tile,template,cv2.TM_CCOEFF_NORMED)
            np.nan_to_num(correlation,copy=False,nan=-1,posinf=-1,neginf=-1)
            # Keep distinct secondary peaks to reject ambiguous repeated textures.
            for _ in range(2):
                _,score,_,loc = cv2.minMaxLoc(correlation)
                rx,ry = _refine_peak_subpixel(correlation,loc)
                peaks.append((score,tx+rx,ty+ry))
                px,py = loc
                correlation[max(0,py-th//2):py+th//2+1,max(0,px-tw//2):px+tw//2+1] = -1
    peaks.sort(reverse=True)
    if not peaks:
        return None,0.0
    score,x,y = peaks[0]
    for second,sx,sy in peaks[1:]:
        if abs(x-sx) > tw/2 or abs(y-sy) > th/2:
            if score-second < ambiguity_margin:
                return None,float(score)
            break
    return ((x0+x+tw/2)/width,(y0+y+th/2)/height),float(score)


def track_planar_range(
    sample_frame: FrameSampler, frame_numbers: list[int], *,
    initial_corners: tuple[NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint],
    region_size: NormalizedPoint, search_radius: float,
    should_cancel: CancelPoll | None = None, on_progress: ProgressCallback | None = None,
) -> tuple[dict, dict, dict, dict]:
    """Advance the four existing point trackers together, sampling each image once.

    Only the current source frame is retained, independent of job duration.
    The planar API keeps its historical curve-pair format.
    """
    cached_number = None
    cached_frame = None
    def shared_sample(number):
        nonlocal cached_number,cached_frame
        if number != cached_number:
            cached_frame = _safe_sample_frame(sample_frame,number)
            cached_number = number
        return cached_frame
    trackers = [_track_point_samples(shared_sample,frame_numbers,initial_center=corner,
                region_size=region_size,search_radius=search_radius,should_cancel=should_cancel)
                for corner in initial_corners]
    results = ({},{},{},{})
    for index,_ in enumerate(frame_numbers):
        if should_cancel and should_cancel():
            break
        for tracker,result in zip(trackers,results):
            sample = next(tracker,None)
            if sample is not None and sample.valid:
                result[sample.frame_number] = sample.x,sample.y
        if on_progress:
            on_progress((index+1)*4,len(frame_numbers)*4)
    return results


# ---------------------------------------------------------------------------
# Frame handling
# ---------------------------------------------------------------------------


def _safe_sample_frame(
    sample_frame: FrameSampler,
    frame_number: int,
) -> np.ndarray | None:
    """Call the frame sampler defensively.

    The tracker should never crash because a decoder/cache returns an
    unexpected value. Sampling failures are treated as unavailable frames.

    Importantly, this does not catch BaseException so KeyboardInterrupt,
    SystemExit, etc. still behave normally.
    """

    try:
        frame = sample_frame(frame_number)
    except Exception:
        return None

    if frame is None:
        return None

    if not isinstance(frame, np.ndarray):
        return None

    return frame


def _is_valid_frame(frame: np.ndarray) -> bool:
    """Return whether a numpy frame has a usable image layout."""

    if not isinstance(frame, np.ndarray):
        return False

    if frame.ndim == 2:
        return frame.shape[0] > 0 and frame.shape[1] > 0

    if frame.ndim == 3:
        return (
            frame.shape[0] > 0
            and frame.shape[1] > 0
            and frame.shape[2] in (1, 3, 4)
        )

    return False


# ---------------------------------------------------------------------------
# Coordinate handling
# ---------------------------------------------------------------------------


def _clamp_point(
    point: NormalizedPoint,
) -> NormalizedPoint:
    """Clamp a normalized point to the valid image range."""

    return (
        float(np.clip(point[0], 0.0, 1.0)),
        float(np.clip(point[1], 0.0, 1.0)),
    )


# ---------------------------------------------------------------------------
# Image conversion
# ---------------------------------------------------------------------------


def _to_gray_u8(
    frame: np.ndarray,
) -> np.ndarray:
    """Convert an RGB/RGBA/grayscale frame to contiguous grayscale uint8.

    Supported representations:

        float 0..1
        float 0..255
        integer 0..255
        grayscale arrays
        RGB arrays
        RGBA arrays

    Aphelion frames are treated as RGB rather than OpenCV's native BGR.
    """

    if frame.ndim == 2:
        return _gray_array_to_u8(frame)

    if frame.ndim != 3:
        raise ValueError(
            f"Unsupported frame dimensions: {frame.shape}"
        )

    channels = frame.shape[2]

    if channels == 1:
        return _gray_array_to_u8(frame[..., 0])

    if channels not in (3, 4):
        raise ValueError(
            f"Unsupported frame channel count: {channels}"
        )

    rgb = frame[..., :3]

    # ---------------------------------------------------------------
    # Floating-point RGB
    # ---------------------------------------------------------------

    if np.issubdtype(rgb.dtype, np.floating):
        working = np.asarray(
            rgb,
            dtype=np.float32,
        )

        if working.size == 0:
            return np.empty(
                working.shape[:2],
                dtype=np.uint8,
            )

        finite_values = working[np.isfinite(working)]

        if finite_values.size == 0:
            return np.zeros(
                working.shape[:2],
                dtype=np.uint8,
            )

        max_value = float(np.max(finite_values))

        if max_value <= 1.0 + 1e-6:
            working = np.clip(
                working,
                0.0,
                1.0,
            )

            working *= 255.0

        else:
            working = np.clip(
                working,
                0.0,
                255.0,
            )

        working = np.rint(working).astype(
            np.uint8,
        )

        gray = cv2.cvtColor(
            working,
            cv2.COLOR_RGB2GRAY,
        )

        return np.ascontiguousarray(gray)

    # ---------------------------------------------------------------
    # Integer RGB
    # ---------------------------------------------------------------

    working_u8 = np.asarray(rgb)

    if working_u8.dtype != np.uint8:
        working_u8 = np.clip(
            working_u8,
            0,
            255,
        ).astype(np.uint8)

    gray = cv2.cvtColor(
        working_u8,
        cv2.COLOR_RGB2GRAY,
    )

    return np.ascontiguousarray(gray)


def _gray_array_to_u8(
    gray: np.ndarray,
) -> np.ndarray:
    """Convert a grayscale array to contiguous uint8."""

    if np.issubdtype(gray.dtype, np.floating):
        working = np.asarray(
            gray,
            dtype=np.float32,
        )

        if working.size == 0:
            return np.empty(
                working.shape,
                dtype=np.uint8,
            )

        finite_values = working[np.isfinite(working)]

        if finite_values.size == 0:
            return np.zeros(
                working.shape,
                dtype=np.uint8,
            )

        max_value = float(np.max(finite_values))

        if max_value <= 1.0 + 1e-6:
            working = np.clip(
                working,
                0.0,
                1.0,
            )

            working *= 255.0

        else:
            working = np.clip(
                working,
                0.0,
                255.0,
            )

        return np.ascontiguousarray(
            np.rint(working).astype(np.uint8)
        )

    return np.ascontiguousarray(
        np.clip(
            gray,
            0,
            255,
        ).astype(np.uint8)
    )


# ---------------------------------------------------------------------------
# Template extraction
# ---------------------------------------------------------------------------


def _extract_patch(
    frame: np.ndarray,
    center: NormalizedPoint,
    size: NormalizedPoint,
    width: int,
    height: int,
) -> np.ndarray | None:
    """Extract a grayscale template centered at a normalized position."""

    if not _is_valid_frame(frame):
        return None

    if frame.shape[1] != width:
        return None

    if frame.shape[0] != height:
        return None

    half_width = max(
        _MIN_HALF_EXTENT_PX,
        int(round(abs(size[0]) * width * 0.5)),
    )

    half_height = max(
        _MIN_HALF_EXTENT_PX,
        int(round(abs(size[1]) * height * 0.5)),
    )

    cx = int(round(center[0] * width))
    cy = int(round(center[1] * height))

    x0 = cx - half_width
    x1 = cx + half_width

    y0 = cy - half_height
    y1 = cy + half_height

    if x0 < 0:
        return None

    if y0 < 0:
        return None

    if x1 > width:
        return None

    if y1 > height:
        return None

    if x1 <= x0:
        return None

    if y1 <= y0:
        return None

    patch = frame[
        y0:y1,
        x0:x1,
    ]

    if patch.size == 0:
        return None

    gray = _to_gray_u8(patch)

    if gray.shape[0] < 2:
        return None

    if gray.shape[1] < 2:
        return None

    return gray


def _template_is_degenerate(
    template: np.ndarray,
) -> bool:
    """Return whether a template lacks enough image variance."""

    if template.size == 0:
        return True

    standard_deviation = float(
        np.std(template)
    )

    return (
        not np.isfinite(standard_deviation)
        or standard_deviation < _MIN_TEMPLATE_STDDEV
    )


def _preprocess_template(
    template_u8: np.ndarray,
) -> np.ndarray:
    """Apply light denoising to the template to improve matching stability."""

    if template_u8.size == 0:
        return template_u8

    # Small Gaussian blur to suppress pixel noise while preserving structure.
    # Kernel size is kept minimal to avoid oversmoothing small templates.
    try:
        return cv2.GaussianBlur(
            template_u8,
            (3, 3),
            0.0,
        )
    except cv2.error:
        # Fall back to original if OpenCV fails for any reason.
        return template_u8


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _refine_peak_subpixel(
    correlation: np.ndarray,
    max_location: tuple[int, int],
) -> tuple[float, float]:
    """Refine the correlation peak to subpixel precision via quadratic fitting.

    Uses a simple 1D parabola fit in X and Y around the discrete maximum.
    """

    x, y = max_location
    h, w = correlation.shape[:2]

    # If we don't have neighbors on both sides, just return the integer peak.
    if x <= 0 or x >= w - 1 or y <= 0 or y >= h - 1:
        return float(x), float(y)

    # Extract 3-point neighborhoods.
    center = float(correlation[y, x])

    left = float(correlation[y, x - 1])
    right = float(correlation[y, x + 1])

    top = float(correlation[y - 1, x])
    bottom = float(correlation[y + 1, x])

    # Quadratic offset: 0.5 * (v_-1 - v_+1) / (v_-1 - 2*v0 + v_+1)
    def _parabolic_offset(vm1: float, v0: float, vp1: float) -> float:
        denom = (vm1 - 2.0 * v0 + vp1)
        if abs(denom) < 1e-12:
            return 0.0
        offset = 0.5 * (vm1 - vp1) / denom
        # Clamp to a reasonable range to avoid wild jumps.
        return float(np.clip(offset, -1.0, 1.0))

    offset_x = _parabolic_offset(left, center, right)
    offset_y = _parabolic_offset(top, center, bottom)

    return float(x) + offset_x, float(y) + offset_y


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "track_point_range",
    "track_planar_range",
]
