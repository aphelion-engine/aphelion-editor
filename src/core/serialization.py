"""Encode / decode project document values for stable JSON round-trips."""

from __future__ import annotations

from enum import Enum
from typing import Any

from core.nodes.base import (
    MediaEdgeMode,
    MediaLoopMode,
    NodeSocketType,
    VideoFrameErrorMethod,
)
from core.nodes.enums import (
    BlendMode,
    CombineMaskMode,
    EdgeDisplayMode,
    GradientMode,
    MaskChannel,
    SwitchInput,
    TransformBorderMode,
)
from render.preview import ViewerBackground, ViewportFitMode

APH_FORMAT_ID: str = "aphelion-project"
APH_FORMAT_VERSION: int = 1

# Named enum types that may appear in saved property values.
_ENUM_TYPES: dict[str, type[Enum]] = {
    "MediaEdgeMode": MediaEdgeMode,
    "MediaLoopMode": MediaLoopMode,
    "VideoFrameErrorMethod": VideoFrameErrorMethod,
    "NodeSocketType": NodeSocketType,
    "BlendMode": BlendMode,
    "CombineMaskMode": CombineMaskMode,
    "EdgeDisplayMode": EdgeDisplayMode,
    "GradientMode": GradientMode,
    "MaskChannel": MaskChannel,
    "SwitchInput": SwitchInput,
    "TransformBorderMode": TransformBorderMode,
    "ViewportFitMode": ViewportFitMode,
    "ViewerBackground": ViewerBackground,
}


def encode_value(value: Any) -> Any:
    """Convert a runtime property value into JSON-safe data.

    Parameters:
        value: Property value from a live node.

    Returns:
        A JSON-serializable value. Enums become
        ``{"__enum__": "<TypeName>", "name": "<Member>"}``.
    """
    if isinstance(value, Enum):
        return {
            "__enum__": type(value).__name__,
            "name": value.name,
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode_value(item) for key, item in value.items()}
    return str(value)


def decode_value(value: Any, *, fallback_enum: type[Enum] | None = None) -> Any:
    """Restore a property value from JSON-safe data.

    Parameters:
        value: Encoded value from a project document.
        fallback_enum: Optional enum type when only a member name was stored.

    Returns:
        A runtime value suitable for ``Node.set_property``.
    """
    if isinstance(value, dict) and "__enum__" in value:
        type_name = str(value.get("__enum__", ""))
        member_name = str(value.get("name", ""))
        enum_type = _ENUM_TYPES.get(type_name)
        if enum_type is None:
            return member_name
        try:
            return enum_type[member_name]
        except KeyError:
            return member_name

    if isinstance(value, str) and fallback_enum is not None:
        try:
            return fallback_enum[value]
        except KeyError:
            return value

    if isinstance(value, list):
        return [decode_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): decode_value(item) for key, item in value.items()}
    return value


def encode_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Encode a mapping of property name → live value."""
    return {key: encode_value(val) for key, val in properties.items()}


def decode_properties(
    properties: dict[str, Any],
    *,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decode property values, using ``defaults`` types as enum/color hints."""
    defaults = defaults or {}
    restored: dict[str, Any] = {}
    for key, raw in properties.items():
        fallback: type[Enum] | None = None
        default_val = defaults.get(key)
        if isinstance(default_val, Enum):
            fallback = type(default_val)
        value = decode_value(raw, fallback_enum=fallback)
        # Color properties round-trip as JSON lists; restore RGB tuples.
        if _is_rgb_tuple(default_val) and isinstance(value, list) and len(value) >= 3:
            value = (
                int(value[0]),
                int(value[1]),
                int(value[2]),
            )
        restored[key] = value
    return restored


def _is_rgb_tuple(value: Any) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 3
        and all(isinstance(channel, int) for channel in value)
    )
