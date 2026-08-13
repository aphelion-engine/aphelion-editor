"""Base class for single-input, single-output frame effect plugins."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from aphelion_sdk.types import ColorRgb, Frame
from core.nodes.frame_base import FrameEffectNode

_DEFAULT_PLUGIN_COLOR: ColorRgb = (120, 120, 120)


class EffectPlugin(FrameEffectNode):
    """Base class for a custom single-input/output frame effect plugin.

    Subclass this, set the ``plugin_*`` class attributes, and implement
    ``setup_effect_properties`` and ``process_frame``. The base class wires
    up the frame input/output sockets and the standard "Enabled"/"Mix"
    controls; plugin authors never touch sockets directly.

    Example:
        class Grayscale(EffectPlugin):
            plugin_name = "Grayscale"
            plugin_category = "Plugins"
            plugin_description = "Blend a frame toward grayscale."
            plugin_color = (140, 140, 140)

            def setup_effect_properties(self) -> None:
                self.set_property("amount", slider_property(100, 0, 100, label="Amount"))

            def process_frame(self, frame: Frame, frame_num: int) -> Frame:
                ...
    """

    #: Display name shown in the node graph and node-creation menus.
    plugin_name: ClassVar[str] = "Untitled Effect"
    #: Menu category the plugin is grouped under.
    plugin_category: ClassVar[str] = "Plugins"
    #: One-line description shown in tooltips and search results.
    plugin_description: ClassVar[str] = ""
    #: RGB header color for the node, in ``0-255`` per channel.
    plugin_color: ClassVar[ColorRgb] = _DEFAULT_PLUGIN_COLOR
    plugin_author: ClassVar[str] = "Unknown"
    
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Map plugin-facing metadata onto the internal node schema."""
        super().__init_subclass__(**kwargs)
        cls.node_type = cls.plugin_name
        cls.node_category = cls.plugin_category
        cls.node_description = cls.plugin_description
        cls.node_color = cls.plugin_color
        
    @abstractmethod
    def setup_effect_properties(self) -> None:
        """Register this effect's editable properties.

        Call ``self.set_property(key, <builder>(...))`` once per parameter,
        using the property builders from ``aphelion_sdk.properties``.
        """
        raise NotImplementedError

    @abstractmethod
    def process_frame(self, frame: Frame, frame_num: int) -> Frame:
        """Return the processed frame.

        Parameters:
            frame: Source frame, shape ``(height, width, 3)``, ``float32``,
                values nominally in ``[0.0, 1.0]``.
            frame_num: Absolute frame number currently being evaluated.

        Returns:
            The processed frame, same shape and dtype as ``frame``.
        """
        raise NotImplementedError
