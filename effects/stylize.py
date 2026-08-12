"""Stylization and post-process frame effects."""

from __future__ import annotations

import cv2
import numpy as np

from effects.frame_ops import ensure_rgb_f32


def film_grain(
    frame: np.ndarray,
    *,
    amount: float,
    frame_num: int,
    seed: int,
) -> np.ndarray:
    """Add temporal film grain noise."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if amount <= 1e-6:
        return source
    rng: np.random.Generator = np.random.default_rng(seed + frame_num * 7919)
    noise: np.ndarray = rng.normal(
        0.0, amount * (42.0 / 255.0), source.shape
    ).astype(np.float32)
    return np.clip(source + noise, 0.0, 1.0).astype(np.float32, copy=False)


def scanlines(
    frame: np.ndarray,
    *,
    intensity: float,
    spacing: int,
    scroll: float,
    frame_num: int,
) -> np.ndarray:
    """Darken alternating rows to emulate CRT scanlines."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if intensity <= 1e-6:
        return source
    height: int = source.shape[0]
    step: int = max(2, spacing)
    offset: int = int(scroll * step + frame_num) % step
    mask: np.ndarray = np.ones((height, 1, 1), dtype=np.float32)
    mask[offset::step] = 1.0 - intensity
    return np.clip(source * mask, 0.0, 1.0).astype(np.float32, copy=False)


def bloom(
    frame: np.ndarray,
    *,
    threshold: float,
    intensity: float,
    radius: int,
) -> np.ndarray:
    """Add a soft glow from bright regions."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if intensity <= 1e-6:
        return source
    luminance: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    bright: np.ndarray = np.clip(luminance - threshold, 0.0, 1.0)
    glow: np.ndarray = cv2.GaussianBlur(bright, (0, 0), sigmaX=max(1, radius))
    glow_rgb: np.ndarray = cv2.cvtColor(glow, cv2.COLOR_GRAY2RGB)
    return np.clip(source + glow_rgb * intensity, 0.0, 1.0).astype(np.float32, copy=False)


def radial_blur(
    frame: np.ndarray,
    *,
    amount: float,
    center_x: float,
    center_y: float,
    samples: int,
) -> np.ndarray:
    """Approximate a zoom/radial blur by averaging scaled copies."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if amount <= 1e-6:
        return source
    height: int
    width: int
    height, width = source.shape[:2]
    cx: float = center_x * width
    cy: float = center_y * height
    count: int = max(3, samples)
    accum: np.ndarray = np.zeros(source.shape, dtype=np.float32)
    for index in range(count):
        t: float = index / max(1, count - 1)
        scale: float = 1.0 + amount * (t - 0.5) * 0.35
        matrix: np.ndarray = cv2.getRotationMatrix2D((cx, cy), 0.0, scale)
        warped: np.ndarray = cv2.warpAffine(
            source,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        accum += warped
    return np.clip(accum / count, 0.0, 1.0).astype(np.float32, copy=False)
