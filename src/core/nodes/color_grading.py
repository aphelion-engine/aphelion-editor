"""Color Grading node — primary controls plus lift/gamma/gain wheels."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.nodes.base import NEUTRAL_COLOR_RGB, NodeProperty
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import color_property, slider_property
from effects.color_grading import apply_color_grade


class ColorGradingNode(FrameEffectNode):
    """Primary color grade with exposure, balance, and tonal color wheels."""

    node_type: str = "Color Grading"
    node_category: str = "Color"
    node_description: str = (
        "Primary grade with exposure, contrast, saturation, and LGG wheels"
    )
    node_color: tuple[int, int, int] = (180, 120, 60)

    def setup_effect_properties(self) -> None:
        """Register primary correction and color-wheel controls."""
        self.set_property(
            "exposure",
            _primary_slider(
                0, -200, 200, 10, "Exposure", "Exposure in hundredths of a stop.", " st"
            ),
        )
        self.set_property(
            "contrast",
            _primary_slider(
                100, 0, 200, 11, "Contrast", "Contrast around middle gray.", "%"
            ),
        )
        self.set_property(
            "saturation",
            _primary_slider(
                100, 0, 200, 12, "Saturation", "Overall color intensity.", "%"
            ),
        )
        self.set_property(
            "temperature",
            _balance_slider(0, 20, "Temperature", "Cool-to-warm channel bias."),
        )
        self.set_property(
            "tint", _balance_slider(0, 21, "Tint", "Magenta-to-green channel bias.")
        )
        self.set_property(
            "lift_color", _wheel_property("Lift", "Shadow color bias.", 30)
        )
        self.set_property(
            "gamma_color", _wheel_property("Gamma", "Midtone color bias.", 31)
        )
        self.set_property(
            "gain_color", _wheel_property("Gain", "Highlight color bias.", 32)
        )
        # Lets a Tracker/Value/Math node drive exposure live (e.g. exposure
        # ramps synced to a tracked light source).
        self.expose_modulation_input("exposure")

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply the primary grade; base class handles final Mix."""
        del frame_num
        return apply_color_grade(
            frame,
            exposure=self.float_value("exposure", 0.0) / 100.0,
            contrast=max(0.0, self.float_value("contrast", 100.0) / 100.0),
            saturation=max(0.0, self.float_value("saturation", 100.0) / 100.0),
            temperature=self.float_value("temperature", 0.0) / 100.0,
            tint=self.float_value("tint", 0.0) / 100.0,
            lift_rgb=self.color_value("lift_color"),
            gamma_rgb=self.color_value("gamma_color"),
            gain_rgb=self.color_value("gain_color"),
            amount=1.0,
        )

    def apply_document(self, data: dict[str, Any]) -> None:
        """Load current documents and map legacy ``amount`` to ``mix``."""
        properties: object = data.get("properties")
        if (
            isinstance(properties, dict)
            and "amount" in properties
            and "mix" not in properties
        ):
            migrated: dict[str, Any] = dict(data)
            migrated_properties: dict[str, Any] = dict(properties)
            migrated_properties["mix"] = migrated_properties["amount"]
            migrated["properties"] = migrated_properties
            super().apply_document(migrated)
            return
        super().apply_document(data)


def _primary_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    description: str,
    suffix: str,
) -> NodeProperty:
    """Create a primary grading slider."""
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group="Primary",
        label=label,
        description=description,
        suffix=suffix,
    )


def _balance_slider(
    value: int,
    priority: int,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a color-balance slider."""
    return slider_property(
        value,
        -100,
        100,
        priority=priority,
        group="Balance",
        label=label,
        description=description,
        suffix="%",
    )


def _wheel_property(
    label: str,
    description: str,
    priority: int,
) -> NodeProperty:
    """Create a neutral lift/gamma/gain color property."""
    return color_property(
        NEUTRAL_COLOR_RGB,
        priority=priority,
        group="Color Wheels",
        label=label,
        description=description,
    )
