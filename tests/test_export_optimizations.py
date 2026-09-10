"""Regression tests for the export fast path and the node fixes it uncovered.

Covers:
- export-mode evaluation must be pixel-identical to the interactive cache,
- export mode must keep the large interactive LRU untouched,
- the ``Depth Tilt Shift`` default of "no near blur" must not raise,
- the optimized ``Volumetric Light`` ray march must match the direct
  per-sample channel mean it replaced,
- MP4 PCM conversion must not mutate the caller's float audio buffer.
"""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from core.audio import AudioData
from core.nodes.compositing import MergeNode
from core.nodes.creative_nodes import GlowNode
from core.nodes.depth_nodes import DepthTiltShiftNode
from core.nodes.generator_nodes import SolidColorNode, VolumetricLightNode
from core.nodes.viewer import ViewerNode
from core.project import Project
from render.video_writer import Mp4VideoWriter

_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)


class ExportModeEquivalenceTests(unittest.TestCase):
    """The sequential-export cache must not change a single rendered pixel."""

    def _build(self) -> tuple[Project, str]:
        """Return a diamond-shaped graph plus its active Viewer node id."""
        project = Project(name="export-mode")
        project.width = 64
        project.height = 48

        source = project.add_node(SolidColorNode())
        project.nodes[source].set_property("color", (200, 120, 40))

        upper = project.add_node(GlowNode())
        lower = project.add_node(GlowNode())
        merge = project.add_node(MergeNode())
        viewer = project.add_node(ViewerNode())

        # Fan-out from one source: this is the shape the per-frame scratch
        # cache exists to deduplicate within a single exported frame.
        project.connect_nodes(source, "frame", upper, "frame")
        project.connect_nodes(source, "frame", lower, "frame")
        project.connect_nodes(upper, "frame", merge, "background")
        project.connect_nodes(lower, "frame", merge, "foreground")
        project.connect_nodes(merge, "frame", viewer, "frame")
        return project, viewer

    def test_export_mode_matches_interactive_cache(self) -> None:
        """Frames rendered in export mode equal frames from the LRU path."""
        frames = range(4)

        project, viewer = self._build()
        expected = [project.evaluate_node(viewer, frame) for frame in frames]

        project.set_export_mode(True)
        try:
            actual = [project.evaluate_node(viewer, frame) for frame in frames]
        finally:
            project.set_export_mode(False)

        for frame, (baseline, rendered) in enumerate(zip(expected, actual)):
            self.assertIsInstance(rendered, np.ndarray, msg=f"frame {frame}")
            np.testing.assert_array_equal(
                baseline,
                rendered,
                err_msg=f"frame {frame} differs between cache modes",
            )

    def test_export_mode_leaves_interactive_cache_empty(self) -> None:
        """Export evaluation must not populate the large cross-frame LRU."""
        project, viewer = self._build()

        project.set_export_mode(True)
        try:
            project.evaluate_node(viewer, 0)
            used_mb, _, entries = project.cache_stats()
            self.assertEqual(entries, 0)
            self.assertEqual(used_mb, 0.0)
            # ...while the per-frame scratch cache did hold intermediates.
            self.assertGreater(len(project._export_frame_cache), 0)
        finally:
            project.set_export_mode(False)

        self.assertEqual(project._export_frame_cache, {})

    def test_disabling_export_mode_restores_lru_caching(self) -> None:
        """Turning export mode off must restore interactive cache writes."""
        project, viewer = self._build()

        project.set_export_mode(True)
        project.evaluate_node(viewer, 0)
        project.set_export_mode(False)
        project.evaluate_node(viewer, 0)

        self.assertGreater(project.cache_stats()[2], 0)


class DepthTiltShiftTests(unittest.TestCase):
    """``Depth Tilt Shift`` used to raise on its own default settings."""

    def _build(self) -> tuple[Project, str]:
        project = Project(name="tilt-shift")
        project.width = 48
        project.height = 48

        source = project.add_node(SolidColorNode())
        project.nodes[source].set_property("color", _WHITE)
        depth = project.add_node(SolidColorNode())
        project.nodes[depth].set_property("color", _BLACK)

        tilt = project.add_node(DepthTiltShiftNode())
        project.connect_nodes(source, "frame", tilt, "frame")
        project.connect_nodes(depth, "frame", tilt, "depth")
        return project, tilt

    def test_default_zero_near_blur_does_not_raise(self) -> None:
        """A zero blur sigma means "no blur", not an OpenCV assertion."""
        project, tilt = self._build()
        frame = project.evaluate_node(tilt, 0)

        self.assertIsInstance(frame, np.ndarray)
        self.assertEqual(
            project.nodes[tilt].exception_log,
            [],
            "Depth Tilt Shift logged an exception on its default settings",
        )

    def test_both_blurs_disabled_returns_the_source_frame(self) -> None:
        """Disabling both blur directions is a pass-through."""
        project, tilt = self._build()
        project.set_node_property(tilt, "blur_near", 0)
        project.set_node_property(tilt, "blur_far", 0)

        frame = project.evaluate_node(tilt, 0)
        self.assertIsInstance(frame, np.ndarray)
        assert isinstance(frame, np.ndarray)
        np.testing.assert_allclose(frame, 1.0, atol=1e-6)


