"""Built-in two-input compositing nodes."""

from __future__ import annotations

import numpy as np

from core.audio import FrameWithAudio
from core.nodes.base import NodeSocketType
from core.nodes.enums import BlendMode
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (
    choice_property,
    slider_property,
    toggle_property,
)
from effects.compositing import blend_frames, dissolve_frames

COMPOSITING_CATEGORY: str = "Compositing"


class MergeNode(FrameNode):
    """Blend a foreground over a background with optional mask."""

    node_type: str = "Merge"
    node_category: str = COMPOSITING_CATEGORY
    node_description: str = (
        "Composite foreground over background using Normal, Add, Subtract, "
        "Multiply, Screen, Overlay, Difference, Darken, or Lighten"
    )
    node_color: tuple[int, int, int] = (70, 160, 112)

    def _setup_sockets(self) -> None:
        """Register frame/mask sockets and merge properties."""
        self.add_input("background", NodeSocketType.Frame)
        self.add_input("foreground", NodeSocketType.Frame)
        self.add_input("mask", NodeSocketType.Mask)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "enabled",
            toggle_property(
                True,
                priority=0,
                group="Merge",
                label="Enabled",
                description="Bypass foreground compositing.",
            ),
        )
        self.set_property(
            "blend_mode",
            choice_property(
                BlendMode.Normal,
                priority=10,
                group="Merge",
                label="Blend Mode",
                description="Pixel operation used to combine both frames.",
            ),
        )
        self.set_property(
            "opacity",
            slider_property(
                100,
                0,
                100,
                priority=11,
                group="Merge",
                label="Opacity",
                description="Foreground contribution before the mask.",
                suffix="%",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray | FrameWithAudio:
        """Composite inputs for the requested frame, preserving foreground audio."""
        del frame_num
        background_payload = self.input_frame_with_audio("background")
        foreground_payload = self.input_frame_with_audio("foreground")
        background: np.ndarray | None = background_payload.frame if background_payload is not None else self.input_frame("background")
        foreground: np.ndarray | None = foreground_payload.frame if foreground_payload is not None else self.input_frame("foreground")
        if background is None:
            return foreground_payload if foreground_payload is not None else (foreground if foreground is not None else self.blank_frame())
        if foreground is None or not self.bool_value("enabled", True):
            return background_payload if background_payload is not None else background
        mode: BlendMode = self.enum_value("blend_mode", BlendMode, BlendMode.Normal)
        result = blend_frames(
            background,
            foreground,
            mode=mode,
            opacity=self.float_value("opacity", 100.0) / 100.0,
            mask=self.input_frame("mask"),
        )
        carried_audio = None
        if foreground_payload is not None and foreground_payload.audio is not None:
            carried_audio = foreground_payload.audio
        elif background_payload is not None:
            carried_audio = background_payload.audio
        if carried_audio is not None:
            return FrameWithAudio(frame=result, audio=carried_audio)
        return result


class DissolveNode(FrameNode):
    """Cross-dissolve between two frames."""

    node_type: str = "Dissolve"
    node_category: str = COMPOSITING_CATEGORY
    node_description: str = "Linearly cross-dissolve from input A to input B"
    node_color: tuple[int, int, int] = (76, 166, 126)

    def _setup_sockets(self) -> None:
        """Register A/B frame sockets and mix control."""
        self.add_input("a", NodeSocketType.Frame)
        self.add_input("b", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "mix",
            slider_property(
                50,
                0,
                100,
                priority=0,
                group="Dissolve",
                label="Mix",
                description="Zero is A; one hundred is B.",
                suffix="%",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray | FrameWithAudio:
        """Dissolve the connected inputs, preserving the dominant input's audio."""
        del frame_num
        payload_a = self.input_frame_with_audio("a")
        payload_b = self.input_frame_with_audio("b")
        frame_a: np.ndarray | None = payload_a.frame if payload_a is not None else self.input_frame("a")
        frame_b: np.ndarray | None = payload_b.frame if payload_b is not None else self.input_frame("b")
        if frame_a is None:
            return payload_b if payload_b is not None else (frame_b if frame_b is not None else self.blank_frame())
        if frame_b is None:
            return payload_a if payload_a is not None else frame_a
        mix = self.float_value("mix", 50.0) / 100.0
        result = dissolve_frames(
            frame_a,
            frame_b,
            mix=mix,
        )
        carried_audio = payload_b.audio if (payload_b is not None and mix >= 0.5) else (payload_a.audio if payload_a is not None else None)
        if carried_audio is not None:
            return FrameWithAudio(frame=result, audio=carried_audio)
        return result
