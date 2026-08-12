"""Reusable typed bases for frame-processing nodes."""

from __future__ import annotations

from abc import abstractmethod
from enum import Enum
from typing import TypeVar

import numpy as np

from core.nodes.base import (
    NEUTRAL_COLOR_RGB,
    ColorRgb,
    Node,
    NodeProperty,
    NodeSocketType,
)
from core.nodes.property_factory import slider_property, toggle_property
from effects.frame_ops import mix_frames

EnumT = TypeVar("EnumT", bound=Enum)

# Naming convention for a property's optional live-modulation input socket.
# See ``FrameNode.expose_modulation_input``/``_modulated_value``.
_MODULATION_INPUT_PREFIX: str = "in_"


class FrameNode(Node):
    """Node with typed frame/property access helpers."""

    def input_frame(self, slot: str = "frame") -> np.ndarray | None:
        """Return a connected ndarray frame or ``None``."""
        value: object | None = self.get_input_value(slot)
        return value if isinstance(value, np.ndarray) else None

    def input_number(self, slot: str, default: float = 0.0) -> float:
        """Return a connected Number-socket scalar, or ``default``."""
        value: object | None = self.get_input_value(slot)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)

    def expose_modulation_input(self, key: str) -> None:
        """Add a Number input socket that can drive/override property ``key``.

        Once connected, ``float_value(key, ...)`` returns the live upstream
        number instead of the static or keyframed property value — this is
        the generic "property modulation" mechanism (e.g. a Tracker or Math
        node wired straight into a Transform's translate/rotation).
        """
        self.add_input(_MODULATION_INPUT_PREFIX + key, NodeSocketType.Number)

    def _modulated_value(self, key: str) -> float | None:
        """Return a connected modulation-socket override for ``key``, if wired."""
        value: object | None = self.get_input_value(_MODULATION_INPUT_PREFIX + key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _effective_numeric_override(self, key: str) -> float | None:
        """Return a live override from modulation or Property Drive."""
        modulated: float | None = self._modulated_value(key)
        if modulated is not None:
            return modulated
        return self.property_drive_value(key)

    def bool_value(self, key: str, default: bool) -> bool:
        """Read a boolean property."""
        override: float | None = self._effective_numeric_override(key)
        if override is not None:
            return override >= 0.5
        value: object | None = self._property_value(key)
        return default if value is None else bool(value)

    def float_value(self, key: str, default: float) -> float:
        """Read a floating-point property (modulation input takes priority)."""
        override: float | None = self._effective_numeric_override(key)
        if override is not None:
            return override
        value: object | None = self._property_value(key)
        if not isinstance(value, (str, int, float)):
            return default
        return float(value)

    def int_value(self, key: str, default: int) -> int:
        """Read an integer property (modulation input takes priority)."""
        override: float | None = self._effective_numeric_override(key)
        if override is not None:
            return round(override)
        value: object | None = self._property_value(key)
        if not isinstance(value, (str, int, float)):
            return default
        return int(value)

    def string_value(self, key: str, default: str = "") -> str:
        """Read a free-text property."""
        value: object | None = self._property_value(key)
        return default if value is None else str(value)

    def color_value(self, key: str, default: ColorRgb = NEUTRAL_COLOR_RGB) -> ColorRgb:
        """Read and clamp an RGB color property."""
        value: object | None = self._property_value(key)
        if not isinstance(value, (tuple, list)) or len(value) < 3:
            return default
        red: int = max(0, min(255, int(value[0])))
        green: int = max(0, min(255, int(value[1])))
        blue: int = max(0, min(255, int(value[2])))
        return red, green, blue

    def enum_value(self, key: str, enum_type: type[EnumT], default: EnumT) -> EnumT:
        """Read an enum property with a safe fallback."""
        value: object | None = self._property_value(key)
        if isinstance(value, enum_type):
            return value
        try:
            return enum_type(value)
        except (TypeError, ValueError):
            return default

    def _property_value(self, key: str) -> object | None:
        """Return a raw property value, resolving a keyframe curve if animated."""
        prop: NodeProperty | None = self.get_property(key)
        if prop is None:
            return None
        curve = self.animated_properties.get(key)
        if (
            curve is not None
            and not curve.is_empty
            and isinstance(prop.value, (int, float))
            and not isinstance(prop.value, bool)
        ):
            return curve.value_at(self._current_frame_num)
        return prop.value


class FrameEffectNode(FrameNode):
    """Unary effect with consistent Enabled and Mix controls."""

    def _setup_sockets(self) -> None:
        """Register shared unary frame sockets and processing controls."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "enabled",
            toggle_property(
                True,
                priority=0,
                group="Processing",
                label="Enabled",
                description="Bypass this effect without removing it from the graph.",
            ),
        )
        self.set_property(
            "mix",
            slider_property(
                100,
                0,
                100,
                priority=1,
                group="Processing",
                label="Mix",
                description="Blend the processed frame over the source.",
                suffix="%",
            ),
        )
        self.setup_effect_properties()

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Evaluate the effect and blend it with the source."""
        source: np.ndarray | None = self.input_frame()
        if source is None:
            return self.blank_frame()
        if not self.bool_value("enabled", True):
            return source
        mix: float = self.float_value("mix", 100.0) / 100.0
        if mix <= 0.0:
            return source
        effected: np.ndarray = self.process_frame(source, frame_num)
        return mix_frames(source, effected, mix)

    @abstractmethod
    def setup_effect_properties(self) -> None:
        """Register effect-specific properties."""
        raise NotImplementedError

    @abstractmethod
    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the processed frame at ``frame_num``."""
        raise NotImplementedError
