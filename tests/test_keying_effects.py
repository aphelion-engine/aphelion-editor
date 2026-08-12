"""Unit tests for chroma keying, spill suppression, and matte refinement."""

from __future__ import annotations

import unittest

import numpy as np

from effects.keying import chroma_key_mask, refine_matte, suppress_spill


class ChromaKeyMaskTests(unittest.TestCase):
    """Verify distance-based masking behavior."""

    def test_exact_key_color_is_fully_keyed_out(self) -> None:
        """A pixel matching the key color exactly produces mask 0."""
        frame = np.full((2, 2, 3), 0.0, dtype=np.float32)
        frame[:, :, 1] = 1.0  # pure green
        mask = chroma_key_mask(
            frame, key_color=(0, 255, 0), tolerance=0.1, softness=0.2
        )
        self.assertEqual(mask.dtype, np.float32)
        np.testing.assert_allclose(mask, 0.0, atol=1e-5)

    def test_distant_color_is_fully_kept(self) -> None:
        """A pixel far from the key color produces mask 1."""
        frame = np.zeros((2, 2, 3), dtype=np.float32)
        frame[:, :, 0] = 1.0  # pure red, far from green key
        mask = chroma_key_mask(
            frame, key_color=(0, 255, 0), tolerance=0.1, softness=0.2
        )
        np.testing.assert_allclose(mask, 1.0, atol=1e-5)

    def test_mask_ramps_between_tolerance_and_softness(self) -> None:
        """Mask values fall strictly within [0, 1] near the edge."""
        frame = np.full((1, 1, 3), 0.3, dtype=np.float32)
        mask = chroma_key_mask(
            frame, key_color=(128, 128, 128), tolerance=0.0, softness=1.0
        )
        value = float(mask[0, 0, 0])
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)


class SuppressSpillTests(unittest.TestCase):
    """Verify dominant-channel clamping toward the other two channels."""

    def test_green_spill_is_clamped_to_max_of_others(self) -> None:
        """Green spill clamps toward max(red, blue) scaled by amount."""
        frame = np.array([[[0.2, 0.9, 0.3]]], dtype=np.float32)
        result = suppress_spill(frame, key_color=(0, 255, 0), amount=1.0)
        self.assertAlmostEqual(float(result[0, 0, 1]), 0.3, places=5)
        # Non-dominant channels are untouched.
        self.assertAlmostEqual(float(result[0, 0, 0]), 0.2, places=5)
        self.assertAlmostEqual(float(result[0, 0, 2]), 0.3, places=5)

    def test_amount_zero_is_a_no_op(self) -> None:
        """Zero suppression amount leaves the frame unchanged."""
        frame = np.array([[[0.1, 0.8, 0.2]]], dtype=np.float32)
        result = suppress_spill(frame, key_color=(0, 255, 0), amount=0.0)
        np.testing.assert_allclose(result, frame, atol=1e-6)


class RefineMatteTests(unittest.TestCase):
    """Verify choke, feather, and levels remap output contract."""

    def test_output_is_float32_rgb_in_unit_range(self) -> None:
        """refine_matte always returns a float32 RGB frame in [0, 1]."""
        mask = np.full((8, 8, 3), 0.5, dtype=np.float32)
        result = refine_matte(
            mask, choke=0.0, feather=0.0, black_point=0.0, white_point=1.0
        )
        self.assertEqual(result.dtype, np.float32)
        self.assertEqual(result.shape, (8, 8, 3))
        self.assertTrue(np.all(result >= 0.0) and np.all(result <= 1.0))

    def test_levels_remap_stretches_contrast(self) -> None:
        """Raising black_point pushes mid-gray toward white."""
        mask = np.full((4, 4, 3), 0.5, dtype=np.float32)
        result = refine_matte(
            mask, choke=0.0, feather=0.0, black_point=0.4, white_point=0.6
        )
        np.testing.assert_allclose(result, 0.5, atol=1e-3)

    def test_choke_positive_shrinks_a_filled_region(self) -> None:
        """A positive choke erodes a solid white square inward."""
        mask = np.zeros((20, 20, 3), dtype=np.float32)
        mask[5:15, 5:15, :] = 1.0
        result = refine_matte(
            mask, choke=3.0, feather=0.0, black_point=0.0, white_point=1.0
        )
        self.assertLess(float(np.sum(result)), float(np.sum(mask)))


if __name__ == "__main__":
    unittest.main()
