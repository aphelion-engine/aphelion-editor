"""Stylization and post-process frame effects."""

from __future__ import annotations

import math

import cv2
import numpy as np

from core.nodes.base import NEUTRAL_COLOR_RGB, ColorRgb
from effects.frame_ops import color01, ensure_rgb_f32


#: Base grain standard deviation expressed in 0-1 display units. Kept as a
#: module constant so the Amount slider stays expressed as a percentage.
_GRAIN_SIGMA: float = 42.0 / 255.0


def film_grain(
    frame: np.ndarray,
    *,
    amount: float,
    frame_num: int,
    seed: int,
    size: float = 1.0,
    monochrome: bool = False,
) -> np.ndarray:
    """Add temporal film grain noise.

    ``size`` scales the grain clump size (1.0 is per-pixel sensor noise)
    and ``monochrome`` correlates the three channels so the grain reads as
    a single silver-halide layer instead of RGB confetti.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    if amount <= 1e-6:
        return source
    rng: np.random.Generator = np.random.default_rng(seed + frame_num * 7919)
    height: int
    width: int
    height, width = source.shape[:2]
    scale: float = float(np.clip(size, 0.25, 8.0))

    if monochrome:
        single: np.ndarray = _grain_field(rng, height, width, scale)
        noise: np.ndarray = np.repeat(single[:, :, None], 3, axis=2)
    else:
        noise = _grain_field(rng, height, width, scale, channels=3)

    sigma: np.float32 = np.float32(amount * _GRAIN_SIGMA)
    return np.clip(source + noise * sigma, 0.0, 1.0).astype(np.float32, copy=False)


def _grain_field(
    rng: np.random.Generator,
    height: int,
    width: int,
    scale: float,
    channels: int = 0,
) -> np.ndarray:
    """Return a unit-variance noise field, optionally at reduced resolution."""
    shape: tuple[int, ...] = (height, width) if channels == 0 else (height, width, channels)
    if scale <= 1.01:
        return rng.normal(0.0, 1.0, shape).astype(np.float32)
    coarse_h: int = max(1, int(height / scale))
    coarse_w: int = max(1, int(width / scale))
    coarse_shape: tuple[int, ...] = (coarse_h, coarse_w) if channels == 0 else (coarse_h, coarse_w, channels)
    coarse: np.ndarray = rng.normal(0.0, 1.0, coarse_shape).astype(np.float32)
    return cv2.resize(coarse, (width, height), interpolation=cv2.INTER_LINEAR)


def scanlines(
    frame: np.ndarray,
    *,
    intensity: float,
    spacing: int,
    scroll: float,
    frame_num: int,
    line_width: int = 1,
    flicker: float = 0.0,
) -> np.ndarray:
    """Darken alternating rows to emulate CRT scanlines.

    ``line_width`` thickens each darkened band; ``flicker`` modulates the
    overall darkness frame to frame for a subtle phosphor instability.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    if intensity <= 1e-6:
        return source
    height: int = source.shape[0]
    step: int = max(2, spacing)
    offset: int = int(scroll * step + frame_num) % step
    width: int = max(1, min(step - 1, int(line_width)))

    level: float = float(intensity)
    if flicker > 1e-6:
        # Deterministic 0-1 hash of the frame number; avoids RNG state and
        # keeps repeated renders of the same range identical.
        hashed: float = math.sin(frame_num * 12.9898) * 43758.5453
        hashed -= math.floor(hashed)
        level *= 1.0 + float(flicker) * (hashed * 2.0 - 1.0)

    rows: np.ndarray = np.arange(height)
    phase: np.ndarray = (rows - offset) % step
    mask: np.ndarray = np.where(
        phase < width,
        1.0 - np.clip(level, 0.0, 1.0),
        1.0,
    ).astype(np.float32)[:, None, None]
    return np.clip(source * mask, 0.0, 1.0).astype(np.float32, copy=False)


def bloom(
    frame: np.ndarray,
    *,
    threshold: float,
    intensity: float,
    radius: int,
    softness: float = 0.0,
    tint: ColorRgb = NEUTRAL_COLOR_RGB,
) -> np.ndarray:
    """Add a soft glow from bright regions.

    ``softness`` turns the hard highlight cutoff into a gradual knee, and
    ``tint`` colors the glow independently of the source (useful for
    anamorphic or sodium-lamp looks).
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    if intensity <= 1e-6:
        return source
    luminance: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    if softness > 1e-6:
        # Linear roll-off above the threshold: fully bright by one knee
        # width past it, instead of clipping abruptly.
        bright: np.ndarray = np.clip(
            (luminance - threshold) / max(1e-4, softness), 0.0, 1.0
        )
    else:
        bright = np.clip(luminance - threshold, 0.0, 1.0)
    glow: np.ndarray = cv2.GaussianBlur(bright, (0, 0), sigmaX=max(1, radius))
    glow_rgb: np.ndarray = cv2.cvtColor(glow, cv2.COLOR_GRAY2RGB)
    tint_rgb: np.ndarray = color01(tint).reshape(1, 1, 3)
    return np.clip(
        source + glow_rgb * (np.float32(intensity) * tint_rgb), 0.0, 1.0
    ).astype(np.float32, copy=False)


def radial_blur(
    frame: np.ndarray,
    *,
    amount: float,
    center_x: float,
    center_y: float,
    samples: int,
    falloff: float = 1.0,
) -> np.ndarray:
    """Approximate a zoom/radial blur by averaging scaled copies.

    ``falloff`` biases where the scaled copies spend their samples: values
    above 1.0 pluck the blur toward the frame edges, values below 1.0 keep
    it concentrated near the center.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    if amount <= 1e-6:
        return source
    height: int
    width: int
    height, width = source.shape[:2]
    cx: float = center_x * width
    cy: float = center_y * height
    count: int = max(3, samples)
    bias: float = float(np.clip(falloff, 0.1, 4.0))
    accum: np.ndarray = np.zeros(source.shape, dtype=np.float32)
    for index in range(count):
        t: float = index / max(1, count - 1)
        # Warp the 0-1 sample ramp so the copies cluster toward an edge of
        # the scale range instead of spreading uniformly.
        offset: float = t - 0.5
        shaped: float = offset * (1.0 + (bias - 1.0) * abs(offset) * 2.0)
        scale: float = 1.0 + amount * shaped * 0.35
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
