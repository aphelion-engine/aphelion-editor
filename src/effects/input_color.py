"""Color transforms used at media-input boundaries."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np


def load_cube(path: str) -> tuple[np.ndarray, int] | None:
    """Load a compact Iridas/Resolve-style ``.cube`` 3D LUT."""
    if not path or not os.path.isfile(path):
        return None
    size = 0
    values: list[tuple[float, float, float]] = []
    try:
        for raw in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if parts[0].upper() == "LUT_3D_SIZE" and len(parts) >= 2:
                size = int(parts[1])
            elif len(parts) >= 3:
                values.append((float(parts[0]), float(parts[1]), float(parts[2])))
        if size < 2 or len(values) != size**3:
            return None
        return np.asarray(values, dtype=np.float32).reshape((size, size, size, 3)), size
    except (OSError, TypeError, ValueError):
        return None


def apply_cube(frame: np.ndarray, lut: tuple[np.ndarray, int], strength: float) -> np.ndarray:
    """Apply a 3D LUT with trilinear interpolation and adjustable mix."""
    table, size = lut
    rgb = np.clip(np.asarray(frame, dtype=np.float32), 0.0, 1.0)
    scale = np.float32(size - 1)
    point = rgb * scale
    low = np.floor(point).astype(np.int32)
    high = np.minimum(low + 1, size - 1)
    weight = point - low

    def sample(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
        return table[r, g, b]

    c000 = sample(low[..., 0], low[..., 1], low[..., 2])
    c001 = sample(low[..., 0], low[..., 1], high[..., 2])
    c010 = sample(low[..., 0], high[..., 1], low[..., 2])
    c011 = sample(low[..., 0], high[..., 1], high[..., 2])
    c100 = sample(high[..., 0], low[..., 1], low[..., 2])
    c101 = sample(high[..., 0], low[..., 1], high[..., 2])
    c110 = sample(high[..., 0], high[..., 1], low[..., 2])
    c111 = sample(high[..., 0], high[..., 1], high[..., 2])
    wx, wy, wz = weight[..., 0:1], weight[..., 1:2], weight[..., 2:3]
    c00 = c000 * (1 - wz) + c001 * wz
    c01 = c010 * (1 - wz) + c011 * wz
    c10 = c100 * (1 - wz) + c101 * wz
    c11 = c110 * (1 - wz) + c111 * wz
    transformed = (c00 * (1 - wy) + c01 * wy) * (1 - wx) + (c10 * (1 - wy) + c11 * wy) * wx
    amount = np.float32(np.clip(float(strength), 0.0, 1.0))
    return rgb + (transformed - rgb) * amount


def apply_input_color(
    frame: np.ndarray,
    color_space: str,
    lut: tuple[np.ndarray, int] | None = None,
    lut_strength: float = 1.0,
) -> np.ndarray:
    """Convert an input frame to the editor's normalized working space."""
    result = np.asarray(frame, dtype=np.float32)
    mode = str(color_space).lower().replace(" ", "_")
    if mode in {"linear", "linear_rgb"}:
        result = np.where(
            result <= 0.04045,
            result / 12.92,
            np.power((result + 0.055) / 1.055, 2.4),
        ).astype(np.float32)
    elif mode in {"log_c", "logc", "arri_logc3"}:
        result = np.maximum(0.0, np.power(10.0, (result - 0.0928) / 0.2472) - 0.01)
    if lut is not None:
        result = apply_cube(result, lut, lut_strength)
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)
