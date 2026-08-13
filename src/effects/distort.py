"""Spatial distortion frame effects."""

from __future__ import annotations

import math

import cv2
import numpy as np

from effects.frame_ops import ensure_rgb_f32


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
