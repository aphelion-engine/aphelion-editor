"""Advanced color correction frame operations."""

from __future__ import annotations

import cv2
import numpy as np

from effects.frame_ops import ensure_rgb_f32


def levels(
    frame: np.ndarray,
    *,
    in_black: float,
    in_white: float,
    gamma: float,
    out_black: float,
    out_white: float,
) -> np.ndarray:
    """Remap input/output black/white points with a gamma curve."""
    source: np.ndarray = ensure_rgb_f32(frame)
    low_in: float = float(np.clip(in_black, 0.0, 0.98))
    high_in: float = float(np.clip(in_white, low_in + 0.02, 1.0))
    low_out: float = float(np.clip(out_black, 0.0, 0.98))
    high_out: float = float(np.clip(out_white, low_out + 0.02, 1.0))
    gamma_value: float = max(0.05, float(gamma))
    normalized: np.ndarray = np.clip(
        (source - low_in) / (high_in - low_in),
        0.0,
        1.0,
    )
    adjusted: np.ndarray = np.power(normalized, 1.0 / gamma_value)
    scaled: np.ndarray = low_out + adjusted * (high_out - low_out)
    return scaled.astype(np.float32, copy=False)


def vibrance(
    frame: np.ndarray,
    *,
    amount: float,
    protect_skin: bool,
) -> np.ndarray:
    """Boost low-saturation colors more than already saturated pixels."""
    source: np.ndarray = ensure_rgb_f32(frame)
    hsv: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2HSV)
    saturation: np.ndarray = hsv[:, :, 1]
    boost: np.ndarray = amount * (1.0 - saturation)
    if protect_skin:
        hue: np.ndarray = hsv[:, :, 0]
        skin_mask: np.ndarray = ((hue >= 0.0) & (hue <= 25.0)).astype(np.float32)
        boost *= 1.0 - skin_mask * 0.65
    hsv[:, :, 1] = np.clip(saturation * (1.0 + boost), 0.0, 1.0)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)


def shadows_highlights(
    frame: np.ndarray,
    *,
    shadows: float,
    highlights: float,
    balance: float,
) -> np.ndarray:
    """Lift shadows and compress highlights with a midtone pivot."""
    source: np.ndarray = ensure_rgb_f32(frame)
    luma: np.ndarray = (
        0.2126 * source[:, :, 0]
        + 0.7152 * source[:, :, 1]
        + 0.0722 * source[:, :, 2]
    )
    pivot: float = float(np.clip(0.5 + balance * 0.35, 0.15, 0.85))
    shadow_mask: np.ndarray = np.clip(1.0 - luma / pivot, 0.0, 1.0)
    highlight_mask: np.ndarray = np.clip((luma - pivot) / (1.0 - pivot), 0.0, 1.0)
    adjusted: np.ndarray = source + shadows * shadow_mask[..., None]
    adjusted -= highlights * highlight_mask[..., None]
    return np.clip(adjusted, 0.0, 1.0).astype(np.float32, copy=False)


def color_balance(
    frame: np.ndarray,
    *,
    cyan_red: float,
    magenta_green: float,
    yellow_blue: float,
    preserve_luma: bool,
) -> np.ndarray:
    """Shift RGB channels independently with optional luma preservation."""
    source: np.ndarray = ensure_rgb_f32(frame)
    offsets: np.ndarray = np.asarray(
        (cyan_red, magenta_green, yellow_blue),
        dtype=np.float32,
    ) * np.float32(64.0 / 255.0)
    shifted: np.ndarray = source + offsets.reshape(1, 1, 3)
    if preserve_luma:
        original_luma: np.ndarray = (
            0.2126 * source[:, :, 0]
            + 0.7152 * source[:, :, 1]
            + 0.0722 * source[:, :, 2]
        )
        new_luma: np.ndarray = (
            0.2126 * shifted[:, :, 0]
            + 0.7152 * shifted[:, :, 1]
            + 0.0722 * shifted[:, :, 2]
        )
        floor: float = 1.0 / 255.0
        scale: np.ndarray = np.divide(
            original_luma,
            np.maximum(new_luma, floor),
            out=np.ones_like(original_luma),
            where=new_luma > floor,
        )
        shifted *= scale[..., None]
    return np.clip(shifted, 0.0, 1.0).astype(np.float32, copy=False)


def clarity(
    frame: np.ndarray,
    *,
    amount: float,
) -> np.ndarray:
    """Apply midtone clarity via a large-radius unsharp mask on luma."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if abs(amount) <= 1e-6:
        return source
    blurred: np.ndarray = cv2.GaussianBlur(source, (0, 0), sigmaX=8.0, sigmaY=8.0)
    detail: np.ndarray = source - blurred
    return np.clip(source + detail * amount, 0.0, 1.0).astype(np.float32, copy=False)
