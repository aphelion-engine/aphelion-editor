"""Unit tests for roto keyframe interpolation."""

from __future__ import annotations

import unittest

from core.roto.interpolation import interpolate_points
from core.roto.model import RotoPoint


class InterpolatePointsTests(unittest.TestCase):
    """Verify linear interpolation and end-of-range holding."""

    def test_empty_keyframes_returns_empty_list(self) -> None:
        """No keyframes means no points."""
        self.assertEqual(interpolate_points({}, 5), [])

    def test_single_keyframe_holds_at_every_frame(self) -> None:
        """A single keyframe is returned unchanged for any requested frame."""
        points = [RotoPoint(x=0.1, y=0.2)]
        keyframes = {10: points}
        self.assertEqual(interpolate_points(keyframes, 0), points)
        self.assertEqual(interpolate_points(keyframes, 10), points)
        self.assertEqual(interpolate_points(keyframes, 999), points)

    def test_holds_before_first_and_after_last_key(self) -> None:
        """Frames outside the keyed range hold at the nearest end."""
        first = [RotoPoint(x=0.0, y=0.0)]
        last = [RotoPoint(x=1.0, y=1.0)]
        keyframes = {0: first, 10: last}
        self.assertEqual(interpolate_points(keyframes, -5), first)
        self.assertEqual(interpolate_points(keyframes, 50), last)

    def test_linear_interpolation_at_midpoint(self) -> None:
        """A point halfway between two keys lands at the midpoint."""
        keyframes = {
            0: [RotoPoint(x=0.0, y=0.0)],
            10: [RotoPoint(x=1.0, y=0.5)],
        }
        result = interpolate_points(keyframes, 5)
        self.assertAlmostEqual(result[0].x, 0.5, places=6)
        self.assertAlmostEqual(result[0].y, 0.25, places=6)

    def test_exact_keyframe_frame_returns_that_keys_points(self) -> None:
        """Requesting a frame exactly on a key returns its points unchanged."""
        mid_points = [RotoPoint(x=0.5, y=0.5)]
        keyframes = {
            0: [RotoPoint(x=0.0, y=0.0)],
            5: mid_points,
            10: [RotoPoint(x=1.0, y=1.0)],
        }
        self.assertEqual(interpolate_points(keyframes, 5), mid_points)

    def test_mismatched_point_counts_hold_lower_key(self) -> None:
        """Differing point counts between surrounding keys fall back safely."""
        keyframes = {
            0: [RotoPoint(x=0.0, y=0.0)],
            10: [RotoPoint(x=1.0, y=1.0), RotoPoint(x=0.5, y=0.5)],
        }
        result = interpolate_points(keyframes, 5)
        self.assertEqual(result, keyframes[0])


if __name__ == "__main__":
    unittest.main()
