"""Tests for the new professional VFX effects and their node wrappers."""

from __future__ import annotations

import unittest

import core.nodes  # noqa: F401  (import order: effects depend on core.nodes)
import numpy as np
from core.nodes.base import NodeSocketType
from core.nodes.creative_nodes import (DuotoneNode, NeonGlowNode,
                                       PixelSortNode, ShockwaveNode)
from core.nodes.depth_nodes import (Anaglyph3DNode, DepthHazeNode,
                                    DepthOfFieldNode, DepthRelightNode,
                                    DepthSliceNode)
from core.nodes.distort_nodes import BendNode, BumpMapNode, OffsetNode
from core.nodes.enums import (AnaglyphMode, AutoBalanceMode, BendAxis,
                              PixelSortMode)
from core.nodes.logic_nodes import (CompareNode, LogicGateNode, OscillatorNode,
                                    RandomNode, RangeCheckNode, SelectNode,
                                    SmoothStepNode)
from core.nodes.smart_color_nodes import (AutoLevelsNode, AutoWhiteBalanceNode,
                                          ShotMatchNode)
from effects.creative import duotone, neon_glow, pixel_sort, shockwave
from effects.depth import (anaglyph, depth_haze, depth_of_field, depth_relight,
                           depth_slice)
from effects.distort import bend, bump_map, offset
from effects.smart_color import auto_levels, auto_white_balance, shot_match

NEW_NODE_CLASSES = (
    PixelSortNode,
    DuotoneNode,
    NeonGlowNode,
    ShockwaveNode,
    AutoLevelsNode,
    AutoWhiteBalanceNode,
    ShotMatchNode,
    DepthOfFieldNode,
    DepthHazeNode,
    DepthRelightNode,
    Anaglyph3DNode,
    DepthSliceNode,
    BendNode,
    BumpMapNode,
    OffsetNode,
    CompareNode,
    LogicGateNode,
    SelectNode,
    RangeCheckNode,
    SmoothStepNode,
    OscillatorNode,
    RandomNode,
)


def _frame(height: int = 8, width: int = 8, value: float = 0.5) -> np.ndarray:
    """Return a constant float32 RGB test frame."""
    return np.full((height, width, 3), value, dtype=np.float32)


def _depth_ramp(height: int = 8, width: int = 8) -> np.ndarray:
    """Return a horizontal 0-1 depth ramp replicated across channels."""
    ramp = np.linspace(0.0, 1.0, width, dtype=np.float32)
    ramp = np.tile(ramp, (height, 1))
    return np.dstack([ramp, ramp, ramp])


class CreativeEffectTests(unittest.TestCase):
    """Verify the new creative image operators."""

    def test_pixel_sort_orders_a_contiguous_run(self) -> None:
        frame = np.zeros((1, 8, 3), dtype=np.float32)
        values = [0.6, 0.9, 0.8, 0.7, 0.5, 0.4, 0.3, 0.2]
        frame[0, :, :] = np.array(values, dtype=np.float32)[:, None]
        result = pixel_sort(
            frame,
            mode=PixelSortMode.Luminance,
            threshold=0.55,
            max_length=64,
            reverse=False,
        )
        np.testing.assert_allclose(
            result[0, :4, 0],
            np.array([0.6, 0.7, 0.8, 0.9], dtype=np.float32),
            atol=1e-5,
        )

    def test_pixel_sort_reverse_orders_descending(self) -> None:
        frame = np.zeros((1, 4, 3), dtype=np.float32)
        frame[0, :, :] = np.array([0.6, 0.7, 0.8, 0.9], dtype=np.float32)[:, None]
        result = pixel_sort(
            frame,
            mode=PixelSortMode.Luminance,
            threshold=0.5,
            max_length=64,
            reverse=True,
        )
        self.assertGreater(float(result[0, 0, 0]), float(result[0, 3, 0]))

    def test_duotone_maps_shadows_and_highlights(self) -> None:
        frame = np.zeros((1, 2, 3), dtype=np.float32)
        frame[0, 1, :] = 1.0
        result = duotone(frame, dark=(0, 0, 0), light=(255, 255, 255))
        np.testing.assert_allclose(result[0, 0], [0.0, 0.0, 0.0], atol=1e-5)
        np.testing.assert_allclose(result[0, 1], [1.0, 1.0, 1.0], atol=1e-5)

    def test_neon_glow_darkens_a_flat_frame(self) -> None:
        result = neon_glow(
            _frame(value=0.5),
            color=(0, 255, 0),
            threshold=60,
            radius=4.0,
            intensity=2.0,
            background=0.0,
        )
        np.testing.assert_allclose(result, 0.0, atol=1e-6)

    def test_shockwave_zero_amplitude_is_identity(self) -> None:
        frame = _depth_ramp()
        result = shockwave(
            frame,
            progress=0.5,
            amplitude=0.0,
            wavelength=0.25,
            center_x=0.5,
            center_y=0.5,
        )
        np.testing.assert_allclose(result, frame, atol=1e-6)


