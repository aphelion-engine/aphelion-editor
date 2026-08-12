"""Two-input compositing and blend-mode operations."""

from __future__ import annotations

import numpy as np

from core.nodes.enums import BlendMode
from effects.frame_ops import ensure_rgb_f32, mix_frames, resize_like


def blend_frames(
    background: np.ndarray,
    foreground: np.ndarray,
    *,
    mode: BlendMode,
    opacity: float,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Blend foreground over background with optional luma mask."""
    bg: np.ndarray = ensure_rgb_f32(background)
    fg: np.ndarray = resize_like(ensure_rgb_f32(foreground), bg)
    amount: float = float(np.clip(opacity, 0.0, 1.0))
    if amount <= 0.0:
        return bg
    if mode == BlendMode.Normal:
        return mix_frames(bg, fg, amount, mask)
    blended: np.ndarray = _apply_mode(bg, fg, mode)
    return mix_frames(bg, blended, amount, mask)


def dissolve_frames(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    *,
    mix: float,
) -> np.ndarray:
    """Cross-dissolve linearly from A to B."""
    source_a: np.ndarray = ensure_rgb_f32(frame_a)
    source_b: np.ndarray = resize_like(ensure_rgb_f32(frame_b), source_a)
    return mix_frames(source_a, source_b, mix)


def _apply_mode(bg: np.ndarray, fg: np.ndarray, mode: BlendMode) -> np.ndarray:
    """Apply one blend equation using direct float32 arithmetic."""
    result: np.ndarray
    if mode == BlendMode.Add:
        result = bg + fg
    elif mode == BlendMode.Subtract:
        result = bg - fg
    elif mode == BlendMode.Multiply:
        result = bg * fg
    elif mode == BlendMode.Screen:
        result = _screen(bg, fg)
    elif mode == BlendMode.Overlay:
        result = _overlay(bg, fg)
    elif mode == BlendMode.Difference:
        result = np.abs(bg - fg)
    elif mode == BlendMode.Darken:
        result = np.minimum(bg, fg)
    elif mode == BlendMode.Lighten:
        result = np.maximum(bg, fg)
    else:
        result = fg
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)


def _screen(bg: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """Apply Screen: ``1 - (1 - bg) * (1 - fg)``."""
    return 1.0 - (1.0 - bg) * (1.0 - fg)


def _overlay(bg: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """Apply Overlay by selecting Multiply or Screen per background channel."""
    low: np.ndarray = 2.0 * bg * fg
    high: np.ndarray = _screen(bg, fg) * 2.0 - 1.0
    return np.where(bg < 0.5, low, high).astype(np.float32, copy=False)
