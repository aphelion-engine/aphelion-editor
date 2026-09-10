"""Depth-map driven effects: defocus, atmosphere, relighting, and stereo.

Every operator here consumes a grayscale depth pass (bright = near) that can
come from a depth generator, a 3D render, or any luminance ramp. Depth is
resized to the beauty frame so the two inputs never have to match exactly.
"""

from __future__ import annotations

import cv2
import numpy as np
from core.nodes.base import ColorRgb
from core.nodes.enums import AnaglyphMode
from effects.filters import gaussian_blur
from effects.frame_ops import color01, ensure_rgb_f32, resize_like

_EPSILON: float = 1e-4


def depth_channel(depth: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Return a resized ``HxW`` float32 depth channel aligned to ``reference``."""
    aligned: np.ndarray = resize_like(ensure_rgb_f32(depth), reference)
    return cv2.cvtColor(aligned, cv2.COLOR_RGB2GRAY)


def depth_of_field(
    frame: np.ndarray,
    depth: np.ndarray,
    *,
    focus: float,
    focus_range: float,
    max_blur: float,
    invert: bool,
) -> np.ndarray:
    """Defocus pixels according to their distance from a focal plane.

    The circle of confusion grows linearly with depth error, and the whole
    frame is blended toward a wide Gaussian using that per-pixel amount — a
    cheap, stable approximation of a lens' bokeh.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    depths: np.ndarray = depth_channel(depth, source)
    if invert:
        depths = 1.0 - depths
    error: np.ndarray = np.abs(depths - float(focus)) / max(_EPSILON, focus_range)
    coc: np.ndarray = np.clip(error, 0.0, 1.0)
    # Square the ramp so the focal plane stays crisp noticeably longer.
    coc = coc * coc
    radius: int = max(1, int(round(max_blur)))
    blurred: np.ndarray = gaussian_blur(source, radius=radius, sigma=0.0)
    return source * (1.0 - coc[:, :, None]) + blurred * coc[:, :, None]


def depth_haze(
    frame: np.ndarray,
    depth: np.ndarray,
    *,
    near: float,
    far: float,
    color: ColorRgb,
    density: float,
    invert: bool,
) -> np.ndarray:
    """Fade distant pixels toward an atmospheric color."""
    source: np.ndarray = ensure_rgb_f32(frame)
    depths: np.ndarray = depth_channel(depth, source)
    if invert:
        depths = 1.0 - depths
    span: float = max(_EPSILON, float(far) - float(near))
    ramp: np.ndarray = np.clip((depths - float(near)) / span, 0.0, 1.0)
    amount: np.ndarray = (ramp * float(np.clip(density, 0.0, 1.0)))[:, :, None]
    haze: np.ndarray = color01(color).reshape(1, 1, 3)
    return source * (1.0 - amount) + haze * amount


def depth_relight(
    frame: np.ndarray,
    depth: np.ndarray,
    *,
    light_x: float,
    light_y: float,
    relief: float,
    strength: float,
    ambient: float,
    invert: bool,
) -> np.ndarray:
    """Relight the frame using normals derived from the depth map.

    ``relief`` controls how steep the recovered surface is: low values give
    a gentle glow, high values punch out hard facets. A flat depth map has no
    gradient and therefore leaves the frame untouched.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    depths: np.ndarray = depth_channel(depth, source)
    if invert:
        depths = 1.0 - depths
    gradient_x: np.ndarray = cv2.Sobel(depths, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y: np.ndarray = cv2.Sobel(depths, cv2.CV_32F, 0, 1, ksize=3)
    slope: float = float(np.clip(relief, 0.05, 20.0))
    normal_z: np.ndarray = np.full_like(depths, 1.0)
    normal: np.ndarray = np.dstack(
        [-gradient_x * slope, -gradient_y * slope, normal_z]
    )
    norm: np.ndarray = np.linalg.norm(normal, axis=2, keepdims=True)
    # A tight epsilon keeps the normalization from perturbing flat surfaces.
    normal = normal / (norm + 1e-6)

    light_x_clamped: float = float(np.clip(light_x, -1.0, 1.0))
    light_y_clamped: float = float(np.clip(light_y, -1.0, 1.0))
    horizontal: float = light_x_clamped * light_x_clamped
    vertical: float = light_y_clamped * light_y_clamped
    light_z: float = float(np.sqrt(max(0.05, 1.0 - horizontal - vertical)))
    light: np.ndarray = np.array(
        [light_x_clamped, light_y_clamped, light_z], dtype=np.float32
    )
    lambert: np.ndarray = np.clip(np.tensordot(normal, light, axes=([2], [0])), 0.0, 1.0)
    ambient_clamped: float = float(np.clip(ambient, 0.0, 1.0))
    # A flat surface has no gradient, so its lambert term is exactly the
    # light's z component; measuring deviation from that keeps untextured
    # regions neutral instead of brightening them on their own.
    shade: np.ndarray = 1.0 + (lambert - light_z) * (1.0 - ambient_clamped) * strength
    return source * shade[:, :, None].astype(np.float32)


def anaglyph(
    frame: np.ndarray,
    depth: np.ndarray,
    *,
    separation: float,
    mode: AnaglyphMode,
    invert: bool,
) -> np.ndarray:
    """Build a red/cyan style stereo anaglyph from a depth pass."""
    source: np.ndarray = ensure_rgb_f32(frame)
    depths: np.ndarray = depth_channel(depth, source)
    if invert:
        depths = 1.0 - depths
    height: int
    width: int
    height, width = source.shape[:2]
    pixels: np.ndarray = (depths - 0.5) * float(separation) * float(width)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    left: np.ndarray = cv2.remap(
        source,
        (xx + pixels).astype(np.float32),
        yy,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    right: np.ndarray = cv2.remap(
        source,
        (xx - pixels).astype(np.float32),
        yy,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    output: np.ndarray = np.empty_like(source)
    if mode == AnaglyphMode.GreenMagenta:
        output[:, :, 1] = left[:, :, 1]
        output[:, :, 0] = right[:, :, 0]
        output[:, :, 2] = right[:, :, 2]
    elif mode == AnaglyphMode.AmberBlue:
        output[:, :, 0] = left[:, :, 0]
        output[:, :, 1] = left[:, :, 1]
        output[:, :, 2] = right[:, :, 2]
    else:
        output[:, :, 0] = left[:, :, 0]
        output[:, :, 1] = right[:, :, 1]
        output[:, :, 2] = right[:, :, 2]
    return output


def depth_slice(
    depth: np.ndarray,
    *,
    near: float,
    far: float,
    softness: float,
    invert: bool,
) -> np.ndarray:
    """Return a soft RGB matte selecting the depth range ``[near, far]``."""
    source: np.ndarray = ensure_rgb_f32(depth)
    depths: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    low: float = float(near)
    high: float = float(far)
    if high < low:
        low, high = high, low
    soft: float = max(_EPSILON, float(softness))
    mask: np.ndarray = np.clip((depths - low) / soft, 0.0, 1.0) * np.clip(
        (high - depths) / soft, 0.0, 1.0
    )
    if invert:
        mask = 1.0 - mask
    return cv2.cvtColor(mask.astype(np.float32), cv2.COLOR_GRAY2RGB)
