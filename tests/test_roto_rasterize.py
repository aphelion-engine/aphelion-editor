"""Unit tests for roto shape flattening and document rasterization."""

from __future__ import annotations

import unittest

import numpy as np

from core.roto.model import RotoDocument, RotoPoint, RotoShape
from effects.roto_raster import flatten_shape, rasterize_document


class FlattenShapeTests(unittest.TestCase):
    """Verify pixel-space vertex generation."""

    def test_straight_shape_returns_one_vertex_per_point(self) -> None:
        """Non-smooth shapes map points directly to pixel coordinates."""
        points = [RotoPoint(x=0.0, y=0.0), RotoPoint(x=1.0, y=1.0)]
        vertices = flatten_shape(points, 100, 200, closed=False, smooth=False)
        self.assertEqual(vertices.shape, (2, 2))
        np.testing.assert_array_equal(vertices[0], [0, 0])
        np.testing.assert_array_equal(vertices[1], [100, 200])

    def test_smooth_shape_generates_more_vertices(self) -> None:
        """Catmull-Rom subdivision produces additional vertices for smooth shapes."""
        points = [
            RotoPoint(x=0.1, y=0.1),
            RotoPoint(x=0.5, y=0.9),
            RotoPoint(x=0.9, y=0.1),
        ]
        vertices = flatten_shape(points, 100, 100, closed=True, smooth=True)
        self.assertGreater(vertices.shape[0], len(points))

    def test_empty_points_returns_empty_array(self) -> None:
        """No points means no vertices."""
        vertices = flatten_shape([], 100, 100, closed=True, smooth=False)
        self.assertEqual(vertices.shape, (0, 2))


class RasterizeDocumentTests(unittest.TestCase):
    """Verify mask rasterization output contract and shape combination."""

    def test_empty_document_is_all_zero(self) -> None:
        """A document with no shapes rasterizes to a fully-zero mask."""
        mask = rasterize_document(RotoDocument(), 0, 32, 32)
        self.assertEqual(mask.dtype, np.float32)
        self.assertEqual(mask.shape, (32, 32, 3))
        self.assertTrue(np.all(mask == 0.0))

    def test_filled_square_shape_produces_nonzero_interior(self) -> None:
        """A closed square shape fills its interior with white."""
        square = RotoShape(
            shape_id="s1",
            closed=True,
            smooth=False,
            keyframes={
                0: [
                    RotoPoint(x=0.25, y=0.25),
                    RotoPoint(x=0.75, y=0.25),
                    RotoPoint(x=0.75, y=0.75),
                    RotoPoint(x=0.25, y=0.75),
                ]
            },
        )
        document = RotoDocument(shapes=[square])
        mask = rasterize_document(document, 0, 40, 40)
        center = mask[20, 20]
        corner = mask[1, 1]
        np.testing.assert_allclose(center, 1.0, atol=1e-5)
        np.testing.assert_allclose(corner, 0.0, atol=1e-5)

    def test_invert_flag_flips_the_shape_mask(self) -> None:
        """An inverted shape produces a black interior and white exterior."""
        square = RotoShape(
            shape_id="s1",
            closed=True,
            invert=True,
            keyframes={
                0: [
                    RotoPoint(x=0.25, y=0.25),
                    RotoPoint(x=0.75, y=0.25),
                    RotoPoint(x=0.75, y=0.75),
                    RotoPoint(x=0.25, y=0.75),
                ]
            },
        )
        document = RotoDocument(shapes=[square])
        mask = rasterize_document(document, 0, 40, 40)
        center = mask[20, 20]
        np.testing.assert_allclose(center, 0.0, atol=1e-5)

    def test_two_shapes_combine_by_union(self) -> None:
        """Overlapping shapes combine via per-pixel maximum."""
        shape_a = RotoShape(
            shape_id="a",
            closed=True,
            keyframes={
                0: [
                    RotoPoint(x=0.1, y=0.1),
                    RotoPoint(x=0.4, y=0.1),
                    RotoPoint(x=0.4, y=0.4),
                    RotoPoint(x=0.1, y=0.4),
                ]
            },
        )
        shape_b = RotoShape(
            shape_id="b",
            closed=True,
            keyframes={
                0: [
                    RotoPoint(x=0.6, y=0.6),
                    RotoPoint(x=0.9, y=0.6),
                    RotoPoint(x=0.9, y=0.9),
                    RotoPoint(x=0.6, y=0.9),
                ]
            },
        )
        document = RotoDocument(shapes=[shape_a, shape_b])
        mask = rasterize_document(document, 0, 50, 50)
        np.testing.assert_allclose(mask[10, 10], 1.0, atol=1e-5)
        np.testing.assert_allclose(mask[38, 38], 1.0, atol=1e-5)
        np.testing.assert_allclose(mask[25, 25], 0.0, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
