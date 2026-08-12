"""Mask extraction and manipulation operations."""

from __future__ import annotations

import cv2
import numpy as np

from core.nodes.enums import MaskChannel
from effects.frame_ops import ensure_rgb_f32


def channel_mask(
    frame: np.ndarray,
    *,
    channel: MaskChannel,
    low: int,
    high: int,
    invert: bool,
) -> np.ndarray:
    """Extract, range-map, and optionally invert a frame channel."""
    source: np.ndarray = ensure_rgb_f32(frame)
    values: np.ndarray = _extract_channel(source, channel)
    low_value: float = max(0.0, min(254.0, float(low))) / 255.0
    high_value: float = max(low_value + 1.0 / 255.0, min(1.0, float(high) / 255.0))
    mask: np.ndarray = (values - low_value) * np.float32(1.0 / (high_value - low_value))
    np.clip(mask, 0.0, 1.0, out=mask)
    if invert:
        mask = 1.0 - mask
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)


def invert_mask(mask: np.ndarray) -> np.ndarray:
    """Invert a mask frame."""
    return 1.0 - ensure_rgb_f32(mask)


def _extract_channel(source: np.ndarray, channel: MaskChannel) -> np.ndarray:
    """Return the selected single-channel view or computed luma."""
    if channel == MaskChannel.Red:
        return source[:, :, 0]
    if channel == MaskChannel.Green:
        return source[:, :, 1]
    if channel == MaskChannel.Blue:
        return source[:, :, 2]
    return cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
