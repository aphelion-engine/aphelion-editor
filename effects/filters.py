"""Spatial image filters backed by optimized OpenCV kernels."""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from core.nodes.base import ColorRgb
from core.nodes.enums import EdgeDisplayMode
from effects.frame_ops import color01, ensure_rgb_f32


def gaussian_blur(frame: np.ndarray, *, radius: int, sigma: float) -> np.ndarray:
    """Apply Gaussian blur; radius zero is a no-op."""
    source: np.ndarray = ensure_rgb_f32(frame)
    safe_radius: int = max(0, min(100, radius))
    if safe_radius == 0:
        return source
    kernel: int = safe_radius * 2 + 1
    return cv2.GaussianBlur(source, (kernel, kernel), max(0.0, sigma))


def unsharp_mask(
    frame: np.ndarray,
    *,
    amount: float,
    radius: int,
    threshold: int,
) -> np.ndarray:
    """Sharpen edges via an unsharp mask with noise thresholding."""
    source: np.ndarray = ensure_rgb_f32(frame)
    blur: np.ndarray = gaussian_blur(source, radius=max(1, radius), sigma=0.0)
    sharpened: np.ndarray = source * np.float32(1.0 + amount) + blur * np.float32(-amount)
    if threshold <= 0:
        return sharpened
    delta: np.ndarray = np.abs(source - blur)
    gray_delta: np.ndarray = cv2.cvtColor(delta, cv2.COLOR_RGB2GRAY)
    quiet: np.ndarray = gray_delta < np.float32(threshold / 255.0)
    sharpened[quiet] = source[quiet]
    return sharpened


def bilateral_denoise(
    frame: np.ndarray,
    *,
    diameter: int,
    color_sigma: float,
    space_sigma: float,
) -> np.ndarray:
    """Edge-preserving bilateral noise reduction."""
    source: np.ndarray = ensure_rgb_f32(frame)
    safe_diameter: int = max(1, min(15, diameter))
    # Bilateral color-space sigma is expressed in 0-1 units here (was 0-255).
    return cv2.bilateralFilter(
        source, safe_diameter, color_sigma / 255.0, space_sigma
    )


def edge_detect(
    frame: np.ndarray,
    *,
    low_threshold: int,
    high_threshold: int,
    display: EdgeDisplayMode,
) -> np.ndarray:
    """Detect Canny edges and return a three-channel preview."""
    source: np.ndarray = ensure_rgb_f32(frame)
    gray_f32: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    # cv2.Canny requires 8-bit input; this is the one local bridge to uint8.
    gray_u8: np.ndarray = np.clip(gray_f32 * 255.0, 0, 255).astype(np.uint8)
    low: int = max(0, min(255, low_threshold))
    high: int = max(low + 1, min(255, high_threshold))
    edges: np.ndarray = cv2.Canny(gray_u8, low, high)
    if display == EdgeDisplayMode.BlackOnWhite:
        edges = cv2.bitwise_not(edges)
    edges_f32: np.ndarray = edges.astype(np.float32) * np.float32(1.0 / 255.0)
    if display == EdgeDisplayMode.Grayscale:
        softened: np.ndarray = cv2.GaussianBlur(edges_f32, (3, 3), 0.0)
        return cv2.cvtColor(softened, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(edges_f32, cv2.COLOR_GRAY2RGB)


def motion_blur(frame: np.ndarray, *, angle_degrees: float, distance: int) -> np.ndarray:
    """Simulate linear motion blur with a normalized directional line kernel."""
    source: np.ndarray = ensure_rgb_f32(frame)
    length: int = max(1, min(200, distance))
    if length <= 1:
        return source
    kernel: np.ndarray = _motion_blur_kernel(length, round(angle_degrees, 1))
    return cv2.filter2D(source, -1, kernel, borderType=cv2.BORDER_REPLICATE)


@lru_cache(maxsize=64)
def _motion_blur_kernel(length: int, angle_degrees: float) -> np.ndarray:
    """Build and cache a normalized ``length``x``length`` directional kernel."""
    kernel: np.ndarray = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    center: tuple[float, float] = (length / 2.0, length / 2.0)
    rotation: np.ndarray = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    rotated: np.ndarray = cv2.warpAffine(kernel, rotation, (length, length))
    total: float = float(np.sum(rotated))
    if total <= 1e-6:
        rotated[length // 2, length // 2] = 1.0
        total = 1.0
    return rotated / total


def pixelate(frame: np.ndarray, *, block_size: int) -> np.ndarray:
    """Pixelate by downsampling then nearest-neighbor upsampling."""
    source: np.ndarray = ensure_rgb_f32(frame)
    block: int = max(1, min(256, block_size))
    if block == 1:
        return source
    height: int
    width: int
    height, width = source.shape[:2]
    small_width: int = max(1, width // block)
    small_height: int = max(1, height // block)
    small: np.ndarray = cv2.resize(
        source, (small_width, small_height), interpolation=cv2.INTER_AREA
    )
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)


def vignette(
    frame: np.ndarray,
    *,
    amount: float,
    softness: float,
    color: ColorRgb,
) -> np.ndarray:
    """Blend a configurable color toward frame edges."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    mask: np.ndarray = _vignette_mask(height, width, round(softness, 2))
    alpha: np.ndarray = mask * np.float32(np.clip(amount, 0.0, 1.0))
    output: np.ndarray = source.copy()
    color_array: np.ndarray = color01(color).reshape(1, 1, 3)
    output *= 1.0 - alpha
    output += color_array * alpha
    return output


@lru_cache(maxsize=12)
def _vignette_mask(height: int, width: int, softness: float) -> np.ndarray:
    """Build and cache a normalized radial edge mask."""
    y_axis: np.ndarray = np.linspace(-1.0, 1.0, height, dtype=np.float32)
    x_axis: np.ndarray = np.linspace(-1.0, 1.0, width, dtype=np.float32)
    xx: np.ndarray
    yy: np.ndarray
    xx, yy = np.meshgrid(x_axis, y_axis)
    radius: np.ndarray = np.sqrt(xx * xx + yy * yy)
    start: float = 1.0 - float(np.clip(softness, 0.05, 1.0))
    mask: np.ndarray = np.clip((radius - start) / max(1e-6, 1.0 - start), 0.0, 1.0)
    return mask[..., None]
