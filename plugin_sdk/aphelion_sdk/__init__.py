"""Aphelion Plugin SDK.

Public, stable surface for writing custom Aphelion node plugins.

Plugin authors must only ever import from this package (``aphelion_sdk``)
and must never import anything from ``core``, ``effects``, ``render``,
``ui``, or any other internal Aphelion package. The internal node system is
not a stable API; this package is.
"""

from __future__ import annotations

from aphelion_sdk.effect import EffectPlugin
from aphelion_sdk.properties import (
    PluginProperty,
    color_property,
    number_property,
    slider_property,
    text_property,
    toggle_property,
)
from aphelion_sdk.registration import (
    discover_installed_plugins,
    get_registered_plugins,
    register_plugin,
)
from aphelion_sdk.types import ColorRgb, Frame
from aphelion_sdk.version import __version__

__all__ = [
    "ColorRgb",
    "EffectPlugin",
    "Frame",
    "PluginProperty",
    "__version__",
    "color_property",
    "discover_installed_plugins",
    "get_registered_plugins",
    "number_property",
    "register_plugin",
    "slider_property",
    "text_property",
    "toggle_property",
]
