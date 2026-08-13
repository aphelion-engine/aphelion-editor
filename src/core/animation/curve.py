"""A single animatable property's keyframe curve.

Mirrors the deliberately minimal animation model already used for roto
shapes (see ``core.roto.interpolation``): keyframes are linearly
interpolated between the nearest integer frames and held flat outside the
keyed range. There is no bezier/ease curve editor — this is the same
trade-off made for roto, applied to arbitrary numeric node properties so
tracked positions, corner-pins, and other numeric parameters can be
animated without inventing a second animation system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def interpolate_curve(keyframes: dict[int, float], frame: int) -> float:
    """Resolve a scalar curve's value at ``frame``.

    Parameters:
        keyframes: Map of integer frame number to the value keyed there.
        frame: The frame to resolve.

    Returns:
        The interpolated value. Held at the first/last keyframe outside the
        keyed range. ``0.0`` when there are no keyframes.
    """
    if not keyframes:
        return 0.0

    frame_numbers = sorted(keyframes.keys())
    if frame <= frame_numbers[0]:
        return keyframes[frame_numbers[0]]
    if frame >= frame_numbers[-1]:
        return keyframes[frame_numbers[-1]]

    lower = frame_numbers[0]
    upper = frame_numbers[-1]
    for candidate in frame_numbers:
        if candidate <= frame:
            lower = candidate
        if candidate >= frame:
            upper = candidate
            break

    if lower == upper:
        return keyframes[lower]

    t = (frame - lower) / (upper - lower)
    return keyframes[lower] + (keyframes[upper] - keyframes[lower]) * t


@dataclass
class AnimationCurve:
    """A property's keyframes, resolved per-frame via ``interpolate_curve``."""

    keyframes: dict[int, float] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when the curve has no keyframes (should be discarded)."""
        return not self.keyframes

    def value_at(self, frame: int) -> float:
        """Resolve this curve's value at ``frame``."""
        return interpolate_curve(self.keyframes, frame)

    def set_keyframe(self, frame: int, value: float) -> None:
        """Add or overwrite the keyframe at ``frame``."""
        self.keyframes[int(frame)] = float(value)

    def remove_keyframe(self, frame: int) -> None:
        """Remove the keyframe at ``frame`` if present."""
        self.keyframes.pop(int(frame), None)

    def has_keyframe_at(self, frame: int) -> bool:
        """True when ``frame`` has an explicit (not interpolated) keyframe."""
        return int(frame) in self.keyframes

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-native types (integer keys become strings)."""
        return {
            "keyframes": {
                str(frame_num): float(value)
                for frame_num, value in self.keyframes.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnimationCurve:
        """Restore a curve from a decoded document dict."""
        raw_keyframes = data.get("keyframes", {})
        keyframes: dict[int, float] = {}
        if isinstance(raw_keyframes, dict):
            for frame_key, raw_value in raw_keyframes.items():
                if not isinstance(raw_value, (int, float)):
                    continue
                try:
                    frame_num = int(frame_key)
                except (TypeError, ValueError):
                    continue
                keyframes[frame_num] = float(raw_value)
        return cls(keyframes=keyframes)
