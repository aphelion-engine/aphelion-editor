"""Fixed-template 2D point tracking over a frame range.

Deliberately simple (no optical flow, no online template adaptation): a
patch is captured once at the seed frame and re-located each subsequent
frame with normalized cross-correlation (``cv2.TM_CCOEFF_NORMED``) inside a
search window predicted from the previous frame's result. This mirrors the
same "no premature cleverness" trade-off the roto/animation modules already
make, and is robust enough for typical tracking markers and high-contrast
features without drifting from repeated template re-capture.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

# Normalized cross-correlation below this is treated as a lost track for
# this frame rather than a low-confidence guess (avoids drifting onto noise).
_MATCH_CONFIDENCE_FLOOR: float = 0.35
# Smallest half-extent (px) for an extracted patch/search window, so tiny
# region sizes on low-resolution proxies still yield a usable template.
_MIN_HALF_EXTENT_PX: int = 4

FrameSampler = Callable[[int], "np.ndarray | None"]
CancelPoll = Callable[[], bool]
ProgressCallback = Callable[[int, int], None]
NormalizedPoint = tuple[float, float]


def track_point_range(
    sample_frame: FrameSampler,
    frame_numbers: list[int],
    *,
    initial_center: NormalizedPoint,
    region_size: NormalizedPoint,
    search_radius: float,
    should_cancel: CancelPoll | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[int, NormalizedPoint]:
    """Track one point across ``frame_numbers`` via fixed-template matching.

    Parameters:
        sample_frame: Returns an RGB float32 frame for a frame number, or
            ``None`` when it can't be evaluated (treated as a skipped frame).
        frame_numbers: Ordered frames to visit; the first is the seed frame
            whose patch becomes the reference template.
        initial_center: Normalized ``(x, y)`` seed position at
            ``frame_numbers[0]``.
        region_size: Normalized ``(width, height)`` of the tracked patch.
        search_radius: Normalized max per-step search offset from the
            previous frame's tracked position.
        should_cancel: Polled between frames for cooperative cancellation.
        on_progress: Called with ``(done, total)`` after each attempted frame.

    Returns:
        Map of frame number to tracked normalized ``(x, y)``. Frames where
        the template/search window couldn't be built (e.g. off-frame, lost
        track) are omitted — downstream ``AnimationCurve`` interpolation
        holds smoothly across any gaps.
    """
    if not frame_numbers:
        return {}

    total = len(frame_numbers)
    results: dict[int, NormalizedPoint] = {}

    seed_frame = sample_frame(frame_numbers[0])
    if seed_frame is None:
        return {}
    height, width = seed_frame.shape[:2]
    template = _extract_patch(seed_frame, initial_center, region_size, width, height)
    if template is None:
        return {}

    results[frame_numbers[0]] = initial_center
    current_center = initial_center
    if on_progress is not None:
        on_progress(1, total)

    for index, frame_num in enumerate(frame_numbers[1:], start=1):
        if should_cancel is not None and should_cancel():
            break
        frame = sample_frame(frame_num)
        if frame is not None:
            matched = _match_patch(
                frame, template, current_center, search_radius, width, height
            )
            if matched is not None:
                current_center = matched
                results[frame_num] = matched
        if on_progress is not None:
            on_progress(index + 1, total)

    return results


def track_planar_range(
    sample_frame: FrameSampler,
    frame_numbers: list[int],
    *,
    initial_corners: tuple[
        NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint
    ],
    region_size: NormalizedPoint,
    search_radius: float,
    should_cancel: CancelPoll | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[
    dict[int, NormalizedPoint],
    dict[int, NormalizedPoint],
    dict[int, NormalizedPoint],
    dict[int, NormalizedPoint],
]:
    """Track four independent corner points for a planar/perspective tracker.

    Each corner is tracked with its own fixed template via
    ``track_point_range``; ``Project``'s frame cache means the four passes
    only decode/evaluate each source frame once.

    Returns:
        ``(top_left, top_right, bottom_right, bottom_left)`` result maps,
        each shaped like ``track_point_range``'s return value.
    """
    corner_count = 4
    results: list[dict[int, NormalizedPoint]] = []
    for index, corner in enumerate(initial_corners):
        if should_cancel is not None and should_cancel():
            results.append({})
            continue

        def corner_progress(
            done: int, total: int, _index: int = index
        ) -> None:
            if on_progress is not None:
                on_progress(_index * total + done, total * corner_count)

        results.append(
            track_point_range(
                sample_frame,
                frame_numbers,
                initial_center=corner,
                region_size=region_size,
                search_radius=search_radius,
                should_cancel=should_cancel,
                on_progress=corner_progress,
            )
        )
    return results[0], results[1], results[2], results[3]


def _to_gray_u8(frame: np.ndarray) -> np.ndarray:
    """Convert an RGB float32 frame region to contiguous grayscale uint8."""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    return np.ascontiguousarray(np.clip(gray * 255.0, 0.0, 255.0)).astype(np.uint8)


def _extract_patch(
    frame: np.ndarray,
    center: NormalizedPoint,
    size: NormalizedPoint,
    width: int,
    height: int,
) -> np.ndarray | None:
    """Crop a grayscale uint8 template patch around a normalized center."""
    half_w = max(_MIN_HALF_EXTENT_PX, round(size[0] * width * 0.5))
    half_h = max(_MIN_HALF_EXTENT_PX, round(size[1] * height * 0.5))
    cx = round(center[0] * width)
    cy = round(center[1] * height)
    x0, x1 = cx - half_w, cx + half_w
    y0, y1 = cy - half_h, cy + half_h
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height or x1 <= x0 or y1 <= y0:
        return None
    return _to_gray_u8(frame[y0:y1, x0:x1])


def _match_patch(
    frame: np.ndarray,
    template_u8: np.ndarray,
    predicted_center: NormalizedPoint,
    search_radius: float,
    width: int,
    height: int,
) -> NormalizedPoint | None:
    """Search a window around ``predicted_center`` for the best template match."""
    if frame.shape[1] != width or frame.shape[0] != height:
        return None
    template_h, template_w = template_u8.shape[:2]
    margin_x = max(_MIN_HALF_EXTENT_PX, round(search_radius * width))
    margin_y = max(_MIN_HALF_EXTENT_PX, round(search_radius * height))
    cx = round(predicted_center[0] * width)
    cy = round(predicted_center[1] * height)
    # Symmetric half-extent: margin (how far the center may drift) plus half
    # the template, so the matched template center can reach the full
    # +/-margin range from ``predicted_center`` without running off the
    # window that ``cv2.matchTemplate`` slides the template across.
    half_search_x = margin_x + template_w // 2
    half_search_y = margin_y + template_h // 2
    x0 = max(0, cx - half_search_x)
    y0 = max(0, cy - half_search_y)
    x1 = min(width, cx + half_search_x)
    y1 = min(height, cy + half_search_y)
    if x1 - x0 < template_w or y1 - y0 < template_h:
        return None

    window = _to_gray_u8(frame[y0:y1, x0:x1])
    correlation = cv2.matchTemplate(window, template_u8, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(correlation)
    if max_val < _MATCH_CONFIDENCE_FLOOR:
        return None
    match_x = x0 + max_loc[0] + template_w / 2.0
    match_y = y0 + max_loc[1] + template_h / 2.0
    return match_x / width, match_y / height
