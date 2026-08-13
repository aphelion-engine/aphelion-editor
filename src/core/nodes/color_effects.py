"""Built-in color correction and channel-processing nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import WHITE_COLOR_RGB, NodeProperty
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import color_property, slider_property
from effects.color_adjustments import (
    channel_mixer,
    exposure_contrast,
    hue_saturation,
    invert,
    monochrome,
    posterize,
    threshold,
    white_balance,
)

COLOR_CATEGORY: str = "Color"
COLOR_NODE_COLOR: tuple[int, int, int] = (186, 112, 64)


class ExposureContrastNode(FrameEffectNode):
    """Exposure, brightness, and contrast correction."""

    node_type: str = "Exposure & Contrast"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Correct exposure, brightness, and midpoint contrast"
    node_color: tuple[int, int, int] = COLOR_NODE_COLOR

    def setup_effect_properties(self) -> None:
        """Register tonal controls."""
        self.set_property(
            "exposure",
            _color_slider(
                0, -400, 400, 10, "Exposure", "Exposure in hundredths of a stop.", " st"
            ),
        )
        self.set_property(
            "brightness",
            _color_slider(
                0, -100, 100, 11, "Brightness", "Uniform luminance offset.", "%"
            ),
        )
        self.set_property(
            "contrast",
            _color_slider(
                100, 0, 300, 12, "Contrast", "Contrast around middle gray.", "%"
            ),
        )
        self.expose_modulation_input("exposure")

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply tonal correction."""
        del frame_num
        return exposure_contrast(
            frame,
            exposure=self.float_value("exposure", 0.0) / 100.0,
            brightness=self.float_value("brightness", 0.0),
            contrast=self.float_value("contrast", 100.0) / 100.0,
        )


