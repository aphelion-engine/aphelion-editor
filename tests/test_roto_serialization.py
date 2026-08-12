"""Round-trip serialization tests for RotoDocument and RotoNode."""

from __future__ import annotations

import unittest

from core.nodes.roto_nodes import RotoNode
from core.roto.model import RotoDocument, RotoPoint, RotoShape


class RotoDocumentRoundTripTests(unittest.TestCase):
    """Verify plain dataclass to_dict/from_dict round-trips exactly."""

    def _sample_document(self) -> RotoDocument:
        return RotoDocument(
            shapes=[
                RotoShape(
                    shape_id="shape_a",
                    closed=True,
                    smooth=True,
                    feather=2.5,
                    invert=False,
                    keyframes={
                        0: [RotoPoint(x=0.1, y=0.2), RotoPoint(x=0.3, y=0.4)],
                        24: [RotoPoint(x=0.5, y=0.6), RotoPoint(x=0.7, y=0.8)],
                    },
                )
            ]
        )

    def test_document_round_trips_through_dict(self) -> None:
        """to_dict -> from_dict recreates an equivalent document."""
        original = self._sample_document()
        restored = RotoDocument.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_from_dict_handles_missing_or_invalid_data(self) -> None:
        """Malformed or absent documents fall back to an empty document."""
        self.assertEqual(RotoDocument.from_dict(None), RotoDocument())
        self.assertEqual(RotoDocument.from_dict({}), RotoDocument())
        self.assertEqual(RotoDocument.from_dict({"shapes": "nope"}), RotoDocument())


class RotoNodeSerializationTests(unittest.TestCase):
    """Verify the shape document survives Node.to_dict()/apply_document()."""

    def test_node_to_dict_includes_shapes_key(self) -> None:
        """RotoNode.to_dict() adds a JSON-safe 'shapes' key."""
        node = RotoNode()
        node.document = RotoDocument(
            shapes=[
                RotoShape(
                    shape_id="s1",
                    keyframes={0: [RotoPoint(x=0.2, y=0.3)]},
                )
            ]
        )
        data = node.to_dict()
        self.assertIn("shapes", data)
        self.assertEqual(data["shapes"]["shapes"][0]["shape_id"], "s1")

    def test_apply_document_restores_shapes(self) -> None:
        """apply_document() rebuilds an equivalent RotoDocument."""
        source = RotoNode()
        source.document = RotoDocument(
            shapes=[
                RotoShape(
                    shape_id="s1",
                    closed=True,
                    keyframes={0: [RotoPoint(x=0.2, y=0.3), RotoPoint(x=0.8, y=0.9)]},
                )
            ]
        )
        data = source.to_dict()

        restored = RotoNode()
        restored.apply_document(data)
        self.assertEqual(restored.document, source.document)

    def test_apply_document_without_shapes_key_yields_empty_document(self) -> None:
        """Legacy/partial documents without a 'shapes' key don't crash."""
        node = RotoNode()
        node.apply_document({"name": "Roto", "x": 0.0, "y": 0.0, "properties": {}})
        self.assertEqual(node.document, RotoDocument())


if __name__ == "__main__":
    unittest.main()
