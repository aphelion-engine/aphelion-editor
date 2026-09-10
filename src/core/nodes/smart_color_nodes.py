"""Automatic and reference-driven color correction nodes.

These nodes analyze the incoming frame (or a reference frame) and apply a
corrective grade, which is what makes them "smart": expose them in a graph
and they adapt to each shot instead of needing hand-keyed values.
"""

from __future__ import annotations

import numpy as np
from core.nodes.base import NodeProperty, NodeSocketType
from core.nodes.enums import AutoBalanceMode
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import (choice_property, slider_property,
                                         toggle_property)
from effects.smart_color import auto_levels, auto_white_balance, shot_match

COLOR_CATEGORY: str = "Color"


def _strength_property(
    value: int,
    priority: int,
    label: str,
    description: str,
) -> NodeProperty:
    """Create the shared 0-100% correction strength slider."""
    return slider_property(
        value,
        0,
        100,
        priority=priority,
        group="Correction",
        label=label,
        description=description,
        suffix="%",
    )


class AutoLevelsNode(FrameEffectNode):
    """Stretch contrast automatically from the frame's histogram."""

    node_type: str = "Auto Levels"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Automatic contrast stretch from histogram percentiles"
    node_color: tuple[int, int, int] = (96, 158, 176)

    def setup_effect_properties(self) -> None:
        """Register the clip amount, per-channel option, and strength."""
        self.set_property(
            "clip",
            slider_property(
                1,
                0,
                20,
                priority=10,
                group="Correction",
                label="Clip",
                description="Percent of darkest and brightest pixels ignored.",
                suffix="%",
            ),
        )
        self.set_property(
            "per_channel",
            toggle_property(
                False,
                priority=11,
                group="Correction",
                label="Per Channel",
                description="Stretch each channel separately to remove color casts.",
            ),
        )
        self.set_property(
            "strength",
            _strength_property(100, 12, "Strength", "Blend the automatic result over the source."),
        )
        self.expose_modulation_input("clip")

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the auto-leveled frame."""
        del frame_num
        return auto_levels(
            frame,
            clip_percent=self.float_value("clip", 1.0),
            strength=self.float_value("strength", 100.0) / 100.0,
            per_channel=self.bool_value("per_channel", False),
        )


class AutoWhiteBalanceNode(FrameEffectNode):
    """Neutralize a color cast from the frame's own channel statistics."""

    node_type: str = "Auto White Balance"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Automatic color cast removal (gray world or white patch)"
    node_color: tuple[int, int, int] = (128, 158, 156)

    def setup_effect_properties(self) -> None:
        """Register the balance method and correction strength."""
        self.set_property(
            "mode",
            choice_property(
                AutoBalanceMode.GrayWorld,
                priority=10,
                group="Correction",
                label="Method",
                description="Statistic used to estimate the neutral point.",
            ),
        )
        self.set_property(
            "strength",
            _strength_property(100, 11, "Strength", "Blend the automatic result over the source."),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the white-balanced frame."""
        del frame_num
        return auto_white_balance(
            frame,
            mode=self.enum_value("mode", AutoBalanceMode, AutoBalanceMode.GrayWorld),
            strength=self.float_value("strength", 100.0) / 100.0,
        )


class ShotMatchNode(FrameEffectNode):
    """Match this shot's color statistics to a reference frame."""

    node_type: str = "Shot Match"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Match color and contrast to a reference frame"
    node_color: tuple[int, int, int] = (140, 150, 178)

    def setup_effect_properties(self) -> None:
        """Add the reference input and register the match controls."""
        self.add_input("reference", NodeSocketType.Frame)
        self.set_property(
            "match_luminance",
            toggle_property(
                True,
                priority=10,
                group="Correction",
                label="Match Luminance",
                description="Also transfer contrast, not just color cast.",
            ),
        )
        self.set_property(
            "strength",
            _strength_property(100, 11, "Strength", "Blend the matched result over the source."),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the shot-matched frame, or the source when unwired."""
        del frame_num
        reference: np.ndarray | None = self.input_frame("reference")
        if reference is None:
            return frame
        return shot_match(
            frame,
            reference,
            strength=self.float_value("strength", 100.0) / 100.0,
            match_luminance=self.bool_value("match_luminance", True),
        )