class SmartColorEffectTests(unittest.TestCase):
    """Verify automatic and reference-driven color correction."""

    def test_auto_levels_expands_low_contrast(self) -> None:
        frame = np.full((4, 4, 3), 0.4, dtype=np.float32)
        frame[:2] = 0.6
        result = auto_levels(frame, clip_percent=0.0, strength=1.0, per_channel=False)
        self.assertLess(float(result.min()), 0.05)
        self.assertGreater(float(result.max()), 0.95)

    def test_auto_levels_zero_strength_is_identity(self) -> None:
        frame = _depth_ramp()
        result = auto_levels(frame, clip_percent=5.0, strength=0.0, per_channel=True)
        np.testing.assert_allclose(result, frame, atol=1e-6)

    def test_auto_white_balance_neutralizes_a_cast(self) -> None:
        frame = np.zeros((4, 4, 3), dtype=np.float32)
        frame[..., 0] = 0.6
        frame[..., 1] = 0.4
        frame[..., 2] = 0.4
        result = auto_white_balance(
            frame, mode=AutoBalanceMode.GrayWorld, strength=1.0
        )
        means = result.reshape(-1, 3).mean(axis=0)
        np.testing.assert_allclose(means[0], means[1], atol=1e-5)
        np.testing.assert_allclose(means[1], means[2], atol=1e-5)

    def test_shot_match_transfers_reference_mean(self) -> None:
        source = _frame(value=0.5)
        reference = _frame(value=0.2)
        result = shot_match(
            source,
            reference,
            strength=1.0,
            match_luminance=False,
        )
        self.assertAlmostEqual(float(result.mean()), 0.2, places=4)

    def test_shot_match_zero_strength_is_identity(self) -> None:
        source = _depth_ramp()
        result = shot_match(
            source,
            _frame(value=0.9),
            strength=0.0,
            match_luminance=True,
        )
        np.testing.assert_allclose(result, source, atol=1e-6)


class DepthEffectTests(unittest.TestCase):
    """Verify depth-driven defocus, atmosphere, relighting, and stereo."""

    def test_depth_of_field_is_sharp_at_focus(self) -> None:
        frame = _depth_ramp()
        depth = _frame(value=0.5)
        result = depth_of_field(
            frame,
            depth,
            focus=0.5,
            focus_range=0.25,
            max_blur=8.0,
            invert=False,
        )
        np.testing.assert_allclose(result, frame, atol=1e-6)

    def test_depth_of_field_blurs_out_of_focus(self) -> None:
        height = width = 16
        frame = np.zeros((height, width, 3), dtype=np.float32)
        frame[::2, ::2] = 1.0
        depth = _frame(height, width, value=1.0)
        result = depth_of_field(
            frame,
            depth,
            focus=0.0,
            focus_range=1.0,
            max_blur=8.0,
            invert=False,
        )
        self.assertLess(float(result.std()), float(frame.std()))

    def test_depth_haze_fades_distant_pixels(self) -> None:
        frame = _frame(value=0.8)
        depth = _frame(value=1.0)
        result = depth_haze(
            frame,
            depth,
            near=0.0,
            far=1.0,
            color=(0, 0, 0),
            density=1.0,
            invert=False,
        )
        np.testing.assert_allclose(result, 0.0, atol=1e-6)

    def test_depth_relight_leaves_flat_depth_unchanged(self) -> None:
        frame = _depth_ramp()
        depth = _frame(value=0.5)
        result = depth_relight(
            frame,
            depth,
            light_x=-0.5,
            light_y=-0.5,
            relief=3.0,
            strength=1.0,
            ambient=0.2,
            invert=False,
        )
        np.testing.assert_allclose(result, frame, atol=1e-5)

    def test_depth_relight_shades_a_sloped_surface(self) -> None:
        frame = _frame(value=0.5)
        depth = _depth_ramp()
        result = depth_relight(
            frame,
            depth,
            light_x=-0.7,
            light_y=0.0,
            relief=3.0,
            strength=1.0,
            ambient=0.2,
            invert=False,
        )
        self.assertFalse(np.allclose(result, frame))

    def test_anaglyph_matches_source_for_flat_depth(self) -> None:
        frame = _depth_ramp()
        depth = _frame(value=0.5)
        for mode in AnaglyphMode:
            with self.subTest(mode=mode):
                result = anaglyph(
                    frame,
                    depth,
                    separation=0.04,
                    mode=mode,
                    invert=False,
                )
                np.testing.assert_allclose(result, frame, atol=1e-5)

    def test_depth_slice_selects_the_range(self) -> None:
        depth = np.zeros((1, 4, 3), dtype=np.float32)
        depth[0, :, :] = np.array([0.0, 0.25, 0.75, 1.0], dtype=np.float32)[:, None]
        result = depth_slice(
            depth,
            near=0.1,
            far=0.6,
            softness=0.01,
            invert=False,
        )
        np.testing.assert_allclose(
            result[0, :, 0],
            np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
            atol=1e-4,
        )


