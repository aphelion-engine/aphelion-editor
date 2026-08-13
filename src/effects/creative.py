"""Creative stylized frame effects."""

from __future__ import annotations

import math

import cv2
import numpy as np

from core.nodes.enums import MirrorAxis
from effects.frame_ops import ensure_rgb_f32


def transform_3d(
    frame: np.ndarray,
    *,
    yaw_degrees: float,
    pitch_degrees: float,
    roll_degrees: float,
    perspective: float,
    fov_degrees: float,
) -> np.ndarray:
    """Simulate a 3D card transform with perspective projection."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    corners: np.ndarray = np.float32(
        [[0.0, 0.0], [float(width), 0.0], [float(width), float(height)], [0.0, float(height)]]
    )
    center: np.ndarray = np.array([width * 0.5, height * 0.5], dtype=np.float32)
    transformed: np.ndarray = _rotate_corners(
        corners - center,
        yaw_degrees=yaw_degrees,
        pitch_degrees=pitch_degrees,
        roll_degrees=roll_degrees,
        perspective=perspective,
        fov_degrees=fov_degrees,
    )
    transformed += center
    matrix: np.ndarray = cv2.getPerspectiveTransform(corners, transformed)
    return cv2.warpPerspective(
        source,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0.0, 0.0, 0.0),
    )


def kaleidoscope(
    frame: np.ndarray,
    *,
    segments: int,
    rotation_degrees: float,
    center_x: float,
    center_y: float,
) -> np.ndarray:
    """Mirror segments around a radial center."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    count: int = max(2, min(segments, 24))
    cx: float = float(np.clip(center_x, 0.0, 1.0)) * width
    cy: float = float(np.clip(center_y, 0.0, 1.0)) * height
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dx: np.ndarray = xx - cx
    dy: np.ndarray = yy - cy
    angle: np.ndarray = np.arctan2(dy, dx) + math.radians(rotation_degrees)
    radius: np.ndarray = np.sqrt(dx * dx + dy * dy)
    wedge: float = (2.0 * math.pi) / float(count)
    angle = np.abs(((angle + wedge * 0.5) % wedge) - wedge * 0.5)
    map_x: np.ndarray = (cx + radius * np.cos(angle)).astype(np.float32)
    map_y: np.ndarray = (cy + radius * np.sin(angle)).astype(np.float32)
    return cv2.remap(
        source,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def mirror(
    frame: np.ndarray,
    *,
    axis: MirrorAxis,
    offset: float,
) -> np.ndarray:
    """Mirror half the frame across a movable axis."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    offset_clamped: float = float(np.clip(offset, 0.0, 1.0))
    if axis == MirrorAxis.Horizontal:
        split: int = max(1, min(width - 1, round(width * offset_clamped)))
        left: np.ndarray = source[:, :split]
        mirrored: np.ndarray = np.fliplr(left)
        output: np.ndarray = source.copy()
        output[:, split:] = cv2.resize(mirrored, (width - split, height))
        return output
    split_row: int = max(1, min(height - 1, round(height * offset_clamped)))
    top: np.ndarray = source[:split_row, :]
    mirrored_rows: np.ndarray = np.flipud(top)
    output = source.copy()
    output[split_row:, :] = cv2.resize(mirrored_rows, (width, height - split_row))
    return output


def lens_distortion(
    frame: np.ndarray,
    *,
    strength: float,
    barrel: bool,
) -> np.ndarray:
    """Apply barrel or pincushion radial distortion."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    fx: float = float(width)
    fy: float = float(height)
    cx: float = width * 0.5
    cy: float = height * 0.5
    k1: float = strength if barrel else -strength
    camera: np.ndarray = np.array(
        [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist: np.ndarray = np.array([k1, 0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    return cv2.undistort(source, camera, dist)


def chromatic_aberration(
    frame: np.ndarray,
    *,
    amount: float,
    angle_degrees: float,
) -> np.ndarray:
    """Shift red and blue channels in opposite directions."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    radians: float = math.radians(angle_degrees)
    shift_x: float = math.cos(radians) * amount * width * 0.02
    shift_y: float = math.sin(radians) * amount * height * 0.02
    red: np.ndarray = _shift_channel(source[:, :, 0], shift_x, shift_y)
    blue: np.ndarray = _shift_channel(source[:, :, 2], -shift_x, -shift_y)
    merged: np.ndarray = source.copy()
    merged[:, :, 0] = red
    merged[:, :, 2] = blue
    return merged


def rgb_split(
    frame: np.ndarray,
    *,
    red_x: float,
    red_y: float,
    green_x: float,
    green_y: float,
    blue_x: float,
    blue_y: float,
) -> np.ndarray:
    """Offset each RGB channel independently."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    output: np.ndarray = source.copy()
    output[:, :, 0] = _shift_channel(source[:, :, 0], red_x * width * 0.02, red_y * height * 0.02)
    output[:, :, 1] = _shift_channel(
        source[:, :, 1], green_x * width * 0.02, green_y * height * 0.02
    )
    output[:, :, 2] = _shift_channel(
        source[:, :, 2], blue_x * width * 0.02, blue_y * height * 0.02
    )
    return output


def glitch(
    frame: np.ndarray,
    *,
    amount: float,
    block_size: int,
    seed: int,
) -> np.ndarray:
    """Block displacement and channel tearing."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if amount <= 1e-6:
        return source
    height: int
    width: int
    height, width = source.shape[:2]
    rng: np.random.Generator = np.random.default_rng(seed)
    output: np.ndarray = source.copy()
    block: int = max(4, block_size)
    rows: int = max(1, height // block)
    for row in range(rows):
        if rng.random() > amount:
            continue
        y0: int = row * block
        y1: int = min(height, y0 + block)
        shift: int = int(rng.integers(-width // 8, width // 8))
        slice_row: np.ndarray = output[y0:y1]
        output[y0:y1] = np.roll(slice_row, shift, axis=1)
    channel: int = int(rng.integers(0, 3))
    channel_shift: int = int(rng.integers(-20, 20))
    output[:, :, channel] = np.roll(output[:, :, channel], channel_shift, axis=1)
    return output


def ripple(
    frame: np.ndarray,
    *,
    amplitude: float,
    frequency: float,
    phase: float,
    frame_num: int,
) -> np.ndarray:
    """Apply a sinusoidal displacement field."""
    source: np.ndarray = ensure_rgb_f32(frame)
    height: int
    width: int
    height, width = source.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    wave: np.ndarray = np.sin(
        (yy / max(1.0, height)) * frequency * math.tau
        + phase
        + frame_num * 0.15
    )
    map_x: np.ndarray = xx + wave * amplitude * width * 0.04
    map_y: np.ndarray = yy + wave * amplitude * height * 0.02
    return cv2.remap(
        source,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _shift_channel(channel: np.ndarray, shift_x: float, shift_y: float) -> np.ndarray:
    """Translate a single channel with zero border fill."""
    matrix: np.ndarray = np.float32([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]])
    return cv2.warpAffine(
        channel,
        matrix,
        (channel.shape[1], channel.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0.0,
    )


def _rotate_corners(
    corners: np.ndarray,
    *,
    yaw_degrees: float,
    pitch_degrees: float,
    roll_degrees: float,
    perspective: float,
    fov_degrees: float,
) -> np.ndarray:
    """Project 3D corner offsets back to 2D."""
    yaw: float = math.radians(yaw_degrees)
    pitch: float = math.radians(pitch_degrees)
    roll: float = math.radians(roll_degrees)
    fov_scale: float = max(0.2, fov_degrees / 90.0)
    depth: float = 400.0 * fov_scale
    rotated: list[np.ndarray] = []
    for point in corners:
        x, y = float(point[0]), float(point[1])
        z: float = 0.0
        x, z = _rotate_pair(x, z, yaw)
        y, z = _rotate_pair(y, z, pitch)
        x, y = _rotate_pair(x, y, roll)
        z += perspective * 120.0
        scale: float = depth / max(1.0, depth + z)
        rotated.append(np.array([x * scale, y * scale], dtype=np.float32))
    return np.stack(rotated, axis=0)


def _rotate_pair(a: float, b: float, radians: float) -> tuple[float, float]:
    """Rotate a 2D pair."""
    cos_value: float = math.cos(radians)
    sin_value: float = math.sin(radians)
    return a * cos_value - b * sin_value, a * sin_value + b * cos_value
