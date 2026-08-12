"""Shared, allocation-conscious operations for float32 RGB frame effects.

Canonical in-graph frame contract: ``HxWx3`` ``np.float32`` with a nominal
``[0.0, 1.0]`` range representing display-referred SDR. Values may briefly
exceed this range mid-graph (e.g. after an exposure boost); only the
display/export boundary (`to_display_u8`) clamps back to ``[0, 1]`` before
quantizing to 8-bit.
"""

from __future__ import annotations

import cv2
import numpy as np

from core.nodes.base import ColorRgb

FRAME_DTYPE: np.dtype = np.dtype(np.float32)


def ensure_rgb_f32(frame: np.ndarray) -> np.ndarray:
    """Return a contiguous 3-channel RGB float32 view/copy.

    Only shape/channel-count is normalized here. Values are assumed to
    already live in the pipeline's ``[0, 1]`` contract; use
    ``from_source_u8`` to promote raw 8-bit decoder/import output instead.
    """
    normalized: np.ndarray = frame.astype(np.float32, copy=False)
    if normalized.ndim == 2:
        return cv2.cvtColor(normalized, cv2.COLOR_GRAY2RGB)
    if normalized.shape[2] == 4:
        return cv2.cvtColor(normalized, cv2.COLOR_RGBA2RGB)
    return np.ascontiguousarray(normalized[:, :, :3])


def from_source_u8(frame_u8: np.ndarray) -> np.ndarray:
    """Promote a raw 8-bit RGB frame (decoder/import) into the float pipeline."""
    return frame_u8.astype(np.float32) * np.float32(1.0 / 255.0)


def to_display_u8(frame_f32: np.ndarray) -> np.ndarray:
    """Quantize a float32 pipeline frame for Qt display or 8-bit export."""
    clamped: np.ndarray = np.clip(frame_f32, 0.0, 1.0)
    return np.rint(clamped * np.float32(255.0)).astype(np.uint8)


def color01(rgb: ColorRgb) -> np.ndarray:
    """Convert a 0-255 UI color tuple to a float32 ``(3,)`` array in ``[0, 1]``."""
    return np.asarray(rgb, dtype=np.float32) * np.float32(1.0 / 255.0)


def resize_like(frame: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Resize ``frame`` to ``reference`` dimensions only when required."""
    target_height: int = int(reference.shape[0])
    target_width: int = int(reference.shape[1])
    if frame.shape[:2] == (target_height, target_width):
        return frame
    interpolation: int = (
        cv2.INTER_AREA
        if frame.shape[0] > target_height or frame.shape[1] > target_width
        else cv2.INTER_LINEAR
    )
    return cv2.resize(frame, (target_width, target_height), interpolation=interpolation)


def mix_frames(
    source: np.ndarray,
    effected: np.ndarray,
    amount: float,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Mix ``effected`` over ``source`` using amount and optional luma mask."""
    mix: float = float(np.clip(amount, 0.0, 1.0))
    if mix <= 0.0:
        return source
    foreground: np.ndarray = resize_like(effected, source)
    if mask is None:
        if mix >= 1.0:
            return foreground
        return source * np.float32(1.0 - mix) + foreground * np.float32(mix)
    return _masked_mix(source, foreground, mix, mask)


def luma_mask(mask: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Return a resized float32 mask shaped ``HxWx1`` in 0-1."""
    normalized: np.ndarray = resize_like(ensure_rgb_f32(mask), reference)
    gray: np.ndarray = cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY)
    return gray[..., None]


def _masked_mix(
    source: np.ndarray,
    foreground: np.ndarray,
    amount: float,
    mask: np.ndarray,
) -> np.ndarray:
    """Blend two aligned RGB frames through a float32 luma mask."""
    alpha: np.ndarray = luma_mask(mask, source)
    if amount < 1.0:
        alpha = alpha * np.float32(amount)
    return source * (1.0 - alpha) + foreground * alpha
