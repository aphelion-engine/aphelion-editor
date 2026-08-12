"""Chroma keying, spill suppression, and matte edge-cleanup operations."""

from __future__ import annotations

import cv2
import numpy as np

from core.nodes.base import ColorRgb
from effects.frame_ops import color01, ensure_rgb_f32

# Maximum possible Euclidean distance between two RGB points in [0, 1]^3.
_MAX_RGB_DISTANCE: float = float(np.sqrt(3.0))


def chroma_key_mask(
    frame: np.ndarray,
    *,
    key_color: ColorRgb,
    tolerance: float,
    softness: float,
) -> np.ndarray:
    """Generate an alpha-style mask from color distance to ``key_color``.

    Parameters:
        frame: Source RGB float32 frame.
        key_color: 0-255 UI color tuple picked as the screen color.
        tolerance: Normalized distance (0-1) below which pixels are fully
            keyed out (mask 0).
        softness: Normalized distance (0-1) over which the mask ramps from
            0 to 1 beyond ``tolerance``.

    Returns:
        Float32 RGB mask where 0 means "keyed out" and 1 means "kept".
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    key: np.ndarray = color01(key_color).reshape(1, 1, 3)
    diff: np.ndarray = source - key
    distance: np.ndarray = np.sqrt(np.sum(diff * diff, axis=2)) / _MAX_RGB_DISTANCE
    tol: float = max(0.0, float(tolerance))
    soft: float = max(1e-4, float(softness))
    mask: np.ndarray = np.clip((distance - tol) / soft, 0.0, 1.0)
    return cv2.cvtColor(mask.astype(np.float32, copy=False), cv2.COLOR_GRAY2RGB)


def suppress_spill(
    frame: np.ndarray,
    *,
    key_color: ColorRgb,
    amount: float,
) -> np.ndarray:
    """Reduce key-color spill by clamping the dominant channel toward the others.

    Generalizes the classic green/blue-screen despill (``G = min(G, max(R, B))``)
    to an arbitrary key color by suppressing whichever channel dominates it.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    key: np.ndarray = color01(key_color)
    dominant: int = int(np.argmax(key))
    other_a, other_b = (i for i in range(3) if i != dominant)

    dominant_channel: np.ndarray = source[:, :, dominant]
    other_max: np.ndarray = np.maximum(source[:, :, other_a], source[:, :, other_b])
    spill: np.ndarray = np.clip(dominant_channel - other_max, 0.0, None)

    output: np.ndarray = source.copy()
    output[:, :, dominant] = dominant_channel - spill * np.float32(
        np.clip(amount, 0.0, 1.0)
    )
    return output


def refine_matte(
    mask: np.ndarray,
    *,
    choke: float,
    feather: float,
    black_point: float,
    white_point: float,
) -> np.ndarray:
    """Clean up a matte edge: choke/grow, feather, then remap black/white points.

    Parameters:
        mask: Source mask (any RGB-shaped float32 frame; luma is extracted).
        choke: Erode (positive) or dilate (negative) radius in pixels.
        feather: Gaussian blur radius in pixels (softens the edge).
        black_point: Normalized (0-1) level mapped to full transparency.
        white_point: Normalized (0-1) level mapped to full opacity.
    """
    source: np.ndarray = ensure_rgb_f32(mask)
    gray: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)

    if abs(choke) > 1e-6:
        radius: int = max(1, round(abs(choke)))
        kernel: np.ndarray = np.ones((radius * 2 + 1, radius * 2 + 1), np.uint8)
        gray = cv2.erode(gray, kernel) if choke > 0 else cv2.dilate(gray, kernel)

    if feather > 1e-6:
        radius = max(1, round(feather))
        kernel_size: int = radius * 2 + 1
        gray = cv2.GaussianBlur(gray, (kernel_size, kernel_size), 0.0)

    low: float = min(float(black_point), float(white_point) - 1e-3)
    high: float = max(float(white_point), low + 1e-3)
    remapped: np.ndarray = np.clip((gray - low) / (high - low), 0.0, 1.0)
    return cv2.cvtColor(remapped.astype(np.float32, copy=False), cv2.COLOR_GRAY2RGB)
