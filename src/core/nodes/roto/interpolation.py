"""Minimal keyframe interpolation for roto point animation.

There is intentionally no general-purpose curve/easing system here: shapes
are linearly interpolated between the nearest integer-frame keys and held
flat at the ends of the keyed range. See the plan's scope notes for why.
"""

from __future__ import annotations

from core.nodes.roto.model import RotoPoint


def interpolate_points(
    keyframes: dict[int, list[RotoPoint]],
    frame: int,
) -> list[RotoPoint]:
    """Resolve a shape's point list at ``frame``.

    Parameters:
        keyframes: Map of integer frame number to the point list keyed there.
        frame: The frame to resolve.

    Returns:
        The interpolated point list. Held at the first/last keyframe outside
        the keyed range. Empty when there are no keyframes. Mismatched point
        counts between the surrounding keys fall back to holding the lower
        key's points rather than raising (keeps editing that changes point
        counts mid-timeline recoverable instead of a hard failure).
    """
    if not keyframes:
        return []

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

    lower_points = keyframes[lower]
    upper_points = keyframes[upper]
    if len(lower_points) != len(upper_points) or not lower_points:
        return lower_points

    t = (frame - lower) / (upper - lower)
    return [
        RotoPoint(x=a.x + (b.x - a.x) * t, y=a.y + (b.y - a.y) * t)
        for a, b in zip(lower_points, upper_points)
    ]
