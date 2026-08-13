"""Example plugin: a single-slider grayscale effect.

Run this file's containing package through the host app's plugin loader,
or use it as a reference for structuring your own plugin. It only imports
from ``aphelion_sdk``.
"""

from __future__ import annotations

from aphelion_sdk import EffectPlugin, Frame, register_plugin, slider_property


@register_plugin
class GrayscaleEffect(EffectPlugin):
    """Desaturates a frame by a user-controlled amount."""

    plugin_name = "Grayscale"
    plugin_category = "Plugins"
    plugin_description = "Blend a frame toward grayscale."
    plugin_color = (140, 140, 140)

    def setup_effect_properties(self) -> None:
        """Register the "Amount" slider control."""
        self.set_property(
            "amount",
            slider_property(
                100,
                0,
                100,
                label="Amount",
                description="How much to desaturate the frame.",
                suffix="%",
            ),
        )

    def process_frame(self, frame: Frame, frame_num: int) -> Frame:
        """Blend the frame toward its luma-derived grayscale value."""
        del frame_num
        amount: float = self.float_value("amount", 100.0) / 100.0
        luma = (
            frame[..., 0] * 0.2126 + frame[..., 1] * 0.7152 + frame[..., 2] * 0.0722
        )
        gray = luma[..., None].repeat(3, axis=2)
        return frame * (1.0 - amount) + gray * amount