class HueSaturationNode(FrameEffectNode):
    """HSV hue, saturation, and lightness adjustment."""

    node_type: str = "Hue & Saturation"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Rotate hue and adjust saturation and lightness"
    node_color: tuple[int, int, int] = (190, 90, 110)

    def setup_effect_properties(self) -> None:
        """Register HSV controls."""
        self.set_property(
            "hue", _color_slider(0, -180, 180, 10, "Hue", "Hue rotation.", "°")
        )
        self.set_property(
            "saturation",
            _color_slider(100, 0, 300, 11, "Saturation", "Color intensity.", "%"),
        )
        self.set_property(
            "lightness",
            _color_slider(
                0, -100, 100, 12, "Lightness", "Post-HSV brightness offset.", "%"
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply HSV correction."""
        del frame_num
        return hue_saturation(
            frame,
            hue_degrees=self.float_value("hue", 0.0),
            saturation=self.float_value("saturation", 100.0) / 100.0,
            lightness=self.float_value("lightness", 0.0),
        )


class WhiteBalanceNode(FrameEffectNode):
    """Temperature and tint white-balance correction."""

    node_type: str = "White Balance"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Balance warm/cool and green/magenta casts"
    node_color: tuple[int, int, int] = (196, 132, 72)

    def setup_effect_properties(self) -> None:
        """Register white-balance controls."""
        self.set_property(
            "temperature",
            _color_slider(
                0,
                -100,
                100,
                10,
                "Temperature",
                "Cool (negative) to warm (positive).",
                "%",
            ),
        )
        self.set_property(
            "tint",
            _color_slider(
                0, -100, 100, 11, "Tint", "Magenta (negative) to green (positive).", "%"
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply channel gain white balance."""
        del frame_num
        return white_balance(
            frame,
            temperature=self.float_value("temperature", 0.0) / 100.0,
            tint=self.float_value("tint", 0.0) / 100.0,
        )


class InvertNode(FrameEffectNode):
    """Invert RGB channels."""

    node_type: str = "Invert"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Invert all RGB channels"
    node_color: tuple[int, int, int] = (128, 100, 190)

    def setup_effect_properties(self) -> None:
        """Register no additional controls."""

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Invert the source frame."""
        del frame_num
        return invert(frame)


class MonochromeNode(FrameEffectNode):
    """Weighted RGB-to-monochrome conversion."""

    node_type: str = "Monochrome"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Convert to grayscale with custom RGB contribution"
    node_color: tuple[int, int, int] = (112, 112, 112)

    def setup_effect_properties(self) -> None:
        """Register channel-weight controls."""
        self.set_property(
            "red_weight",
            _channel_slider(21, 10, "Red", "Red contribution to luminance."),
        )
        self.set_property(
            "green_weight",
            _channel_slider(72, 11, "Green", "Green contribution to luminance."),
        )
        self.set_property(
            "blue_weight",
            _channel_slider(7, 12, "Blue", "Blue contribution to luminance."),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Convert the source to monochrome."""
        del frame_num
        return monochrome(
            frame,
            red_weight=self.float_value("red_weight", 21.0),
            green_weight=self.float_value("green_weight", 72.0),
            blue_weight=self.float_value("blue_weight", 7.0),
        )


class ThresholdNode(FrameEffectNode):
    """Two-color luminance threshold."""

    node_type: str = "Threshold"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Map luminance below and above a threshold to colors"
    node_color: tuple[int, int, int] = (120, 120, 120)

    def setup_effect_properties(self) -> None:
        """Register threshold and output colors."""
        self.set_property(
            "level",
            _color_slider(128, 0, 255, 10, "Threshold", "Luminance split point.", ""),
        )
        self.set_property(
            "low_color",
            color_property(
                (0, 0, 0),
                priority=11,
                group="Threshold",
                label="Below",
                description="Color below the threshold.",
            ),
        )
        self.set_property(
            "high_color",
            color_property(
                WHITE_COLOR_RGB,
                priority=12,
                group="Threshold",
                label="Above",
                description="Color at or above the threshold.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply the two-color threshold."""
        del frame_num
        return threshold(
            frame,
            level=self.int_value("level", 128),
            low_color=self.color_value("low_color", (0, 0, 0)),
            high_color=self.color_value("high_color", WHITE_COLOR_RGB),
        )


class PosterizeNode(FrameEffectNode):
    """Reduce each RGB channel to a fixed number of levels."""

    node_type: str = "Posterize"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Quantize colors into a limited palette"
    node_color: tuple[int, int, int] = (160, 94, 150)

    def setup_effect_properties(self) -> None:
        """Register palette level count."""
        self.set_property(
            "levels",
            _color_slider(
                6, 2, 32, 10, "Levels", "Quantization levels per channel.", ""
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Posterize the source frame."""
        del frame_num
        return posterize(frame, levels=self.int_value("levels", 6))


class ChannelMixerNode(FrameEffectNode):
    """Mix output RGB channels from a configurable 3x3 matrix."""

    node_type: str = "Channel Mixer"
    node_category: str = COLOR_CATEGORY
    node_description: str = "Remap RGB channels through a 3x3 contribution matrix"
    node_color: tuple[int, int, int] = (156, 90, 130)

    def setup_effect_properties(self) -> None:
        """Register nine channel contribution controls."""
        entries: tuple[tuple[str, int, str, str], ...] = (
            ("rr", 100, "Red from Red", "Red input contribution to red output."),
            ("rg", 0, "Red from Green", "Green input contribution to red output."),
            ("rb", 0, "Red from Blue", "Blue input contribution to red output."),
            ("gr", 0, "Green from Red", "Red input contribution to green output."),
            (
                "gg",
                100,
                "Green from Green",
                "Green input contribution to green output.",
            ),
            ("gb", 0, "Green from Blue", "Blue input contribution to green output."),
            ("br", 0, "Blue from Red", "Red input contribution to blue output."),
            ("bg", 0, "Blue from Green", "Green input contribution to blue output."),
            ("bb", 100, "Blue from Blue", "Blue input contribution to blue output."),
        )
        for priority, (key, value, label, description) in enumerate(entries, start=10):
            group: str = f"{label.split()[0]} Output"
            self.set_property(
                key, _matrix_slider(value, priority, group, label, description)
            )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply the configured channel matrix."""
        del frame_num
        keys: tuple[str, ...] = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
        values: list[float] = [self.float_value(key, 0.0) / 100.0 for key in keys]
        return channel_mixer(frame, np.asarray(values, dtype=np.float32))


def _color_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    description: str,
    suffix: str,
) -> NodeProperty:
    """Create a slider in the Color group."""
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group="Color",
        label=label,
        description=description,
        suffix=suffix,
    )


def _channel_slider(
    value: int,
    priority: int,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a percentage channel-weight slider."""
    return slider_property(
        value,
        0,
        100,
        priority=priority,
        group="Channels",
        label=label,
        description=description,
        suffix="%",
    )


def _matrix_slider(
    value: int,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a signed channel matrix slider."""
    return slider_property(
        value,
        -200,
        200,
        priority=priority,
        group=group,
        label=label,
        description=description,
        suffix="%",
    )
