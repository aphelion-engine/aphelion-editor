"""Geometric frame transforms and utility masks."""

from __future__ import annotations

import cv2
import numpy as np

from core.nodes.base import ColorRgb
from core.nodes.enums import TransformBorderMode
from effects.frame_ops import color01, ensure_rgb_f32


def transform_2d(
    frame: np.ndarray,
    *,
    translate_x: float,
    translate_y: float,
    scale: float,
    rotation_degrees: float,
    border_mode: TransformBorderMode,
    border_color: ColorRgb,
) -> np.ndarray:
    """Translate, scale, and rotate around frame center."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    center: tuple[float, float] = (width * 0.5, height * 0.5)
    matrix: np.ndarray = cv2.getRotationMatrix2D(center, rotation_degrees, scale)
    matrix[0, 2] += translate_x * width
    matrix[1, 2] += translate_y * height
    border_value: tuple[float, float, float] = tuple(float(v) for v in color01(border_color))
    return cv2.warpAffine(
        source,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=_border_constant(border_mode),
        borderValue=border_value,
    )


def corner_pin(
    frame: np.ndarray,
    *,
    top_left: tuple[float, float],
    top_right: tuple[float, float],
    bottom_right: tuple[float, float],
    bottom_left: tuple[float, float],
    border_mode: TransformBorderMode,
    border_color: ColorRgb,
    stabilize: bool = False,
) -> np.ndarray:
    """Warp a frame so its four corners land at the given normalized points.

    Parameters:
        frame: Source RGB float32 frame.
        top_left/top_right/bottom_right/bottom_left: Destination corner
            positions as ``(x, y)`` fractions of frame width/height. Corners
            may be driven by a ``PlanarTrackerNode`` for match-moved inserts.
        border_mode: Fill behavior for pixels outside the warped quad.
        border_color: Fill color used by ``TransformBorderMode.Black``.
        stabilize: When ``True``, solves the inverse mapping (tracked quad
            back to the full frame) instead — this is how a moving surface
            gets "locked off" so a mask/paint can be drawn once on the
            stabilized result, then warped forward again with the same
            tracked corners and ``stabilize=False`` to follow the plate.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    identity_corners: np.ndarray = np.float32(
        [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]]
    )
    tracked_corners: np.ndarray = np.float32(
        [
            (top_left[0] * width, top_left[1] * height),
            (top_right[0] * width, top_right[1] * height),
            (bottom_right[0] * width, bottom_right[1] * height),
            (bottom_left[0] * width, bottom_left[1] * height),
        ]
    )
    if stabilize:
        matrix: np.ndarray = cv2.getPerspectiveTransform(tracked_corners, identity_corners)
    else:
        matrix = cv2.getPerspectiveTransform(identity_corners, tracked_corners)
    border_value: tuple[float, float, float] = tuple(float(v) for v in color01(border_color))
    return cv2.warpPerspective(
        source,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=_border_constant(border_mode),
        borderValue=border_value,
    )


def crop(
    frame: np.ndarray,
    *,
    left: float,
    right: float,
    top: float,
    bottom: float,
    resize_to_frame: bool,
) -> np.ndarray:
    """Crop normalized edge percentages, optionally restoring source size."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    x0: int = min(width - 1, max(0, round(width * left)))
    x1: int = max(x0 + 1, min(width, round(width * (1.0 - right))))
    y0: int = min(height - 1, max(0, round(height * top)))
    y1: int = max(y0 + 1, min(height, round(height * (1.0 - bottom))))
    cropped: np.ndarray = np.ascontiguousarray(source[y0:y1, x0:x1])
    if not resize_to_frame or cropped.shape[:2] == source.shape[:2]:
        return cropped
    return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)


def luma_key_mask(
    frame: np.ndarray,
    *,
    low: int,
    high: int,
    invert: bool,
) -> np.ndarray:
    """Generate a soft grayscale mask from luminance range."""
    source: np.ndarray = ensure_rgb_f32(frame)
    gray: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    low_value: float = max(0.0, min(254.0, float(low))) / 255.0
    high_value: float = max(low_value + 1.0 / 255.0, min(1.0, float(high) / 255.0))
    mask: np.ndarray = np.clip(
        (gray - low_value) / (high_value - low_value),
        0.0,
        1.0,
    )
    if invert:
        mask = 1.0 - mask
    return cv2.cvtColor(mask.astype(np.float32, copy=False), cv2.COLOR_GRAY2RGB)


def _border_constant(mode: TransformBorderMode) -> int:
    """Map a public border mode to its OpenCV constant."""
    if mode == TransformBorderMode.Hold:
        return cv2.BORDER_REPLICATE
    if mode == TransformBorderMode.Reflect:
        return cv2.BORDER_REFLECT_101
    return cv2.BORDER_CONSTANT
