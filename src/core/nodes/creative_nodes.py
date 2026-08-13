"""Creative stylized effect nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import NodeProperty
from core.nodes.enums import MirrorAxis
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import choice_property, slider_property, toggle_property
from effects.creative import (
    chromatic_aberration,
    glitch,
    kaleidoscope,
    lens_distortion,
    mirror,
    rgb_split,
    ripple,
    transform_3d,
)

CREATIVE_CATEGORY: str = "Creative"
TRANSFORM_CATEGORY: str = "Transform"


class Transform3DNode(FrameEffectNode):
    """Perspective card transform with yaw, pitch, and roll."""

    node_type: str = "Transform 3D"
    node_category: str = TRANSFORM_CATEGORY
    node_description: str = "Simulate a 3D card transform with perspective"
    node_color: tuple[int, int, int] = (128, 92, 210)

    def setup_effect_properties(self) -> None:
        self.set_property("yaw", _axis_slider(0, -90, 90, 10, "Yaw", "Transform"))
        self.set_property("pitch", _axis_slider(0, -90, 90, 11, "Pitch", "Transform"))
        self.set_property("roll", _axis_slider(0, -180, 180, 12, "Roll", "Transform"))
        self.set_property(
            "perspective", _axis_slider(35, 0, 100, 20, "Perspective", "Camera")
        )
        self.set_property("fov", _axis_slider(75, 30, 120, 21, "FOV", "Camera", "°"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return transform_3d(
            frame,
            yaw_degrees=self.float_value("yaw", 0.0),
            pitch_degrees=self.float_value("pitch", 0.0),
            roll_degrees=self.float_value("roll", 0.0),
            perspective=self.float_value("perspective", 35.0) / 100.0,
            fov_degrees=self.float_value("fov", 75.0),
        )


class KaleidoscopeNode(FrameEffectNode):
    """Radial mirrored segments."""

    node_type: str = "Kaleidoscope"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Mirror the frame into radial segments"
    node_color: tuple[int, int, int] = (170, 88, 188)

    def setup_effect_properties(self) -> None:
        self.set_property("segments", _axis_slider(6, 2, 24, 10, "Segments", "Pattern"))
        self.set_property(
            "rotation", _axis_slider(0, -180, 180, 11, "Rotation", "Pattern", "°")
        )
        self.set_property(
            "center_x", _axis_slider(50, 0, 100, 12, "Center X", "Center", "%")
        )
        self.set_property(
            "center_y", _axis_slider(50, 0, 100, 13, "Center Y", "Center", "%")
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return kaleidoscope(
            frame,
            segments=int(self.int_value("segments", 6)),
            rotation_degrees=self.float_value("rotation", 0.0),
            center_x=self.float_value("center_x", 50.0) / 100.0,
            center_y=self.float_value("center_y", 50.0) / 100.0,
        )


class MirrorNode(FrameEffectNode):
    """Mirror half the frame across an axis."""

    node_type: str = "Mirror"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Reflect one half of the frame across an axis"
    node_color: tuple[int, int, int] = (108, 156, 196)

    def setup_effect_properties(self) -> None:
        self.set_property(
            "axis",
            choice_property(
                MirrorAxis.Horizontal,
                priority=10,
                group="Mirror",
                label="Axis",
                description="Mirror horizontally or vertically.",
            ),
        )
        self.set_property(
            "offset", _axis_slider(50, 5, 95, 11, "Split", "Mirror", "%")
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return mirror(
            frame,
            axis=self.enum_value("axis", MirrorAxis, MirrorAxis.Horizontal),
            offset=self.float_value("offset", 50.0) / 100.0,
        )


class LensDistortionNode(FrameEffectNode):
    """Barrel or pincushion lens distortion."""

    node_type: str = "Lens Distortion"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Barrel or pincushion radial distortion"
    node_color: tuple[int, int, int] = (92, 148, 176)

    def setup_effect_properties(self) -> None:
        self.set_property("strength", _axis_slider(35, 0, 100, 10, "Strength", "Lens"))
        self.set_property(
            "barrel",
            toggle_property(
                True,
                priority=11,
                group="Lens",
                label="Barrel",
                description="Use barrel distortion instead of pincushion.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return lens_distortion(
            frame,
            strength=self.float_value("strength", 35.0) / 100.0,
            barrel=self.bool_value("barrel", True),
        )


class ChromaticAberrationNode(FrameEffectNode):
    """Directional RGB channel separation."""

    node_type: str = "Chromatic Aberration"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Split red and blue channels for lens fringing"
    node_color: tuple[int, int, int] = (196, 96, 118)

    def setup_effect_properties(self) -> None:
        self.set_property("amount", _axis_slider(40, 0, 100, 10, "Amount", "Aberration"))
        self.set_property(
            "angle", _axis_slider(0, -180, 180, 11, "Angle", "Aberration", "°")
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return chromatic_aberration(
            frame,
            amount=self.float_value("amount", 40.0) / 100.0,
            angle_degrees=self.float_value("angle", 0.0),
        )


class RGBSplitNode(FrameEffectNode):
    """Independent RGB channel offsets."""

    node_type: str = "RGB Split"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Offset red, green, and blue channels independently"
    node_color: tuple[int, int, int] = (184, 102, 164)

    def setup_effect_properties(self) -> None:
        self.set_property("red_x", _axis_slider(8, -100, 100, 10, "Red X", "Channels"))
        self.set_property("red_y", _axis_slider(0, -100, 100, 11, "Red Y", "Channels"))
        self.set_property(
            "green_x", _axis_slider(0, -100, 100, 12, "Green X", "Channels")
        )
        self.set_property(
            "green_y", _axis_slider(0, -100, 100, 13, "Green Y", "Channels")
        )
        self.set_property(
            "blue_x", _axis_slider(-8, -100, 100, 14, "Blue X", "Channels")
        )
        self.set_property(
            "blue_y", _axis_slider(0, -100, 100, 15, "Blue Y", "Channels")
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return rgb_split(
            frame,
            red_x=self.float_value("red_x", 8.0) / 100.0,
            red_y=self.float_value("red_y", 0.0) / 100.0,
            green_x=self.float_value("green_x", 0.0) / 100.0,
            green_y=self.float_value("green_y", 0.0) / 100.0,
            blue_x=self.float_value("blue_x", -8.0) / 100.0,
            blue_y=self.float_value("blue_y", 0.0) / 100.0,
        )


class GlitchNode(FrameEffectNode):
    """Block displacement and channel tearing."""

    node_type: str = "Glitch"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Digital block displacement with channel tearing"
    node_color: tuple[int, int, int] = (210, 72, 132)

    def setup_effect_properties(self) -> None:
        self.set_property("amount", _axis_slider(45, 0, 100, 10, "Amount", "Glitch"))
        self.set_property("block_size", _axis_slider(24, 4, 96, 11, "Block Size", "Glitch"))
        self.set_property("seed", _axis_slider(0, 0, 999, 12, "Seed", "Glitch"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return glitch(
            frame,
            amount=self.float_value("amount", 45.0) / 100.0,
            block_size=int(self.int_value("block_size", 24)),
            seed=int(self.int_value("seed", 0)) + frame_num,
        )


class RippleNode(FrameEffectNode):
    """Animated sinusoidal displacement."""

    node_type: str = "Ripple"
    node_category: str = CREATIVE_CATEGORY
    node_description: str = "Wave displacement that animates over time"
    node_color: tuple[int, int, int] = (88, 168, 176)

    def setup_effect_properties(self) -> None:
        self.set_property("amplitude", _axis_slider(35, 0, 100, 10, "Amplitude", "Wave"))
        self.set_property("frequency", _axis_slider(6, 1, 24, 11, "Frequency", "Wave"))
        self.set_property("phase", _axis_slider(0, -180, 180, 12, "Phase", "Wave", "°"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return ripple(
            frame,
            amplitude=self.float_value("amplitude", 35.0) / 100.0,
            frequency=self.float_value("frequency", 6.0),
            phase=self.float_value("phase", 0.0),
            frame_num=frame_num,
        )


def _axis_slider(
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
