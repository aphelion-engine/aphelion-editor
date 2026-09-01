"""Time-based animated effect nodes."""

from __future__ import annotations

import numpy as np

from core.audio import FrameWithAudio
from core.nodes.base import NodeProperty, NodeSocketType, NodeValue
from core.nodes.frame_base import FrameEffectNode, FrameNode
from core.nodes.property_factory import number_property, slider_property
from effects.timing import film_flicker, pulse_exposure, strobe

TIMING_CATEGORY: str = "Timing"

# Sentinel for ``TimeRemapNode``'s "source_frame": below this, pass the
# current timeline frame through unchanged instead of resampling.
_PASSTHROUGH_SENTINEL: float = -1.0


class TimeRemapNode(FrameNode):
    """Resample the connected input at an animatable, possibly-different frame.

    Keyframe ``source_frame`` to freeze-frame (flat curve), reverse
    (descending curve), or speed-ramp (varying slope) any upstream chain —
    not just a Video Input's own trim controls.
    """

    node_type: str = "Time Remap"
    node_category: str = TIMING_CATEGORY
    node_description: str = (
        "Resample the input at a keyframed source frame — retime, freeze, or reverse"
    )
    node_color: tuple[int, int, int] = (196, 120, 96)

    def _setup_sockets(self) -> None:
        """Register frame sockets and the source-frame curve."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "source_frame",
            number_property(
                _PASSTHROUGH_SENTINEL,
                -100_000.0,
                100_000.0,
                priority=0,
                group="Time",
                label="Source Frame",
                description=(
                    "Upstream frame to sample. Keyframe this to retime; "
                    "-1 passes the current frame through unchanged."
                ),
            ),
        )
        self.expose_modulation_input("source_frame")

    def evaluate(self, frame_num: int) -> NodeValue:
        """Resample the upstream chain at the resolved source frame."""
        source_frame = self.float_value("source_frame", _PASSTHROUGH_SENTINEL)
        target = frame_num if source_frame < 0.0 else int(round(source_frame))
        resampled = self.resample_frame(target)
        if isinstance(resampled, (np.ndarray, FrameWithAudio)):
            return resampled
        return self.blank_frame()


class FrameHoldNode(FrameNode):
    """Freeze the connected input on a single fixed frame."""

    node_type: str = "Frame Hold"
    node_category: str = TIMING_CATEGORY
    node_description: str = "Freeze the input on one fixed upstream frame"
    node_color: tuple[int, int, int] = (188, 132, 100)

    def _setup_sockets(self) -> None:
        """Register frame sockets and the held frame number."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "hold_frame",
            number_property(
                0.0,
                0.0,
                100_000.0,
                priority=0,
                group="Time",
                label="Hold Frame",
                description="Upstream frame number to freeze on.",
            ),
        )
        self.expose_modulation_input("hold_frame")

    def evaluate(self, frame_num: int) -> NodeValue:
        """Resample the upstream chain at the fixed hold frame."""
        del frame_num
        target = int(round(self.float_value("hold_frame", 0.0)))
        resampled = self.resample_frame(target)
        if isinstance(resampled, (np.ndarray, FrameWithAudio)):
            return resampled
        return self.blank_frame()


class FilmFlickerNode(FrameEffectNode):
    """Exposure flicker driven by frame index."""

    node_type: str = "Film Flicker"
    node_category: str = TIMING_CATEGORY
    node_description: str = "Randomized exposure flicker for a film look"
    node_color: tuple[int, int, int] = (196, 148, 72)

    def setup_effect_properties(self) -> None:
        self.set_property("intensity", _timing_slider(35, 0, 100, 10, "Intensity", "Flicker"))
        self.set_property("speed", _timing_slider(50, 0, 100, 11, "Speed", "Motion"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return film_flicker(
            frame,
            intensity=self.float_value("intensity", 35.0) / 100.0,
            speed=self.float_value("speed", 50.0) / 100.0,
            frame_num=frame_num,
        )


class StrobeNode(FrameEffectNode):
    """On/off visibility gate synced to frame rate."""

    node_type: str = "Strobe"
    node_category: str = TIMING_CATEGORY
    node_description: str = "Flash the frame on and off at a set rate"
    node_color: tuple[int, int, int] = (210, 96, 88)

    def setup_effect_properties(self) -> None:
        self.set_property("rate", _timing_slider(8, 1, 30, 10, "Rate", "Timing", " Hz"))
        self.set_property("duty", _timing_slider(50, 5, 95, 11, "Duty", "Timing", "%"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return strobe(
            frame,
            rate=self.float_value("rate", 8.0),
            duty=self.float_value("duty", 50.0) / 100.0,
            frame_num=frame_num,
        )


class PulseExposureNode(FrameEffectNode):
    """Smooth breathing exposure animation."""

    node_type: str = "Pulse Exposure"
    node_category: str = TIMING_CATEGORY
    node_description: str = "Oscillate exposure over time"
    node_color: tuple[int, int, int] = (168, 128, 210)

    def setup_effect_properties(self) -> None:
        self.set_property("speed", _timing_slider(40, 0, 100, 10, "Speed", "Motion"))
        self.set_property("amount", _timing_slider(30, 0, 100, 11, "Amount", "Exposure"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return pulse_exposure(
            frame,
            speed=self.float_value("speed", 40.0) / 100.0,
            amount=self.float_value("amount", 30.0) / 100.0,
            frame_num=frame_num,
        )


def _timing_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    group: str,
    suffix: str = "%",
) -> NodeProperty:
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group=group,
        label=label,
        description=f"Adjust {label.lower()}.",
        suffix=suffix,
    )
