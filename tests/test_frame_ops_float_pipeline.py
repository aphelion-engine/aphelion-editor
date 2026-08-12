"""Regression tests for the float32 frame pipeline contract."""

from __future__ import annotations

import unittest

import numpy as np

from core.nodes.enums import BlendMode
from effects.color_adjustments import exposure_contrast
from effects.compositing import blend_frames
from effects.frame_ops import color01, ensure_rgb_f32, from_source_u8, to_display_u8
from effects.generators import solid_color


class FrameOpsConversionTests(unittest.TestCase):
    """Verify the uint8 <-> float32 conversion boundary is stable."""

    def test_from_source_u8_maps_full_range_to_zero_one(self) -> None:
        """0 and 255 map to the domain endpoints exactly."""
        source: np.ndarray = np.array([[[0, 128, 255]]], dtype=np.uint8)
        converted: np.ndarray = from_source_u8(source)
        self.assertEqual(converted.dtype, np.float32)
        self.assertAlmostEqual(float(converted[0, 0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(converted[0, 0, 2]), 1.0, places=6)

    def test_round_trip_u8_to_f32_to_u8_is_stable(self) -> None:
        """Every 8-bit level survives a round trip through the float pipeline."""
        levels: np.ndarray = np.arange(256, dtype=np.uint8).reshape(1, 256, 1)
        levels_rgb: np.ndarray = np.repeat(levels, 3, axis=2)
        round_tripped: np.ndarray = to_display_u8(from_source_u8(levels_rgb))
        np.testing.assert_array_equal(round_tripped, levels_rgb)

    def test_to_display_u8_clamps_headroom(self) -> None:
        """Values above 1.0 or below 0.0 clamp instead of wrapping."""
        frame: np.ndarray = np.array([[[1.5, -0.5, 0.5]]], dtype=np.float32)
        result: np.ndarray = to_display_u8(frame)
        self.assertEqual(result[0, 0, 0], 255)
        self.assertEqual(result[0, 0, 1], 0)
        self.assertEqual(result[0, 0, 2], 128)

    def test_ensure_rgb_f32_drops_alpha_and_expands_gray(self) -> None:
        """Shape normalization matches the RGB contract regardless of input."""
        rgba: np.ndarray = np.zeros((4, 4, 4), dtype=np.float32)
        gray: np.ndarray = np.zeros((4, 4), dtype=np.float32)
        self.assertEqual(ensure_rgb_f32(rgba).shape, (4, 4, 3))
        self.assertEqual(ensure_rgb_f32(gray).shape, (4, 4, 3))

    def test_color01_converts_ui_color_to_unit_range(self) -> None:
        """A 0-255 UI color tuple maps to a float32 (3,) array in [0, 1]."""
        converted: np.ndarray = color01((0, 128, 255))
        self.assertEqual(converted.dtype, np.float32)
        self.assertAlmostEqual(float(converted[0]), 0.0, places=6)
        self.assertAlmostEqual(float(converted[2]), 1.0, places=6)


class EffectsFloatContractTests(unittest.TestCase):
    """Smoke-test representative effects for dtype/shape/range correctness."""

    def test_solid_color_generator_is_float32_in_unit_range(self) -> None:
        """Generators build frames directly in the float32 pipeline contract."""
        frame: np.ndarray = solid_color(4, 4, (64, 128, 255))
        self.assertEqual(frame.dtype, np.float32)
        self.assertTrue(np.all(frame >= 0.0) and np.all(frame <= 1.0))
        np.testing.assert_allclose(frame[0, 0], color01((64, 128, 255)), atol=1e-6)

    def test_blend_multiply_matches_direct_float_math(self) -> None:
        """Multiply blend equals a*b with no uint8 saturation artifacts."""
        background: np.ndarray = np.full((2, 2, 3), 0.5, dtype=np.float32)
        foreground: np.ndarray = np.full((2, 2, 3), 0.5, dtype=np.float32)
        blended: np.ndarray = blend_frames(
            background, foreground, mode=BlendMode.Multiply, opacity=1.0
        )
        self.assertEqual(blended.dtype, np.float32)
        np.testing.assert_allclose(blended, 0.25, atol=1e-6)

    def test_exposure_contrast_gain_is_linear_in_float_domain(self) -> None:
        """A one-stop exposure boost doubles the signal before clamping."""
        source: np.ndarray = np.full((2, 2, 3), 0.25, dtype=np.float32)
        result: np.ndarray = exposure_contrast(
            source, exposure=1.0, brightness=0.0, contrast=1.0
        )
        self.assertEqual(result.dtype, np.float32)
        np.testing.assert_allclose(result, 0.5, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
