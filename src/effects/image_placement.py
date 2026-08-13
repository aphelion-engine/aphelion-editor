"""Compositing helpers for placing a loaded still image onto a canvas.

Kept separate from ``effects.generators`` since this operates on an already
-decoded RGBA source (with a real alpha channel) rather than procedurally
building pixels — the output is always a straight RGB frame plus a matching
alpha mask, ready for a ``Merge`` node.
"""

from __future__ import annotations

import cv2
import numpy as np

from core.nodes.enums import ImageFitMode


def place_image(
    rgba: np.ndarray,
    canvas_width: int,
    canvas_height: int,
    *,
    fit_mode: ImageFitMode,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Place a native-resolution RGBA image onto a transparent canvas.

    Parameters:
        rgba: Source image as float32 ``HxWx4`` in ``[0, 1]``.
        canvas_width: Target frame width in pixels.
        canvas_height: Target frame height in pixels.
        fit_mode: How the image is scaled to the canvas before ``scale``.
        scale: Additional uniform scale multiplier on top of ``fit_mode``
            (``1.0`` leaves the fitted size unchanged).
        offset_x: Center offset as a fraction of canvas width (``0`` centers).
        offset_y: Center offset as a fraction of canvas height (``0`` centers).

    Returns:
        ``(frame_rgb, mask_rgb)`` — both ``HxWx3`` float32 in ``[0, 1]``.
        ``mask_rgb`` is the placed image's alpha, broadcast to three
        channels so it can feed a ``Merge`` node's mask input directly;
        pixels outside the placed image are fully transparent (``0``).
    """
    canvas_width = max(1, int(canvas_width))
    canvas_height = max(1, int(canvas_height))
    src_height, src_width = rgba.shape[:2]

    if fit_mode == ImageFitMode.Stretch:
        resized = cv2.resize(
            rgba, (canvas_width, canvas_height), interpolation=cv2.INTER_LINEAR
        )
        frame_rgb = np.ascontiguousarray(resized[:, :, :3])
        mask_rgb = np.repeat(resized[:, :, 3:4], 3, axis=2)
        return frame_rgb, mask_rgb

    base_scale = _base_scale(src_width, src_height, canvas_width, canvas_height, fit_mode)
    total_scale = max(0.01, base_scale * max(0.01, scale))
    scaled_width = max(1, round(src_width * total_scale))
    scaled_height = max(1, round(src_height * total_scale))
    interpolation = cv2.INTER_AREA if total_scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(rgba, (scaled_width, scaled_height), interpolation=interpolation)

    canvas = np.zeros((canvas_height, canvas_width, 4), dtype=np.float32)
    center_x = canvas_width * (0.5 + offset_x)
    center_y = canvas_height * (0.5 + offset_y)
    dest_x = round(center_x - scaled_width / 2.0)
    dest_y = round(center_y - scaled_height / 2.0)
    _paste_with_alpha(canvas, resized, dest_x, dest_y)

    frame_rgb = np.ascontiguousarray(canvas[:, :, :3])
    mask_rgb = np.repeat(canvas[:, :, 3:4], 3, axis=2)
    return frame_rgb, mask_rgb


def _base_scale(
    src_width: int,
    src_height: int,
    canvas_width: int,
    canvas_height: int,
    fit_mode: ImageFitMode,
) -> float:
    """Return the uniform scale factor ``fit_mode`` implies (excludes Stretch)."""
    if fit_mode == ImageFitMode.Native:
        return 1.0
    scale_x = canvas_width / max(1, src_width)
    scale_y = canvas_height / max(1, src_height)
    if fit_mode == ImageFitMode.Fill:
        return max(scale_x, scale_y)
    return min(scale_x, scale_y)  # Fit: contain within the canvas.


def _paste_with_alpha(canvas: np.ndarray, patch: np.ndarray, dest_x: int, dest_y: int) -> None:
    """Paste ``patch`` (HxWx4) onto ``canvas`` (HxWx4) at ``(dest_x, dest_y)``.

    Clips to the overlapping region so a patch placed partially or fully
    outside the canvas (via scale/offset) never raises on an out-of-range
    slice.
    """
    canvas_height, canvas_width = canvas.shape[:2]
    patch_height, patch_width = patch.shape[:2]

    src_x0 = max(0, -dest_x)
    src_y0 = max(0, -dest_y)
    dst_x0 = max(0, dest_x)
    dst_y0 = max(0, dest_y)
    copy_width = min(patch_width - src_x0, canvas_width - dst_x0)
    copy_height = min(patch_height - src_y0, canvas_height - dst_y0)
    if copy_width <= 0 or copy_height <= 0:
        return

    canvas[dst_y0 : dst_y0 + copy_height, dst_x0 : dst_x0 + copy_width] = patch[
        src_y0 : src_y0 + copy_height, src_x0 : src_x0 + copy_width
    ]
