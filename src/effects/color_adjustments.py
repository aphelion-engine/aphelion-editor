"""Fast RGB color adjustment primitives for built-in nodes."""

from __future__ import annotations

import cv2
import numpy as np

from core.nodes.base import ColorRgb
from effects.frame_ops import color01, ensure_rgb_f32


def exposure_contrast(
    frame: np.ndarray,
    *,
    exposure: float,
    brightness: float,
    contrast: float,
) -> np.ndarray:
    """Adjust exposure stops, brightness offset, and midpoint contrast."""
    source: np.ndarray = ensure_rgb_f32(frame)
    gain: float = (2.0**exposure) * contrast
    offset: float = brightness * 0.01 + 0.5 * (1.0 - contrast)
    return source * np.float32(gain) + np.float32(offset)


def hue_saturation(
    frame: np.ndarray,
    *,
    hue_degrees: float,
    saturation: float,
    lightness: float,
) -> np.ndarray:
    """Adjust HSV hue/saturation plus a final lightness offset."""
    source: np.ndarray = ensure_rgb_f32(frame)
    hsv: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2HSV)
    hue: np.ndarray = hsv[:, :, 0]
    hsv[:, :, 0] = (hue + hue_degrees) % 360.0
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0.0, 1.0)
    adjusted: np.ndarray = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    if abs(lightness) <= 1e-6:
        return adjusted
    return adjusted + np.float32(lightness * 0.01)


def white_balance(
    frame: np.ndarray,
    *,
    temperature: float,
    tint: float,
) -> np.ndarray:
    """Apply warm/cool and green/magenta channel gains."""
    source: np.ndarray = ensure_rgb_f32(frame)
    temp: float = float(np.clip(temperature, -1.0, 1.0))
    tint_value: float = float(np.clip(tint, -1.0, 1.0))
    red_gain: float = 1.0 + temp * 0.18 - tint_value * 0.06
    green_gain: float = 1.0 + tint_value * 0.12
    blue_gain: float = 1.0 - temp * 0.18 - tint_value * 0.06
    matrix: np.ndarray = np.diag(
        np.asarray((red_gain, green_gain, blue_gain), dtype=np.float32)
    )
    return cv2.transform(source, matrix)


def invert(frame: np.ndarray) -> np.ndarray:
    """Invert every RGB channel."""
    return 1.0 - ensure_rgb_f32(frame)


def monochrome(
    frame: np.ndarray,
    *,
    red_weight: float,
    green_weight: float,
    blue_weight: float,
) -> np.ndarray:
    """Convert to monochrome with normalized custom channel weights."""
    source: np.ndarray = ensure_rgb_f32(frame)
    weights: np.ndarray = np.asarray(
        (red_weight, green_weight, blue_weight), dtype=np.float32
    )
    total: float = float(np.sum(weights))
    if total <= 1e-6:
        weights = np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)
    else:
        weights /= np.float32(total)
    gray: np.ndarray = cv2.transform(source, weights.reshape(1, 3))
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)


def threshold(
    frame: np.ndarray,
    *,
    level: int,
    low_color: ColorRgb,
    high_color: ColorRgb,
) -> np.ndarray:
    """Map luminance below/above ``level`` to two configurable colors."""
    source: np.ndarray = ensure_rgb_f32(frame)
    gray: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    high_mask: np.ndarray = gray >= np.float32(max(0, min(255, level)) / 255.0)
    output: np.ndarray = np.empty_like(source)
    output[:, :] = color01(low_color)
    output[high_mask] = color01(high_color)
    return output


def posterize(frame: np.ndarray, *, levels: int) -> np.ndarray:
    """Quantize each channel to ``levels`` evenly spaced values."""
    source: np.ndarray = ensure_rgb_f32(frame)
    count: int = max(2, min(32, levels))
    step: float = 1.0 / float(count - 1)
    return np.rint(source / step) * np.float32(step)


def channel_mixer(frame: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Transform RGB channels using a 3x3 float32 matrix."""
    source: np.ndarray = ensure_rgb_f32(frame)
    normalized: np.ndarray = np.asarray(matrix, dtype=np.float32).reshape(3, 3)
    return cv2.transform(source, normalized)
