"""Built-in routing and mask utility nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import NodeSocketType
from core.nodes.enums import MaskChannel, SwitchInput
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (
    choice_property,
    slider_property,
    toggle_property,
)
from effects.masks import channel_mask, invert_mask


class FrameSwitchNode(FrameNode):
    """Route input A or B to the output without copying."""

    node_type: str = "Frame Switch"
    node_category: str = "Utility"
    node_description: str = "Select either frame input A or B"
    node_color: tuple[int, int, int] = (138, 138, 84)

    def _setup_sockets(self) -> None:
        """Register routing sockets and selection."""
        self.add_input("a", NodeSocketType.Frame)
        self.add_input("b", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "input",
            choice_property(
                SwitchInput.A,
                priority=0,
                group="Routing",
                label="Input",
                description="Frame input routed to the output.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Return the selected frame."""
        del frame_num
        selection: SwitchInput = self.enum_value("input", SwitchInput, SwitchInput.A)
        primary: np.ndarray | None = self.input_frame(
            "a" if selection == SwitchInput.A else "b"
        )
        fallback: np.ndarray | None = self.input_frame(
            "b" if selection == SwitchInput.A else "a"
        )
        if primary is not None:
            return primary
        return fallback if fallback is not None else self.blank_frame()


class ChannelMaskNode(FrameNode):
    """Generate a mask from luma or an RGB channel."""

    node_type: str = "Channel Mask"
    node_category: str = "Keying"
    node_description: str = "Extract luma, red, green, or blue into a soft mask"
    node_color: tuple[int, int, int] = (86, 154, 104)

    def _setup_sockets(self) -> None:
        """Register frame input, mask output, and range controls."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("mask", NodeSocketType.Mask)
        self._setup_channel_property()
        self._setup_range_properties()
        self._setup_invert_property()

    def _setup_channel_property(self) -> None:
        """Register source channel selection."""
        self.set_property(
            "channel",
            choice_property(
                MaskChannel.Luma,
                priority=10,
                group="Key",
                label="Channel",
                description="Source channel used for the mask.",
            ),
        )

    def _setup_range_properties(self) -> None:
        """Register black and white mapping points."""
        self.set_property(
            "low",
            slider_property(
                0,
                0,
                254,
                priority=11,
                group="Key",
                label="Low",
                description="Channel value mapped to black.",
            ),
        )
        self.set_property(
            "high",
            slider_property(
                255,
                1,
                255,
                priority=12,
                group="Key",
                label="High",
                description="Channel value mapped to white.",
            ),
        )

    def _setup_invert_property(self) -> None:
        """Register mask inversion."""
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=13,
                group="Key",
                label="Invert",
                description="Invert the generated mask.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Extract the selected channel mask."""
        del frame_num
        source: np.ndarray | None = self.input_frame()
        if source is None:
            return self.blank_frame()
        channel: MaskChannel = self.enum_value("channel", MaskChannel, MaskChannel.Luma)
        return channel_mask(
            source,
            channel=channel,
            low=self.int_value("low", 0),
            high=self.int_value("high", 255),
            invert=self.bool_value("invert", False),
        )


class InvertMaskNode(FrameNode):
    """Invert an incoming mask."""

    node_type: str = "Invert Mask"
    node_category: str = "Keying"
    node_description: str = "Invert a grayscale mask"
    node_color: tuple[int, int, int] = (82, 148, 96)

    def _setup_sockets(self) -> None:
        """Register mask input/output."""
        self.add_input("mask", NodeSocketType.Mask)
        self.add_output("mask", NodeSocketType.Mask)

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Invert the connected mask."""
        del frame_num
        source: np.ndarray | None = self.input_frame("mask")
        return self.blank_frame() if source is None else invert_mask(source)
