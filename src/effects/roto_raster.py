"""Rasterize roto shape documents into float32 masks."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from core.roto.interpolation import interpolate_points
from core.roto.model import RotoDocument, RotoPoint

# Line segments generated per Catmull-Rom curve segment when a shape is smooth.
_SUBDIVISIONS_PER_SEGMENT: int = 12

_Point = tuple[float, float]


def _catmull_rom_segment(
    p0: _Point,
    p1: _Point,
    p2: _Point,
    p3: _Point,
    num_samples: int,
) -> list[_Point]:
    """Sample a Catmull-Rom curve segment from ``p1`` to ``p2``."""
    samples: list[_Point] = []
    for i in range(num_samples):
        t: float = i / num_samples
        t2: float = t * t
        t3: float = t2 * t
        x = 0.5 * (
            (2.0 * p1[0])
            + (-p0[0] + p2[0]) * t
            + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
            + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
        )
        y = 0.5 * (
            (2.0 * p1[1])
            + (-p0[1] + p2[1]) * t
            + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
            + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
        )
        samples.append((x, y))
    return samples


def flatten_shape(
    points: Sequence[RotoPoint],
    width: int,
    height: int,
    *,
    closed: bool,
    smooth: bool,
) -> np.ndarray:
    """Convert normalized roto points into pixel-space polygon vertices.

    Parameters:
        points: Normalized (0-1) shape points, already resolved for a frame.
        width: Target raster width in pixels.
        height: Target raster height in pixels.
        closed: Whether the shape wraps back to its first point.
        smooth: When ``True``, subdivide segments with Catmull-Rom curves
            instead of drawing straight lines between points.

    Returns:
        ``Nx2`` ``int32`` array of pixel vertices suitable for
        ``cv2.fillPoly``/``cv2.polylines``.
    """
    if not points:
        return np.zeros((0, 2), dtype=np.int32)

    pixel_points: list[_Point] = [(p.x * width, p.y * height) for p in points]
    if len(pixel_points) < 3 or not smooth:
        vertices: list[_Point] = pixel_points
    else:
        n: int = len(pixel_points)
        segment_count: int = n if closed else n - 1
        vertices = []
        for i in range(segment_count):
            if closed:
                p0 = pixel_points[(i - 1) % n]
                p2 = pixel_points[(i + 1) % n]
                p3 = pixel_points[(i + 2) % n]
            else:
                p0 = pixel_points[max(0, i - 1)]
                p2 = pixel_points[min(n - 1, i + 1)]
                p3 = pixel_points[min(n - 1, i + 2)]
            p1 = pixel_points[i]
            vertices.extend(
                _catmull_rom_segment(p0, p1, p2, p3, _SUBDIVISIONS_PER_SEGMENT)
            )
        if not closed:
            vertices.append(pixel_points[-1])

    return np.array(vertices, dtype=np.int32)


def rasterize_document(
    document: RotoDocument,
    frame_num: int,
    width: int,
    height: int,
) -> np.ndarray:
    """Rasterize every shape in ``document`` at ``frame_num`` into a mask.

    Shapes are combined by taking the per-pixel maximum (union), matching the
    simple combine style already used in ``effects.masks``/``effects.compositing``.
    """
    canvas: np.ndarray = np.zeros((height, width), dtype=np.float32)

    for shape in document.shapes:
        points = interpolate_points(shape.keyframes, frame_num)
        if len(points) < 2:
            continue

        vertices = flatten_shape(
            points, width, height, closed=shape.closed, smooth=shape.smooth
        )
        if vertices.shape[0] < 2:
            continue

        shape_mask: np.ndarray = np.zeros((height, width), dtype=np.uint8)
        if shape.closed and vertices.shape[0] >= 3:
            cv2.fillPoly(shape_mask, [vertices], 255)
        else:
            cv2.polylines(
                shape_mask, [vertices], isClosed=shape.closed, color=255, thickness=1
            )

        shape_mask_f: np.ndarray = shape_mask.astype(np.float32) / 255.0
        if shape.feather > 1e-6:
            radius: int = max(1, round(shape.feather))
            kernel_size: int = radius * 2 + 1
            shape_mask_f = cv2.GaussianBlur(shape_mask_f, (kernel_size, kernel_size), 0.0)

        if shape.invert:
            shape_mask_f = 1.0 - shape_mask_f

        np.maximum(canvas, shape_mask_f, out=canvas)

    return cv2.cvtColor(canvas.astype(np.float32, copy=False), cv2.COLOR_GRAY2RGB)
