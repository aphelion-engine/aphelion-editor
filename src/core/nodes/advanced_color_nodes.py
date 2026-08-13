"""Advanced color correction nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import NodeProperty
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import slider_property, toggle_property
from effects.advanced_color import (
    clarity,
    color_balance,
    levels,
    shadows_highlights,
    vibrance,
)

COLOR_CATEGORY: str = "Color"


class LevelsNode(FrameEffectNode):
    """Input/output black-white points with gamma."""

    node_type: str = "Levels"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Remap black/white input and output with gamma"
    node_color: tuple[int, int, int] = (168, 118, 72)

    def setup_effect_properties(self) -> None:
        self.set_property("in_black", _pct_slider(0, 0, 40, 10, "In Black"))
        self.set_property("in_white", _pct_slider(100, 60, 100, 11, "In White"))
        self.set_property("gamma", _pct_slider(100, 20, 300, 12, "Gamma"))
        self.set_property("out_black", _pct_slider(0, 0, 40, 13, "Out Black"))
        self.set_property("out_white", _pct_slider(100, 60, 100, 14, "Out White"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return levels(
            frame,
            in_black=self.float_value("in_black", 0.0) / 100.0,
            in_white=self.float_value("in_white", 100.0) / 100.0,
            gamma=self.float_value("gamma", 100.0) / 100.0,
            out_black=self.float_value("out_black", 0.0) / 100.0,
            out_white=self.float_value("out_white", 100.0) / 100.0,
        )


class VibranceNode(FrameEffectNode):
    """Intelligent saturation boost for muted colors."""

    node_type: str = "Vibrance"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Boost low-saturation colors more than vivid tones"
    node_color: tuple[int, int, int] = (176, 96, 128)

    def setup_effect_properties(self) -> None:
        self.set_property("amount", _pct_slider(35, -100, 200, 10, "Amount"))
        self.set_property(
            "protect_skin",
            toggle_property(
                True,
                priority=11,
                group="Color",
                label="Protect Skin",
                description="Reduce vibrance on warm skin hues.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return vibrance(
            frame,
            amount=self.float_value("amount", 35.0) / 100.0,
            protect_skin=self.bool_value("protect_skin", True),
        )


class ShadowsHighlightsNode(FrameEffectNode):
    """Recover shadow detail and roll off harsh highlights."""

    node_type: str = "Shadows / Highlights"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Lift shadows and tame highlights with a midtone pivot"
    node_color: tuple[int, int, int] = (150, 110, 190)

    def setup_effect_properties(self) -> None:
        self.set_property("shadows", _pct_slider(0, -100, 100, 10, "Shadows"))
        self.set_property("highlights", _pct_slider(0, -100, 100, 11, "Highlights"))
        self.set_property("balance", _pct_slider(0, -100, 100, 12, "Balance"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return shadows_highlights(
            frame,
            shadows=self.float_value("shadows", 0.0) / 100.0,
            highlights=self.float_value("highlights", 0.0) / 100.0,
            balance=self.float_value("balance", 0.0) / 100.0,
        )


class ColorBalanceNode(FrameEffectNode):
    """Three-way color balance on shadows, mids, and highlights."""

    node_type: str = "Color Balance"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Shift cyan/red, magenta/green, and yellow/blue"
    node_color: tuple[int, int, int] = (188, 132, 84)

    def setup_effect_properties(self) -> None:
        self.set_property("cyan_red", _pct_slider(0, -100, 100, 10, "Cyan / Red"))
        self.set_property(
            "magenta_green", _pct_slider(0, -100, 100, 11, "Magenta / Green")
        )
        self.set_property("yellow_blue", _pct_slider(0, -100, 100, 12, "Yellow / Blue"))
        self.set_property(
            "preserve_luma",
            toggle_property(
                True,
                priority=13,
                group="Color",
                label="Preserve Luma",
                description="Keep perceived brightness after channel shifts.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return color_balance(
            frame,
            cyan_red=self.float_value("cyan_red", 0.0) / 100.0,
            magenta_green=self.float_value("magenta_green", 0.0) / 100.0,
            yellow_blue=self.float_value("yellow_blue", 0.0) / 100.0,
            preserve_luma=self.bool_value("preserve_luma", True),
        )


class ClarityNode(FrameEffectNode):
    """Local midtone contrast for punch and texture."""

    node_type: str = "Clarity"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Add midtone punch with a large-radius clarity pass"
    node_color: tuple[int, int, int] = (142, 156, 108)

    def setup_effect_properties(self) -> None:
        self.set_property("amount", _pct_slider(25, -100, 100, 10, "Amount"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return clarity(frame, amount=self.float_value("amount", 25.0) / 100.0)


def _pct_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
) -> NodeProperty:
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group="Color",
        label=label,
        description=f"Adjust {label.lower()}.",
        suffix="%",
    )
