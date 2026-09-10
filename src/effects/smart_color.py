"""Statistical auto-correction and shot-matching color effects.

These are the "smart" operators: instead of asking the artist to dial in a
value, they analyze the incoming frame (histogram percentiles, channel
statistics) and apply an automatic correction. All of them expose a
``strength`` amount so the automatic result can be dialed back, and they
never mutate the source array.
"""

from __future__ import annotations

import cv2
import numpy as np
from core.nodes.enums import AutoBalanceMode
from effects.frame_ops import ensure_rgb_f32, resize_like

#: Channel/statistic floor that keeps ratios finite on flat or black frames.
_EPSILON: float = 1e-4


def auto_levels(
    frame: np.ndarray,
    *,
    clip_percent: float,
    strength: float,
    per_channel: bool,
) -> np.ndarray:
    """Stretch contrast by mapping histogram percentiles to black and white.

    ``clip_percent`` of the darkest and brightest pixels are ignored, so a
    single hot pixel cannot wreck the stretch. ``per_channel`` removes color
    casts (auto levels per channel) at the cost of shifting white balance.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    clip: float = float(np.clip(clip_percent, 0.0, 25.0)) / 100.0
    if per_channel:
        flat: np.ndarray = source.reshape(-1, 3)
        low: np.ndarray = np.quantile(flat, clip, axis=0).reshape(1, 1, 3)
        high: np.ndarray = np.quantile(flat, 1.0 - clip, axis=0).reshape(1, 1, 3)
    else:
        luma: np.ndarray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
        low = float(np.quantile(luma, clip))
        high = float(np.quantile(luma, 1.0 - clip))
    span: np.ndarray = np.maximum(high - low, _EPSILON)
    stretched: np.ndarray = (source - low) / span
    return _blend(source, stretched, strength)


def auto_white_balance(
    frame: np.ndarray,
    *,
    mode: AutoBalanceMode,
    strength: float,
) -> np.ndarray:
    """Neutralize a color cast from the frame's own channel statistics.

    ``GrayWorld`` assumes the average scene color is neutral; ``WhitePatch``
    scales the brightest percentile of each channel to a common level, which
    handles frames dominated by one color better.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    flat: np.ndarray = source.reshape(-1, 3)
    if mode == AutoBalanceMode.WhitePatch:
        reference: np.ndarray = np.quantile(flat, 0.99, axis=0)
    else:
        reference = flat.mean(axis=0)
    reference = np.maximum(reference.astype(np.float32), _EPSILON)
    target: float = float(reference.mean())
    gains: np.ndarray = (target / reference).reshape(1, 1, 3)
    balanced: np.ndarray = source * gains.astype(np.float32)
    return _blend(source, balanced, strength)


def shot_match(
    frame: np.ndarray,
    reference: np.ndarray,
    *,
    strength: float,
    match_luminance: bool,
) -> np.ndarray:
    """Match this frame's color statistics to a reference frame (shot matching).

    A per-channel mean/standard-deviation transfer is applied in CIELAB when
    ``match_luminance`` is on (so the two shots agree on contrast as well as
    hue) or in linear RGB when only the color cast should follow.
    """
    source: np.ndarray = ensure_rgb_f32(frame)
    target: np.ndarray = resize_like(ensure_rgb_f32(reference), source)
    if match_luminance:
        matched: np.ndarray = cv2.cvtColor(
            _transfer_statistics(
                cv2.cvtColor(source, cv2.COLOR_RGB2LAB),
                cv2.cvtColor(target, cv2.COLOR_RGB2LAB),
            ),
            cv2.COLOR_LAB2RGB,
        )
    else:
        matched = _transfer_statistics(source, target)
    return _blend(source, matched, strength)


def _transfer_statistics(source: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Rescale each channel of ``source`` toward ``reference`` mean/std."""
    output: np.ndarray = source.astype(np.float32, copy=True)
    channels: int = output.shape[2]
    for channel in range(channels):
        source_channel: np.ndarray = output[:, :, channel]
        reference_channel: np.ndarray = reference[:, :, channel]
        source_std: float = float(source_channel.std())
        reference_std: float = float(reference_channel.std())
        if source_std <= _EPSILON or reference_std <= _EPSILON:
            scale: float = 1.0
        else:
            scale = reference_std / source_std
        output[:, :, channel] = (
            (source_channel - float(source_channel.mean())) * scale
            + float(reference_channel.mean())
        )
    return output


def _blend(source: np.ndarray, corrected: np.ndarray, strength: float) -> np.ndarray:
    """Mix a corrected image back over the source by ``strength``."""
    amount: float = float(np.clip(strength, 0.0, 1.0))
    if amount <= 0.0:
        return source
    if amount >= 1.0:
        return corrected
    return source * np.float32(1.0 - amount) + corrected * np.float32(amount)
