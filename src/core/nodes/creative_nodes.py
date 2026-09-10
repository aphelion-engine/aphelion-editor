"""Creative stylized effect nodes."""

from __future__ import annotations

import cv2
import numpy as np
from core.nodes.base import NodeProperty
from core.nodes.enums import MirrorAxis
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import (choice_property, slider_property,
                                         toggle_property)
from effects.creative import (chromatic_aberration, glitch, kaleidoscope,
                              lens_distortion, mirror, rgb_split, ripple,
                              transform_3d)

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
        self.set_property(
            "radial",
            _axis_slider(
                0,
                -100,
                100,
                12,
                "Radial",
                "Aberration",
                "%",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return chromatic_aberration(
            frame,
            amount=self.float_value("amount", 40.0) / 100.0,
            angle_degrees=self.float_value("angle", 0.0),
            radial=self.float_value("radial", 0.0) / 100.0,
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

class GlowNode(FrameEffectNode):
    """Thresholded glow effect."""

    node_type = "Glow"
    node_category = CREATIVE_CATEGORY
    node_description = "Soft glow with threshold and blur"
    node_color = (220, 140, 180)

    def setup_effect_properties(self):
        self.set_property(
            "threshold",
            slider_property(
                0.7, 0.0, 1.0,
                priority=10,
                group="Glow",
                label="Threshold",
                description="Brightness threshold for glow",
            ),
        )
        self.set_property(
            "radius",
            slider_property(
                12, 1, 64,
                priority=11,
                group="Glow",
                label="Radius",
                description="Glow blur radius",
                suffix=" px",
            ),
        )
        self.set_property(
            "intensity",
            slider_property(
                1.0, 0.0, 5.0,
                priority=12,
                group="Glow",
                label="Intensity",
                description="Glow strength",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        rgb = frame[..., :3].astype(np.float32)
        bright = np.clip(rgb - self.float_value("threshold", 0.7), 0, 1)
        radius = int(self.float_value("radius", 12))
        glow = cv2.GaussianBlur(bright, (0, 0), radius)
        out = rgb + glow * self.float_value("intensity", 1.0)
        return np.clip(out, 0, 1)

class LightWrapNode(FrameEffectNode):
    """Wrap background light around foreground edges."""

    node_type = "Light Wrap"
    node_category = CREATIVE_CATEGORY
    node_description = "Wrap background light around foreground edges"
    node_color = (180, 160, 120)

    def setup_effect_properties(self):
        self.set_property(
            "amount",
            slider_property(
                50, 0, 200,
                priority=10,
                group="Wrap",
                label="Amount",
                description="Light wrap intensity",
                suffix="%",
            ),
        )
        self.set_property(
            "blur",
            slider_property(
                8, 0, 64,
                priority=11,
                group="Wrap",
                label="Blur",
                description="Blur radius for wrap",
                suffix=" px",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        fg = frame
        bg = self.input_frame("background") or frame

        if fg.shape[2] < 4:
            return fg

        alpha = fg[..., 3:4].astype(np.float32)
        blur = int(self.float_value("blur", 8))
        amount = self.float_value("amount", 50) / 100.0

        bg_blur = cv2.GaussianBlur(bg[..., :3].astype(np.float32), (0, 0), blur)
        wrap = bg_blur * (1.0 - alpha)
        out = fg[..., :3] + wrap * amount
        return np.concatenate([np.clip(out, 0, 1), alpha], axis=2)

class GlowEdgesNode(FrameEffectNode):
    """Glow only on edges."""

    node_type = "Glow Edges"
    node_category = CREATIVE_CATEGORY
    node_description = "Glow applied only to detected edges"
    node_color = (200, 120, 200)

    def setup_effect_properties(self):
        self.set_property(
            "radius",
            slider_property(
                8, 1, 64,
                priority=10,
                group="Edges",
                label="Radius",
                description="Glow blur radius",
                suffix=" px",
            ),
        )
        self.set_property(
            "intensity",
            slider_property(
                1.0, 0.0, 5.0,
                priority=11,
                group="Edges",
                label="Intensity",
                description="Glow strength",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        gray = cv2.cvtColor(frame[..., :3], cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny((gray * 255).astype(np.uint8), 80, 160).astype(np.float32) / 255.0
        edges = cv2.GaussianBlur(edges, (0, 0), self.float_value("radius", 8))
        glow = edges[..., None] * self.float_value("intensity", 1.0)
        return np.clip(frame[..., :3] + glow, 0, 1)

class HalftoneNode(FrameEffectNode):
    """Comic-style halftone shading."""

    node_type = "Halftone"
    node_category = CREATIVE_CATEGORY
    node_description = "Dot-pattern halftone shading"
    node_color = (160, 120, 200)

    def setup_effect_properties(self):
        self.set_property(
            "scale",
            slider_property(
                8, 2, 64,
                priority=10,
                group="Halftone",
                label="Scale",
                description="Dot size",
                suffix=" px",
            ),
        )
        self.set_property(
            "contrast",
            slider_property(
                1.0, 0.0, 3.0,
                priority=11,
                group="Halftone",
                label="Contrast",
                description="Halftone contrast",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        gray = cv2.cvtColor(frame[..., :3], cv2.COLOR_RGB2GRAY)
        scale = int(self.float_value("scale", 8))
        contrast = self.float_value("contrast", 1.0)

        small = cv2.resize(gray, (frame.shape[1] // scale, frame.shape[0] // scale))
        dots = cv2.resize(small, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)
        dots = np.clip(dots * contrast, 0, 1)
        return np.dstack([dots, dots, dots])

class PosterEdgesNode(FrameEffectNode):
    """Posterize + edge enhancement."""

    node_type = "Poster Edges"
    node_category = CREATIVE_CATEGORY
    node_description = "Posterize colors and enhance edges"
    node_color = (180, 140, 160)

    def setup_effect_properties(self):
        self.set_property(
            "levels",
            slider_property(
                6, 2, 32,
                priority=10,
                group="Poster",
                label="Levels",
                description="Posterization levels",
            ),
        )
        self.set_property(
            "edge_strength",
            slider_property(
                1.0, 0.0, 5.0,
                priority=11,
                group="Poster",
                label="Edge Strength",
                description="Edge enhancement",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        levels = int(self.float_value("levels", 6))
        edge_strength = self.float_value("edge_strength", 1.0)

        rgb = frame[..., :3]
        poster = np.floor(rgb * levels) / levels

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny((gray * 255).astype(np.uint8), 80, 160).astype(np.float32) / 255.0
        edges = edges[..., None] * edge_strength

        return np.clip(poster + edges, 0, 1)

class VHSNode(FrameEffectNode):
    """Analog VHS distortion."""

    node_type = "VHS"
    node_category = CREATIVE_CATEGORY
    node_description = "Analog VHS distortion and color bleed"
    node_color = (200, 100, 120)

    def setup_effect_properties(self):
        self.set_property(
            "bleed",
            slider_property(
                20, 0, 100,
                priority=10,
                group="VHS",
                label="Bleed",
                description="Color bleed amount",
                suffix="%",
            ),
        )
        self.set_property(
            "noise",
            slider_property(
                10, 0, 100,
                priority=11,
                group="VHS",
                label="Noise",
                description="Static noise amount",
                suffix="%",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        bleed = self.float_value("bleed", 20) / 100.0
        noise = self.float_value("noise", 10) / 100.0

        rgb = frame[..., :3].astype(np.float32)
        shifted = np.roll(rgb, int(bleed * 10), axis=1)
        static = np.random.random(rgb.shape).astype(np.float32) * noise

        return np.clip(shifted + static, 0, 1)
