"""Chroma keying, spill suppression, and matte cleanup nodes."""

from __future__ import annotations

import numpy as np
import cv2

from core.nodes.base import NodeSocketType
from core.nodes.enums import CombineMaskMode
from core.nodes.frame_base import FrameEffectNode, FrameNode
from core.nodes.property_factory import choice_property, color_property, slider_property
from effects.keying import chroma_key_mask, refine_matte, suppress_spill

KEYING_CATEGORY: str = "Keying"

# Default key color: a standard chroma-key green.
_DEFAULT_KEY_GREEN: tuple[int, int, int] = (0, 177, 64)


class ChromaKeyNode(FrameNode):
    """Generate a matte from a picked screen color."""

    node_type: str = "Chroma Key"
    node_category: str = KEYING_CATEGORY
    node_description: str = "Key out a picked screen color with adjustable tolerance"
    node_color: tuple[int, int, int] = (90, 160, 110)

    def _setup_sockets(self) -> None:
        """Register frame input, mask output, and key controls."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property(
            "key_color",
            color_property(
                _DEFAULT_KEY_GREEN,
                priority=0,
                group="Key",
                label="Key Color",
                description="Screen color to remove.",
            ),
        )
        self.set_property(
            "tolerance",
            slider_property(
                10,
                0,
                100,
                priority=10,
                group="Key",
                label="Tolerance",
                description="Color distance treated as fully keyed out.",
                suffix="%",
            ),
        )
        self.set_property(
            "softness",
            slider_property(
                20,
                1,
                100,
                priority=11,
                group="Key",
                label="Softness",
                description="Distance range over which the matte edge ramps in.",
                suffix="%",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Extract a chroma-key matte from the connected frame."""
        del frame_num
        source: np.ndarray | None = self.input_frame()
        if source is None:
            return self.blank_frame()
        return chroma_key_mask(
            source,
            key_color=self.color_value("key_color", _DEFAULT_KEY_GREEN),
            tolerance=self.float_value("tolerance", 10.0) / 100.0,
            softness=self.float_value("softness", 20.0) / 100.0,
        )


class SpillSuppressNode(FrameEffectNode):
    """Desaturate screen-color spill from foreground edges."""

    node_type: str = "Spill Suppress"
    node_category: str = KEYING_CATEGORY
    node_description: str = "Reduce screen-color spill on keyed foreground edges"
    node_color: tuple[int, int, int] = (94, 154, 116)

    def setup_effect_properties(self) -> None:
        """Register key color and suppression strength."""
        self.set_property(
            "key_color",
            color_property(
                _DEFAULT_KEY_GREEN,
                priority=10,
                group="Spill",
                label="Key Color",
                description="Screen color whose spill is suppressed.",
            ),
        )
        self.set_property(
            "amount",
            slider_property(
                100,
                0,
                100,
                priority=11,
                group="Spill",
                label="Amount",
                description="Strength of spill suppression.",
                suffix="%",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Suppress key-color spill on the connected frame."""
        del frame_num
        return suppress_spill(
            frame,
            key_color=self.color_value("key_color", _DEFAULT_KEY_GREEN),
            amount=self.float_value("amount", 100.0) / 100.0,
        )


class MatteEdgeNode(FrameNode):
    """Choke, feather, and remap a matte's black/white points."""

    node_type: str = "Matte Edge"
    node_category: str = KEYING_CATEGORY
    node_description: str = "Choke, feather, and level-remap a matte edge"
    node_color: tuple[int, int, int] = (88, 148, 108)

    def _setup_sockets(self) -> None:
        """Register mask input/output and edge-cleanup controls."""
        self.add_input("mask", NodeSocketType.Mask)
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property(
            "choke",
            slider_property(
                0,
                -20,
                20,
                priority=10,
                group="Edge",
                label="Choke",
                description="Erode (positive) or grow (negative) the matte edge.",
                suffix=" px",
            ),
        )
        self.set_property(
            "feather",
            slider_property(
                0,
                0,
                40,
                priority=11,
                group="Edge",
                label="Feather",
                description="Soften the matte edge with a blur radius.",
                suffix=" px",
            ),
        )
        self.set_property(
            "black_point",
            slider_property(
                0,
                0,
                99,
                priority=20,
                group="Levels",
                label="Black Point",
                description="Level mapped to fully transparent.",
                suffix="%",
            ),
        )
        self.set_property(
            "white_point",
            slider_property(
                100,
                1,
                100,
                priority=21,
                group="Levels",
                label="White Point",
                description="Level mapped to fully opaque.",
                suffix="%",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Clean up the connected mask's edge."""
        del frame_num
        source: np.ndarray | None = self.input_frame("mask")
        if source is None:
            return self.blank_frame()
        return refine_matte(
            source,
            choke=self.float_value("choke", 0.0),
            feather=self.float_value("feather", 0.0),
            black_point=self.float_value("black_point", 0.0) / 100.0,
            white_point=self.float_value("white_point", 100.0) / 100.0,
        )


class CombineMasksNode(FrameNode):
    """Combine two masks (e.g. a chroma key with a roto garbage matte)."""

    node_type: str = "Combine Masks"
    node_category: str = KEYING_CATEGORY
    node_description: str = "Add, subtract, intersect, or max two masks together"
    node_color: tuple[int, int, int] = (84, 142, 118)

    def _setup_sockets(self) -> None:
        """Register both mask inputs, the combined output, and blend mode."""
        self.add_input("mask_a", NodeSocketType.Mask)
        self.add_input("mask_b", NodeSocketType.Mask)
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property(
            "mode",
            choice_property(
                CombineMaskMode.Intersect,
                priority=0,
                group="Combine",
                label="Mode",
                description="Pixel operation used to combine both masks.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Combine both connected masks using the selected mode."""
        del frame_num
        mask_a: np.ndarray | None = self.input_frame("mask_a")
        mask_b: np.ndarray | None = self.input_frame("mask_b")
        if mask_a is None:
            return mask_b if mask_b is not None else self.blank_frame()
        if mask_b is None:
            return mask_a

        # --- AUTO RESIZE PATCH ---
        if mask_a.shape != mask_b.shape:
            h, w, _ = mask_a.shape
            mask_b = cv2.resize(mask_b, (w, h), interpolation=cv2.INTER_NEAREST)
        # --------------------------

        mode: CombineMaskMode = self.enum_value(
            "mode", CombineMaskMode, CombineMaskMode.Intersect
        )
        if mode == CombineMaskMode.Add:
            result = mask_a + mask_b
        elif mode == CombineMaskMode.Subtract:
            result = mask_a - mask_b
        elif mode == CombineMaskMode.Max:
            result = np.maximum(mask_a, mask_b)
        else:
            result = mask_a * mask_b

        return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)