class ManipulationEffectTests(unittest.TestCase):
    """Verify the new geometric manipulation operators."""

    def test_bend_zero_is_identity(self) -> None:
        frame = _depth_ramp()
        result = bend(frame, amount=0.0, axis=BendAxis.Horizontal)
        np.testing.assert_allclose(result, frame, atol=1e-6)

    def test_bend_displaces_pixels(self) -> None:
        frame = _depth_ramp()
        result = bend(frame, amount=0.3, axis=BendAxis.Horizontal)
        self.assertFalse(np.allclose(result, frame))

    def test_bump_map_zero_intensity_is_identity(self) -> None:
        frame = _depth_ramp()
        height_map = _depth_ramp()
        result = bump_map(
            frame,
            height_map,
            intensity=0.0,
            light_x=-0.5,
            light_y=-0.5,
            blur=0.0,
        )
        np.testing.assert_allclose(result, frame, atol=1e-6)

    def test_bump_map_shades_a_height_map(self) -> None:
        frame = _frame(value=0.5)
        height_map = _depth_ramp()
        result = bump_map(
            frame,
            height_map,
            intensity=1.0,
            light_x=-0.7,
            light_y=0.0,
            blur=0.0,
        )
        self.assertFalse(np.allclose(result, frame))

    def test_offset_zero_is_identity(self) -> None:
        frame = _depth_ramp()
        result = offset(frame, offset_x=0.0, offset_y=0.0, wrap=True)
        np.testing.assert_allclose(result, frame, atol=1e-6)

    def test_offset_wraps_pixels(self) -> None:
        frame = _depth_ramp(width=4)
        result = offset(frame, offset_x=0.5, offset_y=0.0, wrap=True)
        np.testing.assert_allclose(result, np.roll(frame, 2, axis=1), atol=1e-6)


class NewNodeSmokeTests(unittest.TestCase):
    """Every new node must construct and evaluate without raising."""

    def _wire_inputs(self, node: object) -> None:
        frame = _depth_ramp()
        for slot, socket in node.inputs.items():
            if socket.socket_type in (NodeSocketType.Frame, NodeSocketType.Mask):
                node.set_input_value(slot, frame)
            elif socket.socket_type == NodeSocketType.Number:
                node.set_input_value(slot, 0.5)

    def test_all_new_nodes_evaluate(self) -> None:
        for node_class in NEW_NODE_CLASSES:
            with self.subTest(node=node_class.node_type):
                node = node_class()
                node.prepare_evaluation(16, 16)
                node.clear_input_values()
                self._wire_inputs(node)
                result = node.evaluate(0)
                self.assertIsNotNone(result)

    def test_new_nodes_are_registered(self) -> None:
        from app_io.node_loader import NodeLoader
        from core.nodes.registry import global_node_registry

        NodeLoader.load_defaults()
        for node_class in NEW_NODE_CLASSES:
            with self.subTest(node=node_class.node_type):
                info = global_node_registry.get_node_info(
                    node_class.node_category, node_class.node_type
                )
                self.assertIsNotNone(info)
                assert info is not None
                self.assertIs(info.node_class, node_class)

    def test_logic_category_is_populated(self) -> None:
        from app_io.node_loader import NodeLoader
        from core.nodes.registry import global_node_registry

        NodeLoader.load_defaults()
        names = global_node_registry.get_nodes_in_category("Logic")
        self.assertIn("Compare", names)
        self.assertIn("Logic Gate", names)

    def test_new_enums_round_trip_through_serialization(self) -> None:
        from core.serialization import decode_value, encode_value

        for member in (
            *PixelSortMode,
            *AnaglyphMode,
            *AutoBalanceMode,
            *BendAxis,
        ):
            with self.subTest(member=member):
                self.assertEqual(decode_value(encode_value(member)), member)


if __name__ == "__main__":
    unittest.main()
