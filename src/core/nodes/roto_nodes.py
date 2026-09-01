"""Roto/rotopaint mask node: shape-based keyframed matte generation."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.nodes.base import NodeSocketType
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import toggle_property
from core.nodes.roto.model import RotoDocument
from effects.masks import invert_mask
from effects.roto_raster import rasterize_document

ROTO_CATEGORY: str = "Roto"


class RotoNode(FrameNode):
    """Generator node holding a ``RotoDocument`` and rasterizing it to a mask.

    Unlike regular node properties, the shape document is not rendered as a
    generic slider/checkbox — it is edited interactively through the viewport
    overlay (see ``ui.widgets.roto_overlay``) while ``edit_mode`` is enabled.
    """

    node_type: str = "Roto"
    node_category: str = ROTO_CATEGORY
    node_description: str = "Draw keyframed shape masks for garbage mattes and rotoscoping"
    node_color: tuple[int, int, int] = (176, 128, 72)

    def __init__(self, name: str | None = None) -> None:
        self.document: RotoDocument = RotoDocument()
        super().__init__(name)

    def _setup_sockets(self) -> None:
        """Register the mask output and edit/invert toggles."""
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property(
            "edit_mode",
            toggle_property(
                False,
                priority=0,
                group="Roto",
                label="Edit Mode",
                description="Arm the viewport overlay to edit this shape's points.",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=1,
                group="Roto",
                label="Invert",
                description="Invert the rasterized mask.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Rasterize the shape document at ``frame_num``."""
        width: int
        height: int
        width, height = self.evaluation_frame_size()
        mask: np.ndarray = rasterize_document(self.document, frame_num, width, height)
        if self.bool_value("invert", False):
            mask = invert_mask(mask)
        return mask

    def to_dict(self) -> dict[str, Any]:
        """Serialize base node data plus the shape document."""
        data = super().to_dict()
        data["shapes"] = self.document.to_dict()
        return data

    def apply_document(self, data: dict[str, Any]) -> None:
        """Restore base node data plus the shape document."""
        super().apply_document(data)
        self.document = RotoDocument.from_dict(data.get("shapes"))
