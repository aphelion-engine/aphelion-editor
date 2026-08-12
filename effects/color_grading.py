"""Lift / gamma / gain color grading for RGB float32 frames.

Interactive-preview oriented: identity grades short-circuit, and active grades
use a fused float32 pass (no per-pixel ``np.power`` unless a gamma trim
is actually active).
"""

from __future__ import annotations

import numpy as np

_NEUTRAL_U8: int = 128
_NEUTRAL: float = 128.0 / 255.0
_EPS: float = 1e-6


def apply_color_grade(
    frame: np.ndarray,
    *,
    exposure: float,
    contrast: float,
    saturation: float,
    temperature: float,
    tint: float,
    lift_rgb: tuple[int, int, int],
    gamma_rgb: tuple[int, int, int],
    gain_rgb: tuple[int, int, int],
    amount: float,
) -> np.ndarray:
    """Apply a Resolve-style grade to an RGB float32 frame.

    Parameters:
        frame: HxWx3 ``float32`` RGB image in the ``[0, 1]`` pipeline contract.
        exposure: Exposure offset in stops (0 = unchanged).
        contrast: Contrast multiplier (1.0 = unchanged).
        saturation: Saturation multiplier (1.0 = unchanged).
        temperature: Warm/cool bias in ``[-1, 1]``.
        tint: Green/magenta bias in ``[-1, 1]``.
        lift_rgb: Shadow tint (128,128,128 = neutral, 0-255 UI units).
        gamma_rgb: Midtone tint (128,128,128 = neutral, 0-255 UI units).
        gain_rgb: Highlight tint (128,128,128 = neutral, 0-255 UI units).
        amount: Mix of graded result over original in ``[0, 1]``.

    Returns:
        Graded RGB ``float32`` frame (contiguous). Does not mutate ``frame``.
    """
    if frame.ndim != 3 or frame.shape[2] < 3:
        return frame

    amount_f = float(np.clip(amount, 0.0, 1.0))
    if amount_f <= _EPS or _is_identity_grade(
        exposure,
        contrast,
        saturation,
        temperature,
        tint,
        lift_rgb,
        gamma_rgb,
        gain_rgb,
    ):
        return np.ascontiguousarray(frame)

    scale = np.float32((2.0 ** float(exposure)) * float(contrast))
    bias = np.float32(0.5 - 0.5 * float(contrast))
    sat = np.float32(saturation)
    temp = np.float32(np.clip(temperature, -1.0, 1.0))
    green_magenta = np.float32(np.clip(tint, -1.0, 1.0))

    lift = _offset(lift_rgb)
    gamma = _offset(gamma_rgb)
    gain = _offset(gain_rgb)
    use_lgg = not _is_neutral_rgb(lift_rgb, gamma_rgb, gain_rgb)

    src = np.ascontiguousarray(frame[:, :, :3])
    work = src.astype(np.float32, copy=True)
    work *= scale
    work += bias

    if abs(float(temp)) > _EPS or abs(float(green_magenta)) > _EPS:
        work[:, :, 0] += temp * np.float32(0.08) - green_magenta * np.float32(0.03)
        work[:, :, 1] += green_magenta * np.float32(0.06)
        work[:, :, 2] += -temp * np.float32(0.08) - green_magenta * np.float32(0.03)

    luma = (
        work[:, :, 0] * np.float32(0.2126)
        + work[:, :, 1] * np.float32(0.7152)
        + work[:, :, 2] * np.float32(0.0722)
    )

    if use_lgg:
        shadow_w = (1.0 - luma)[..., None]
        highlight_w = luma[..., None]
        mid_w = (1.0 - np.abs(luma - 0.5) * 2.0)[..., None]
        work += lift * shadow_w
        work *= 1.0 + gain * highlight_w
        work += gamma * mid_w * work * np.float32(0.35)
        # Luma changes after LGG — recompute for saturation.
        luma = (
            work[:, :, 0] * np.float32(0.2126)
            + work[:, :, 1] * np.float32(0.7152)
            + work[:, :, 2] * np.float32(0.0722)
        )

    if abs(float(sat) - 1.0) > _EPS:
        luma_3 = luma[..., None]
        work -= luma_3
        work *= sat
        work += luma_3

    np.clip(work, 0.0, 1.0, out=work)

    if amount_f < 1.0 - _EPS:
        mix = np.float32(amount_f)
        inv = np.float32(1.0 - amount_f)
        work *= mix
        work += src * inv

    out = np.empty_like(frame)
    out[:, :, :3] = work
    if frame.shape[2] > 3:
        out[:, :, 3:] = frame[:, :, 3:]
    return np.ascontiguousarray(out)


def _is_neutral_rgb(
    lift_rgb: tuple[int, int, int],
    gamma_rgb: tuple[int, int, int],
    gain_rgb: tuple[int, int, int],
) -> bool:
    neutral = (_NEUTRAL_U8, _NEUTRAL_U8, _NEUTRAL_U8)
    return lift_rgb == neutral and gamma_rgb == neutral and gain_rgb == neutral


def _is_identity_grade(
    exposure: float,
    contrast: float,
    saturation: float,
    temperature: float,
    tint: float,
    lift_rgb: tuple[int, int, int],
    gamma_rgb: tuple[int, int, int],
    gain_rgb: tuple[int, int, int],
) -> bool:
    return (
        abs(exposure) <= _EPS
        and abs(contrast - 1.0) <= _EPS
        and abs(saturation - 1.0) <= _EPS
        and abs(temperature) <= _EPS
        and abs(tint) <= _EPS
        and _is_neutral_rgb(lift_rgb, gamma_rgb, gain_rgb)
    )


def _offset(rgb: tuple[int, int, int]) -> np.ndarray:
    return (
        np.asarray(rgb, dtype=np.float32) * np.float32(1.0 / 255.0)
        - np.float32(_NEUTRAL)
    ).reshape(1, 1, 3)