def _reference_ray_march(
    frame: np.ndarray,
    samples: int,
    cx: int,
    cy: int,
) -> np.ndarray:
    """Pre-optimization algorithm: per-sample RGB remap then channel mean."""
    height, width = frame.shape[:2]
    rays = np.zeros((height, width), dtype=np.float32)
    yy, xx = np.indices((height, width))
    dx = cx - xx
    dy = cy - yy

    for index in range(samples):
        t = index / samples
        sx = (xx + dx * t).astype(np.float32)
        sy = (yy + dy * t).astype(np.float32)
        sample = cv2.remap(frame[..., :3], sx, sy, cv2.INTER_LINEAR)
        rays += sample.mean(axis=2)

    return np.clip(rays / samples, 0.0, 1.0)


class VolumetricLightTests(unittest.TestCase):
    """The optimized ray march must stay numerically identical."""

    def _node(self, frame: np.ndarray, **properties: float) -> VolumetricLightNode:
        node = VolumetricLightNode()
        node.prepare_evaluation(frame.shape[1], frame.shape[0])
        node.clear_input_values()
        node.set_input_value("frame", frame)
        for key, value in properties.items():
            node.set_property(key, value)
        return node

    def test_ray_march_matches_reference_for_random_input(self) -> None:
        """Collapsing channels before the remap must not shift any pixel."""
        rng = np.random.default_rng(20240909)
        frame = rng.random((48, 64, 3), dtype=np.float32)
        height, width = frame.shape[:2]

        for samples, (percent_x, percent_y) in (
            (1, (50.0, 50.0)),
            (5, (0.0, 0.0)),
            (16, (98.4375, 50.0)),
        ):
            node = self._node(
                frame,
                samples=float(samples),
                center_x=percent_x,
                center_y=percent_y,
                intensity=100.0,
            )
            result = node.evaluate(0)
            self.assertIsInstance(result, np.ndarray)
            assert isinstance(result, np.ndarray)

            # Mirror the node's own percentage -> pixel-centre resolution so
            # the reference is driven by exactly the same centre.
            cx = int(node.float_value("center_x", 50.0) / 100.0 * width)
            cy = int(node.float_value("center_y", 50.0) / 100.0 * height)

            reference = _reference_ray_march(frame, samples, cx, cy)
            np.testing.assert_allclose(
                result[:, :, 0],
                reference,
                atol=1e-4,
                err_msg=f"samples={samples} centre=({cx}, {cy})",
            )

    def test_zero_samples_does_not_divide_by_zero(self) -> None:
        """A malformed sample count must not raise."""
        frame = np.full((8, 8, 3), 0.5, dtype=np.float32)
        node = self._node(frame, samples=0.0)
        result = node.evaluate(0)
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(node.exception_log, [])

    def test_all_three_channels_are_identical(self) -> None:
        """The node emits a grey image, so every channel must match."""
        rng = np.random.default_rng(5)
        frame = rng.random((16, 16, 3), dtype=np.float32)
        result = self._node(frame, samples=4.0).evaluate(0)
        assert isinstance(result, np.ndarray)
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
        np.testing.assert_array_equal(result[:, :, 1], result[:, :, 2])


class Mp4AudioConversionTests(unittest.TestCase):
    """PCM conversion must never write through the caller's audio buffer."""

    def _writer(self) -> Mp4VideoWriter:
        """Build a writer shell without spawning FFmpeg."""
        writer = Mp4VideoWriter.__new__(Mp4VideoWriter)
        writer._audio_channels = 2
        writer._audio_sample_rate = 48000
        return writer

    def test_source_samples_are_not_mutated(self) -> None:
        """Exporting used to scale the node's samples by 32767 in place."""
        samples = np.array(
            [[0.5, -0.25], [1.5, -2.0], [0.0, 0.75]],
            dtype=np.float32,
        )
        original = samples.copy()
        audio = AudioData(samples=samples, sample_rate=48000)

        pcm = self._writer()._prepare_audio(audio)

        np.testing.assert_array_equal(samples, original)
        self.assertEqual(pcm.dtype, np.int16)
        self.assertEqual(pcm.shape, (3, 2))
        # Clipped and scaled into the signed 16-bit range.
        np.testing.assert_array_equal(
            pcm,
            np.array([[16383, -8191], [32767, -32767], [0, 24575]], dtype=np.int16),
        )

    def test_mono_is_duplicated_to_stereo(self) -> None:
        """Mono input is up-mixed without touching the source."""
        samples = np.array([0.5, -0.5], dtype=np.float32)
        original = samples.copy()
        audio = AudioData(samples=samples, sample_rate=48000)

        pcm = self._writer()._prepare_audio(audio)

        np.testing.assert_array_equal(samples, original)
        self.assertEqual(pcm.shape, (2, 2))
        np.testing.assert_array_equal(pcm[:, 0], pcm[:, 1])


if __name__ == "__main__":
    unittest.main()
