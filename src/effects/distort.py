"""Spatial distortion frame effects."""

from __future__ import annotations

import math

import cv2
import numpy as np
from core.nodes.enums import BendAxis
from effects.frame_ops import ensure_rgb_f32, resize_like


def twirl(
    frame: np.ndarray,
    *,
    angle_degrees: float,
    radius: float,
    strength: float,
    center_x: float,
    center_y: float,
) -> np.ndarray:
    """Rotate pixels around a center within a radial falloff."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    if strength <= 1e-6:
        return source
    cx: float = center_x * width
    cy: float = center_y * height
    max_radius: float = max(8.0, radius * min(width, height) * 0.5)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dx: np.ndarray = xx - cx
    dy: np.ndarray = yy - cy
    distance: np.ndarray = np.sqrt(dx * dx + dy * dy)
    falloff: np.ndarray = np.clip(1.0 - distance / max_radius, 0.0, 1.0)
    theta: np.ndarray = np.arctan2(dy, dx)
    twist: np.ndarray = np.deg2rad(angle_degrees) * falloff * strength
    cos_t: np.ndarray = np.cos(twist)
    sin_t: np.ndarray = np.sin(twist)
    rotated_x: np.ndarray = dx * cos_t - dy * sin_t + cx
    rotated_y: np.ndarray = dx * sin_t + dy * cos_t + cy
    map_x: np.ndarray = np.where(falloff > 0.0, rotated_x, xx)
    map_y: np.ndarray = np.where(falloff > 0.0, rotated_y, yy)
    return cv2.remap(
        source,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def bulge(
    frame: np.ndarray,
    *,
    strength: float,
    radius: float,
    center_x: float,
    center_y: float,
) -> np.ndarray:
    """Magnify or pinch pixels around a radial center."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    if abs(strength) <= 1e-6:
        return source
    cx: float = center_x * width
    cy: float = center_y * height
    max_radius: float = max(8.0, radius * min(width, height) * 0.5)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dx: np.ndarray = xx - cx
    dy: np.ndarray = yy - cy
    distance: np.ndarray = np.sqrt(dx * dx + dy * dy)
    normalized: np.ndarray = np.clip(distance / max_radius, 0.0, 1.0)
    scale: np.ndarray = 1.0 + strength * (1.0 - normalized * normalized)
    safe_scale: np.ndarray = np.where(distance > 1e-3, scale, 1.0)
    map_x: np.ndarray = cx + dx / safe_scale
    map_y: np.ndarray = cy + dy / safe_scale
    return cv2.remap(
        source,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def wave_warp(
    frame: np.ndarray,
    *,
    amplitude: float,
    frequency: float,
    phase: float,
    direction: float,
    frame_num: int,
) -> np.ndarray:
    """Apply directional sinusoidal displacement."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    radians: float = math.radians(direction)
    axis_x: float = math.cos(radians)
    axis_y: float = math.sin(radians)
    projection: np.ndarray = xx * axis_x + yy * axis_y
    wave: np.ndarray = np.sin(
        projection / max(1.0, min(width, height)) * frequency * math.tau
        + math.radians(phase)
        + frame_num * 0.12
    )
    offset: np.ndarray = wave * amplitude * min(width, height) * 0.04
    map_x: np.ndarray = xx + offset * -axis_y
    map_y: np.ndarray = yy + offset * axis_x
    return cv2.remap(
        source,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def tile(
    frame: np.ndarray,
    *,
    columns: int,
    rows: int,
    mirror: bool,
) -> np.ndarray:
    """Repeat the frame into a grid, optionally mirroring alternating tiles."""
    source: np.ndarray = ensure_rgb_f32(frame)
    cols: int = max(1, columns)
    row_count: int = max(1, rows)
    tiles: list[np.ndarray] = []
    for row_index in range(row_count):
        row_tiles: list[np.ndarray] = []
        for col_index in range(cols):
            tile: np.ndarray = source
            if mirror and (row_index + col_index) % 2 == 1:
                tile = cv2.flip(tile, 1)
            row_tiles.append(tile)
        tiles.append(np.hstack(row_tiles))
    output: np.ndarray = np.vstack(tiles)
    height: int
    width: int
    height, width = source.shape[:2]
    return cv2.resize(output, (width, height), interpolation=cv2.INTER_LINEAR)


def bend(
    frame: np.ndarray,
    *,
    amount: float,
    axis: BendAxis,
) -> np.ndarray:
    """Bow the frame along its axis with a parabolic curve.

    Positive ``amount`` bends content toward the far edge, negative toward the
    near edge, which is the classic "page curl without the curl" look used to
    fake curved screens and rolling titles.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    if abs(amount) <= 1e-6:
        return source
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    if axis == BendAxis.Horizontal:
        normalized: np.ndarray = _unit_ramp(height).reshape(height, 1)
        curve: np.ndarray = 1.0 - normalized * normalized
        magnitude: float = float(amount) * width
        return cv2.remap(
            source,
            (xx - curve * magnitude).astype(np.float32),
            yy,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
    normalized = _unit_ramp(width).reshape(1, width)
    curve = 1.0 - normalized * normalized
    magnitude = float(amount) * height
    return cv2.remap(
        source,
        xx,
        (yy - curve * magnitude).astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _unit_ramp(size: int) -> np.ndarray:
    """Return ``[-1, 1]`` coordinates along an axis of ``size`` samples."""
    if size <= 1:
        return np.zeros(max(1, size), dtype=np.float32)
    return (
        np.linspace(-1.0, 1.0, size, dtype=np.float32)
    )


def bump_map(
    frame: np.ndarray,
    height_map: np.ndarray,
    *,
    intensity: float,
    light_x: float,
    light_y: float,
    blur: float,
) -> np.ndarray:
    """Emboss the frame with a height map as if lit from a direction.

    A second frame input supplies the bump heights; the source is shaded by
    the resulting surface normals, which fakes bevels, embossing, and oil
    paint relief without touching the underlying colors.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    bump: np.ndarray = resize_like(ensure_rgb_f32(height_map), source)
    heights: np.ndarray = cv2.cvtColor(bump, cv2.COLOR_RGB2GRAY)
    if blur > 0.0:
        heights = cv2.GaussianBlur(heights, (0, 0), float(blur))
    gradient_x: np.ndarray = cv2.Sobel(
        heights, cv2.CV_32F, 1, 0, ksize=3) * float(intensity)
    gradient_y: np.ndarray = cv2.Sobel(
        heights, cv2.CV_32F, 0, 1, ksize=3) * float(intensity)
    normal: np.ndarray = np.dstack(
        [-gradient_x, -gradient_y, np.ones_like(heights)])
    norm: np.ndarray = np.linalg.norm(normal, axis=2, keepdims=True)
    normal = normal / (norm + 1e-6)

    horizontal: float = float(np.clip(light_x, -1.0, 1.0))
    vertical: float = float(np.clip(light_y, -1.0, 1.0))
    light_z: float = float(
        np.sqrt(max(0.05, 1.0 - horizontal * horizontal - vertical * vertical)))
    light: np.ndarray = np.array(
        [horizontal, vertical, light_z], dtype=np.float32)
    lambert: np.ndarray = np.clip(np.tensordot(
        normal, light, axes=([2], [0])), 0.0, 1.0)
    shade: np.ndarray = 1.0 + (lambert - light_z)
    return source * shade[:, :, None].astype(np.float32)


def offset(
    frame: np.ndarray,
    *,
    offset_x: float,
    offset_y: float,
    wrap: bool,
) -> np.ndarray:
    """Shift the frame by a fraction of its size, wrapping or filling edges."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    shift_x: int = int(round(float(offset_x) * width))
    shift_y: int = int(round(float(offset_y) * height))
    if shift_x == 0 and shift_y == 0:
        return source
    if wrap:
        return np.roll(
            np.roll(source, shift_y, axis=0), shift_x, axis=1
        )
    matrix: np.ndarray = np.array(
        [[1.0, 0.0, float(shift_x)], [0.0, 1.0, float(shift_y)]],
        dtype=np.float32,
    )
    return cv2.warpAffine(
        source,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0.0, 0.0, 0.0),
    )
