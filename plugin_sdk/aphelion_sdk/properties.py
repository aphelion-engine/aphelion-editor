"""Property builders exposed to plugin authors.

Call these from ``EffectPlugin.setup_effect_properties`` to declare the
editable, UI-rendered parameters of a plugin, then pass the result to
``self.set_property(key, ...)``.
"""

from __future__ import annotations

from aphelion_sdk.types import ColorRgb
from core.nodes.base import NodeProperty
from core.nodes.property_factory import color_property as _color_property
from core.nodes.property_factory import number_property as _number_property
from core.nodes.property_factory import slider_property as _slider_property
from core.nodes.property_factory import text_property as _text_property
from core.nodes.property_factory import toggle_property as _toggle_property

# Opaque handle returned by every builder below and accepted by
# ``Node.set_property``. Plugin authors never construct this directly.
PluginProperty = NodeProperty

_DEFAULT_GROUP: str = "General"
_DEFAULT_PRIORITY: int = 100


def slider_property(
    value: int,
    minimum: int,
    maximum: int,
    *,
    label: str,
    description: str = "",
    suffix: str = "",
    group: str = _DEFAULT_GROUP,
    priority: int = _DEFAULT_PRIORITY,
) -> PluginProperty:
    """Create an integer slider control, shown with a draggable slider."""
    return _slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group=group,
        label=label,
        description=description,
        suffix=suffix,
    )


def number_property(
    value: float,
    minimum: float,
    maximum: float,
    *,
    label: str,
    description: str = "",
    suffix: str = "",
    group: str = _DEFAULT_GROUP,
    priority: int = _DEFAULT_PRIORITY,
) -> PluginProperty:
    """Create a numeric spin-box control."""
    return _number_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group=group,
        label=label,
        description=description,
        suffix=suffix,
    )


def toggle_property(
    value: bool,
    *,
    label: str,
    description: str = "",
    group: str = _DEFAULT_GROUP,
    priority: int = _DEFAULT_PRIORITY,
) -> PluginProperty:
    """Create a boolean checkbox control."""
    return _toggle_property(
        value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def text_property(
    value: str,
    *,
    label: str,
    description: str = "",
    group: str = _DEFAULT_GROUP,
    priority: int = _DEFAULT_PRIORITY,
) -> PluginProperty:
    """Create a free-text control."""
    return _text_property(
        value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def color_property(
    value: ColorRgb,
    *,
    label: str,
    description: str = "",
    group: str = _DEFAULT_GROUP,
    priority: int = _DEFAULT_PRIORITY,
) -> PluginProperty:
    """Create an RGB color-swatch control."""
    return _color_property(
        value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )
