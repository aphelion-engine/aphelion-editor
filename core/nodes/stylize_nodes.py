"""Stylization and post-process effect nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import NodeProperty
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import slider_property
from effects.stylize import bloom, film_grain, radial_blur, scanlines

STYLIZE_CATEGORY: str = "Effects"


class FilmGrainNode(FrameEffectNode):
    """Temporal film grain overlay."""

    node_type: str = "Film Grain"
    node_category: str = STYLIZE_CATEGORY
    node_description: str = "Add animated grain noise"
    node_color: tuple[int, int, int] = (156, 136, 108)

    def setup_effect_properties(self) -> None:
        self.set_property("amount", _stylize_slider(25, 0, 100, 10, "Amount", "Grain"))
        self.set_property("seed", _stylize_slider(0, 0, 999, 11, "Seed", "Random", ""))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return film_grain(
            frame,
            amount=self.float_value("amount", 25.0) / 100.0,
            frame_num=frame_num,
            seed=self.int_value("seed", 0),
        )


class ScanlinesNode(FrameEffectNode):
    """CRT-style horizontal scanlines."""

    node_type: str = "Scanlines"
    node_category: str = STYLIZE_CATEGORY
    node_description: str = "Darken alternating rows like a CRT display"
    node_color: tuple[int, int, int] = (96, 148, 108)

    def setup_effect_properties(self) -> None:
        self.set_property("intensity", _stylize_slider(35, 0, 100, 10, "Intensity", "Lines"))
        self.set_property("spacing", _stylize_slider(3, 2, 12, 11, "Spacing", "Lines", " px"))
        self.set_property("scroll", _stylize_slider(0, 0, 100, 12, "Scroll", "Motion"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return scanlines(
            frame,
            intensity=self.float_value("intensity", 35.0) / 100.0,
            spacing=self.int_value("spacing", 3),
            scroll=self.float_value("scroll", 0.0) / 100.0,
            frame_num=frame_num,
        )


class BloomNode(FrameEffectNode):
    """Soft glow from bright regions."""

    node_type: str = "Bloom"
    node_category: str = STYLIZE_CATEGORY
    node_description: str = "Add a glow from highlights"
    node_color: tuple[int, int, int] = (188, 168, 96)

    def setup_effect_properties(self) -> None:
        self.set_property("threshold", _stylize_slider(70, 0, 100, 10, "Threshold", "Glow"))
        self.set_property("intensity", _stylize_slider(40, 0, 100, 11, "Intensity", "Glow"))
        self.set_property("radius", _stylize_slider(12, 1, 40, 12, "Radius", "Blur", " px"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return bloom(
            frame,
            threshold=self.float_value("threshold", 70.0) / 100.0,
            intensity=self.float_value("intensity", 40.0) / 100.0,
            radius=self.int_value("radius", 12),
        )


class RadialBlurNode(FrameEffectNode):
    """Zoom blur from a center point."""

    node_type: str = "Radial Blur"
    node_category: str = STYLIZE_CATEGORY
    node_description: str = "Average scaled copies for a radial blur"
    node_color: tuple[int, int, int] = (128, 108, 188)

    def setup_effect_properties(self) -> None:
        self.set_property("amount", _stylize_slider(50, 0, 100, 10, "Amount", "Blur"))
        self.set_property("center_x", _stylize_slider(50, 0, 100, 11, "Center X", "Center"))
        self.set_property("center_y", _stylize_slider(50, 0, 100, 12, "Center Y", "Center"))
        self.set_property("samples", _stylize_slider(8, 3, 16, 13, "Samples", "Quality", ""))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return radial_blur(
            frame,
            amount=self.float_value("amount", 50.0) / 100.0,
            center_x=self.float_value("center_x", 50.0) / 100.0,
            center_y=self.float_value("center_y", 50.0) / 100.0,
            samples=self.int_value("samples", 8),
        )


def _stylize_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    group: str,
    suffix: str = "%",
) -> NodeProperty:
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group=group,
        label=label,
        description=f"Adjust {label.lower()}.",
        suffix=suffix,
    )
