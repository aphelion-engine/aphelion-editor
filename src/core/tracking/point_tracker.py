"""Fixed-template 2D point tracking over a frame range.

The tracker deliberately uses a simple fixed-template approach:

    1. Capture a template once at the seed frame.
    2. Predict the feature position from the previous successful result.
    3. Search for the template inside a local search window.
    4. Accept the result when normalized cross-correlation is sufficiently
       confident.
    5. Keep the original template for the entire track.

No optical flow or online template adaptation is used.

Frames supplied by ``sample_frame`` may be RGB/RGBA arrays using either
floating-point 0..1 values, floating-point 0..255 values, or integer
0..255 values.

The tracker intentionally distinguishes between:

    - a frame that cannot be sampled,
    - an invalid seed/template,
    - a successfully matched frame,
    - a low-confidence match.

This prevents a frame-sampling failure from being mistaken for a tracking
failure.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MATCH_CONFIDENCE_FLOOR: float = 0.35

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
    sample_frame: FrameSampler,
    frame_numbers: list[int],
    *,
    initial_center: NormalizedPoint,
    region_size: NormalizedPoint,
    search_radius: float,
    should_cancel: CancelPoll | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[int, NormalizedPoint]:
    """Track one point across a sequence of frames.

    ``sample_frame`` is expected to return an RGB/RGBA numpy array for the
    requested frame number.

    The first frame is used only to create the fixed reference template.
    Every following frame searches around the previous successful position.

    Frames which cannot be sampled or do not produce a confident match are
    omitted from the returned dictionary.

    Args:
        sample_frame:
            Callable receiving a frame number and returning a numpy frame or
            ``None`` if that frame cannot be sampled.

        frame_numbers:
            Ordered frame numbers to process.

        initial_center:
            Normalized ``(x, y)`` position of the tracked feature on the
            first frame.

        region_size:
            Normalized ``(width, height)`` size of the reference template.

        search_radius:
            Maximum normalized per-frame search distance.

        should_cancel:
            Optional cooperative cancellation callback.

        on_progress:
            Optional callback receiving ``(completed, total)``.

    Returns:
        Dictionary mapping successfully tracked frame numbers to normalized
        ``(x, y)`` positions.
    """

    if not frame_numbers:
        return {}

    total = len(frame_numbers)

    results: dict[int, NormalizedPoint] = {}

    # ------------------------------------------------------------------
    # Normalize inputs
    # ------------------------------------------------------------------

    seed_center = _clamp_point(initial_center)

    region_width = abs(float(region_size[0]))
    region_height = abs(float(region_size[1]))

    search_radius = abs(float(search_radius))

    if region_width <= 0.0 or region_height <= 0.0:
        return {}

    # ------------------------------------------------------------------
    # Seed frame
    # ------------------------------------------------------------------

    seed_frame_number = int(frame_numbers[0])

    seed_frame = _safe_sample_frame(
        sample_frame,
        seed_frame_number,
    )

    if seed_frame is None:
        # The caller's sampler could not provide the seed frame.
        #
        # Do not attempt matching because there is no reference template.
        if on_progress is not None:
            on_progress(0, total)

        return {}

    if not _is_valid_frame(seed_frame):
        if on_progress is not None:
            on_progress(0, total)

        return {}

    seed_height, seed_width = seed_frame.shape[:2]

    if seed_width <= 0 or seed_height <= 0:
        if on_progress is not None:
            on_progress(0, total)

        return {}

    # ------------------------------------------------------------------
    # Extract reference template
    # ------------------------------------------------------------------

    template = _extract_patch(
        seed_frame,
        seed_center,
        (region_width, region_height),
        seed_width,
        seed_height,
    )

    if template is None:
        if on_progress is not None:
            on_progress(0, total)

        return {}

    # CCOEFF_NORMED requires texture/variance.
    if _template_is_degenerate(template):
        if on_progress is not None:
            on_progress(0, total)

        return {}

    # Seed is always considered tracked because the user explicitly placed
    # the initial point there.
    results[seed_frame_number] = seed_center

    current_center = seed_center

    if on_progress is not None:
        on_progress(1, total)

    # ------------------------------------------------------------------
    # Sequential tracking
    # ------------------------------------------------------------------

    for index, frame_number in enumerate(frame_numbers[1:], start=1):
        if should_cancel is not None and should_cancel():
            break

        frame_number = int(frame_number)

        frame = _safe_sample_frame(
            sample_frame,
            frame_number,
        )

        if frame is not None and _is_valid_frame(frame):
            matched = _match_patch(
                frame,
                template,
                current_center,
                search_radius,
                seed_width,
                seed_height,
            )

            if matched is not None:
                current_center = matched
                results[frame_number] = matched

        if on_progress is not None:
            on_progress(index + 1, total)

    return results


def track_planar_range(
    sample_frame: FrameSampler,
    frame_numbers: list[int],
    *,
    initial_corners: tuple[
        NormalizedPoint,
        NormalizedPoint,
        NormalizedPoint,
        NormalizedPoint,
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
    """Track four independent planar-tracking corner points.

    The returned tuple is:

        (
            top_left,
            top_right,
            bottom_right,
            bottom_left,
        )

    Each entry is a dictionary mapping frame numbers to normalized points.
    """

    empty_result = ({}, {}, {}, {})

    if not frame_numbers:
        return empty_result

    corners = (
        initial_corners[0],
        initial_corners[1],
        initial_corners[2],
        initial_corners[3],
    )

    results: list[dict[int, NormalizedPoint]] = []

    corner_count = 4

    for corner_index, corner in enumerate(corners):
        if should_cancel is not None and should_cancel():
            results.append({})
            continue

        def corner_progress(
            done: int,
            total: int,
            *,
            _corner_index: int = corner_index,
        ) -> None:
            if on_progress is not None:
                on_progress(
                    (_corner_index * total) + done,
                    total * corner_count,
                )

        result = track_point_range(
            sample_frame,
            frame_numbers,
            initial_center=corner,
            region_size=region_size,
            search_radius=search_radius,
            should_cancel=should_cancel,
            on_progress=corner_progress,
        )

        results.append(result)

    while len(results) < 4:
        results.append({})

    return (
        results[0],
        results[1],
        results[2],
        results[3],
    )


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


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _match_patch(
    frame: np.ndarray,
    template_u8: np.ndarray,
    predicted_center: NormalizedPoint,
    search_radius: float,
    width: int,
    height: int,
) -> NormalizedPoint | None:
    """Find the best template match around a predicted position."""

    if not _is_valid_frame(frame):
        return None

    frame_height, frame_width = frame.shape[:2]

    if frame_width != width:
        return None

    if frame_height != height:
        return None

    template_height, template_width = (
        template_u8.shape[:2]
    )

    if template_width <= 0:
        return None

    if template_height <= 0:
        return None

    if template_width > width:
        return None

    if template_height > height:
        return None

    if _template_is_degenerate(template_u8):
        return None

    # ---------------------------------------------------------------
    # Calculate search region
    # ---------------------------------------------------------------

    margin_x = max(
        _MIN_HALF_EXTENT_PX,
        int(round(abs(search_radius) * width)),
    )

    margin_y = max(
        _MIN_HALF_EXTENT_PX,
        int(round(abs(search_radius) * height)),
    )

    cx = int(round(
        predicted_center[0] * width
    ))

    cy = int(round(
        predicted_center[1] * height
    ))

    # Include the complete template around every possible center in the
    # search radius.
    half_search_x = (
        margin_x
        + template_width // 2
    )

    half_search_y = (
        margin_y
        + template_height // 2
    )

    x0 = max(
        0,
        cx - half_search_x,
    )

    y0 = max(
        0,
        cy - half_search_y,
    )

    x1 = min(
        width,
        cx + half_search_x,
    )

    y1 = min(
        height,
        cy + half_search_y,
    )

    if x1 - x0 < template_width:
        return None

    if y1 - y0 < template_height:
        return None

    window = frame[
        y0:y1,
        x0:x1,
    ]

    if window.size == 0:
        return None

    window_u8 = _to_gray_u8(window)

    if window_u8.shape[1] < template_width:
        return None

    if window_u8.shape[0] < template_height:
        return None

    # ---------------------------------------------------------------
    # Perform normalized cross-correlation
    # ---------------------------------------------------------------

    try:
        correlation = cv2.matchTemplate(
            window_u8,
            template_u8,
            cv2.TM_CCOEFF_NORMED,
        )
    except cv2.error:
        return None

    if correlation.size == 0:
        return None

    # OpenCV may generate NaN for pathological low-variance inputs.
    correlation = np.nan_to_num(
        correlation,
        nan=-1.0,
        posinf=-1.0,
        neginf=-1.0,
    )

    _min_value, max_value, _min_location, max_location = (
        cv2.minMaxLoc(correlation)
    )

    if not np.isfinite(max_value):
        return None

    if max_value < _MATCH_CONFIDENCE_FLOOR:
        return None

    # ---------------------------------------------------------------
    # Convert match location to template center
    # ---------------------------------------------------------------

    match_x = (
        x0
        + max_location[0]
        + template_width * 0.5
    )

    match_y = (
        y0
        + max_location[1]
        + template_height * 0.5
    )

    normalized_x = match_x / width
    normalized_y = match_y / height

    return _clamp_point(
        (
            normalized_x,
            normalized_y,
        )
    )


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "track_point_range",
    "track_planar_range",
]
