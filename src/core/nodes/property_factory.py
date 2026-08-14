"""Typed factories for concise, consistent node property schemas."""

from __future__ import annotations

from enum import Enum

from core.nodes.base import ColorRgb, NodeProperty, NodePropertyInputType


def slider_property(
    value: int,
    minimum: int,
    maximum: int,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
    suffix: str = "",
) -> NodeProperty:
    """Create an integer slider property with UI metadata."""
    return NodeProperty(
        input_type=NodePropertyInputType.Slider,
        value=value,
        slider_min_value=minimum,
        slider_max_value=maximum,
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
    priority: int,
    group: str,
    label: str,
    description: str,
    suffix: str = "",
) -> NodeProperty:
    """Create a numeric spin-box property with UI metadata."""
    return NodeProperty(
        input_type=NodePropertyInputType.Number,
        value=value,
        slider_min_value=minimum,
        slider_max_value=maximum,
        priority=priority,
        group=group,
        label=label,
        description=description,
        suffix=suffix,
    )


def text_property(
    value: str,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a free-text property with UI metadata."""
    return NodeProperty(
        input_type=NodePropertyInputType.Text,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def image_file_property(
    value: str,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create an image-file path property (browse dialog filters to images)."""
    return NodeProperty(
        input_type=NodePropertyInputType.ImageFile,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def toggle_property(
    value: bool,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a boolean property with UI metadata."""
    return NodeProperty(
        input_type=NodePropertyInputType.Checkbox,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def node_property_choice_property(
    value: str,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a property key selector populated from a wired source node."""
    return NodeProperty(
        input_type=NodePropertyInputType.NodePropertyChoice,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def color_property(
    value: ColorRgb,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create an RGB color property with UI metadata."""
    return NodeProperty(
        input_type=NodePropertyInputType.Color,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )


def custom_property(
    value: object,
    *,
    widget_id: str,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create a custom inspector property bound to a dialog plugin id."""
    return NodeProperty(
        input_type=NodePropertyInputType.Custom,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
        custom_widget_id=widget_id,
    )


def choice_property(
    value: Enum,
    *,
    priority: int,
    group: str,
    label: str,
    description: str,
) -> NodeProperty:
    """Create an enum-backed choice property with UI metadata."""
    return NodeProperty(
        input_type=NodePropertyInputType.CustomChoice,
        value=value,
        priority=priority,
        group=group,
        label=label,
        description=description,
    )
