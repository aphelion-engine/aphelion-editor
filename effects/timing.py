"""Time-based animated frame effects."""

from __future__ import annotations

import math

import numpy as np

from effects.frame_ops import ensure_rgb_f32


def film_flicker(
    frame: np.ndarray,
    *,
    intensity: float,
    speed: float,
    frame_num: int,
) -> np.ndarray:
    """Modulate exposure with pseudo-random flicker over time."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if intensity <= 1e-6:
        return source
    phase: float = frame_num * speed * 0.17
    noise: float = (
        math.sin(phase * 1.7)
        + math.sin(phase * 3.1 + 1.2) * 0.55
        + math.sin(phase * 5.3 + 2.4) * 0.25
    ) / 1.8
    gain: float = 1.0 - intensity * max(0.0, noise)
    return np.clip(source * gain, 0.0, 1.0).astype(np.float32, copy=False)


def strobe(
    frame: np.ndarray,
    *,
    rate: float,
    duty: float,
    frame_num: int,
) -> np.ndarray:
    """Gate visibility using a repeating on/off cycle."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if rate <= 1e-6:
        return source
    cycle: float = max(2.0, 60.0 / rate)
    position: float = (frame_num % cycle) / cycle
    if position <= max(0.05, min(0.95, duty)):
        return source
    return np.zeros_like(source)


def pulse_exposure(
    frame: np.ndarray,
    *,
    speed: float,
    amount: float,
    frame_num: int,
) -> np.ndarray:
    """Oscillate exposure with a smooth sine envelope."""
    source: np.ndarray = ensure_rgb_f32(frame)
    if amount <= 1e-6:
        return source
    wave: float = (math.sin(frame_num * speed * 0.12) + 1.0) * 0.5
    gain: float = 1.0 + amount * (wave - 0.5) * 2.0
    return np.clip(source * gain, 0.0, 1.0).astype(np.float32, copy=False)
