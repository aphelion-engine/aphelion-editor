"""Procedural RGB frame generators."""

from __future__ import annotations

import numpy as np

from core.nodes.base import ColorRgb
from core.nodes.enums import GradientMode
from effects.frame_ops import color01


def solid_color(width: int, height: int, color: ColorRgb) -> np.ndarray:
    """Generate a constant RGB frame."""
    frame: np.ndarray = np.empty((height, width, 3), dtype=np.float32)
    frame[:, :] = color01(color)
    return frame


def gradient(
    width: int,
    height: int,
    *,
    start_color: ColorRgb,
    end_color: ColorRgb,
    mode: GradientMode,
    center_x: float,
    center_y: float,
) -> np.ndarray:
    """Generate linear/diagonal/radial RGB gradient."""
    blend: np.ndarray = _gradient_weights(
        width,
        height,
        mode=mode,
        center_x=center_x,
        center_y=center_y,
    )
    start: np.ndarray = color01(start_color).reshape(1, 1, 3)
    end: np.ndarray = color01(end_color).reshape(1, 1, 3)
    output: np.ndarray = start * (1.0 - blend) + end * blend
    return output.astype(np.float32, copy=False)


def checkerboard(
    width: int,
    height: int,
    *,
    color_a: ColorRgb,
    color_b: ColorRgb,
    cell_size: int,
    offset_x: int,
    offset_y: int,
) -> np.ndarray:
    """Generate a two-color checkerboard."""
    cell: int = max(1, cell_size)
    x_axis: np.ndarray = (np.arange(width, dtype=np.int32) + offset_x) // cell
    y_axis: np.ndarray = (np.arange(height, dtype=np.int32) + offset_y) // cell
    selector: np.ndarray = (y_axis[:, None] + x_axis[None, :]) % 2 == 0
    output: np.ndarray = np.empty((height, width, 3), dtype=np.float32)
    output[selector] = color01(color_a)
    output[~selector] = color01(color_b)
    return output


def color_bars(width: int, height: int) -> np.ndarray:
    """Generate seven standard 75%-intensity reference bars."""
    colors: np.ndarray = np.asarray(
        (
            (191, 191, 191),
            (191, 191, 0),
            (0, 191, 191),
            (0, 191, 0),
            (191, 0, 191),
            (191, 0, 0),
            (0, 0, 191),
        ),
        dtype=np.float32,
    ) * np.float32(1.0 / 255.0)
    indices: np.ndarray = np.minimum(
        np.arange(width, dtype=np.int32) * len(colors) // max(1, width),
        len(colors) - 1,
    )
    row: np.ndarray = colors[indices]
    return np.broadcast_to(row, (height, width, 3)).copy()


def _gradient_weights(
    width: int,
    height: int,
    *,
    mode: GradientMode,
    center_x: float,
    center_y: float,
) -> np.ndarray:
    """Build a single-channel 0-1 weight field for a gradient mode."""
    x_axis: np.ndarray = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y_axis: np.ndarray = np.linspace(0.0, 1.0, height, dtype=np.float32)
    if mode == GradientMode.Horizontal:
        return np.broadcast_to(x_axis[None, :, None], (height, width, 1))
    if mode == GradientMode.Vertical:
        return np.broadcast_to(y_axis[:, None, None], (height, width, 1))
    xx: np.ndarray
    yy: np.ndarray
    xx, yy = np.meshgrid(x_axis, y_axis)
    if mode == GradientMode.Diagonal:
        diagonal: np.ndarray = ((xx + yy) * np.float32(0.5))[..., None]
        return diagonal
    distance: np.ndarray = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
    max_distance: float = max(0.001, np.sqrt(0.5**2 + 0.5**2))
    radial: np.ndarray = np.clip(distance / max_distance, 0.0, 1.0)[..., None]
    return radial
