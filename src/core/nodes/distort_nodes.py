"""Spatial distortion effect nodes."""

from __future__ import annotations
from core.nodes import NodeSocketType

import numpy as np
import cv2

from core.nodes.base import NodeProperty
from core.nodes.frame_base import FrameEffectNode, FrameNode
from core.nodes.property_factory import slider_property, toggle_property
from effects.distort import bulge, tile, twirl, wave_warp

DISTORT_CATEGORY: str = "Distort"


class TwirlNode(FrameEffectNode):
    """Swirl pixels around a center point."""

    node_type: str = "Twirl"
    node_category: str = DISTORT_CATEGORY
    node_description: str = "Rotate pixels within a radial falloff"
    node_color: tuple[int, int, int] = (92, 168, 128)

    def setup_effect_properties(self) -> None:
        self.set_property("angle", _distort_slider(45, -180, 180, 10, "Angle", "Twist", "°"))
        self.set_property("radius", _distort_slider(50, 5, 100, 11, "Radius", "Region"))
        self.set_property("strength", _distort_slider(100, 0, 100, 12, "Strength", "Twist"))
        self.set_property("center_x", _distort_slider(50, 0, 100, 13, "Center X", "Center"))
        self.set_property("center_y", _distort_slider(50, 0, 100, 14, "Center Y", "Center"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return twirl(
            frame,
            angle_degrees=self.float_value("angle", 45.0),
            radius=self.float_value("radius", 50.0) / 100.0,
            strength=self.float_value("strength", 100.0) / 100.0,
            center_x=self.float_value("center_x", 50.0) / 100.0,
            center_y=self.float_value("center_y", 50.0) / 100.0,
        )


class BulgeNode(FrameEffectNode):
    """Magnify or pinch around a center."""

    node_type: str = "Bulge"
    node_category: str = DISTORT_CATEGORY
    node_description: str = "Radial magnification or pinch distortion"
    node_color: tuple[int, int, int] = (108, 152, 196)

    def setup_effect_properties(self) -> None:
        self.set_property("strength", _distort_slider(35, -100, 100, 10, "Strength", "Bulge"))
        self.set_property("radius", _distort_slider(45, 5, 100, 11, "Radius", "Region"))
        self.set_property("center_x", _distort_slider(50, 0, 100, 12, "Center X", "Center"))
        self.set_property("center_y", _distort_slider(50, 0, 100, 13, "Center Y", "Center"))

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return bulge(
            frame,
            strength=self.float_value("strength", 35.0) / 100.0,
            radius=self.float_value("radius", 45.0) / 100.0,
            center_x=self.float_value("center_x", 50.0) / 100.0,
            center_y=self.float_value("center_y", 50.0) / 100.0,
        )


class WaveWarpNode(FrameEffectNode):
    """Directional sinusoidal displacement."""

    node_type: str = "Wave Warp"
    node_category: str = DISTORT_CATEGORY
    node_description: str = "Animated wave displacement along an axis"
    node_color: tuple[int, int, int] = (88, 176, 168)

    def setup_effect_properties(self) -> None:
        self.set_property("amplitude", _distort_slider(30, 0, 100, 10, "Amplitude", "Wave"))
        self.set_property("frequency", _distort_slider(8, 1, 32, 11, "Frequency", "Wave"))
        self.set_property("phase", _distort_slider(0, -180, 180, 12, "Phase", "Wave", "°"))
        self.set_property(
            "direction", _distort_slider(0, 0, 180, 13, "Direction", "Wave", "°")
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        return wave_warp(
            frame,
            amplitude=self.float_value("amplitude", 30.0) / 100.0,
            frequency=self.float_value("frequency", 8.0),
            phase=self.float_value("phase", 0.0),
            direction=self.float_value("direction", 0.0),
            frame_num=frame_num,
        )


class TileNode(FrameEffectNode):
    """Repeat the frame into a mirrored grid."""

    node_type: str = "Tile"
    node_category: str = DISTORT_CATEGORY
    node_description: str = "Tile the image with optional mirror alternation"
    node_color: tuple[int, int, int] = (148, 120, 196)

    def setup_effect_properties(self) -> None:
        self.set_property("columns", _distort_slider(2, 1, 6, 10, "Columns", "Grid", ""))
        self.set_property("rows", _distort_slider(2, 1, 6, 11, "Rows", "Grid", ""))
        self.set_property(
            "mirror",
            toggle_property(True, priority=12, group="Grid", label="Mirror", description="Alternate mirrored tiles."),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        del frame_num
        return tile(
            frame,
            columns=self.int_value("columns", 2),
            rows=self.int_value("rows", 2),
            mirror=self.bool_value("mirror", True),
        )


def _distort_slider(
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

class DisplaceNode(FrameNode):
    """Warp an image using a displacement map."""

    node_type = "Displace"
    node_category = "Distort"
    node_description = "Warp an image using a displacement map"
    node_color = (180, 120, 80)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("displace", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "strength",
            slider_property(
                20, 0, 200,
                priority=0,
                group="Displace",
                label="Strength",
                description="Displacement intensity",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        frame = self.input_frame("frame")
        disp = self.input_frame("displace")

        if frame is None or disp is None:
            return self.blank_frame()

        h, w = frame.shape[:2]
        strength = self.float_value("strength", 20.0)

        dx = disp[..., 0].astype(np.float32) * strength
        dy = disp[..., 1].astype(np.float32) * strength

        xx, yy = np.meshgrid(np.arange(w), np.arange(h))
        map_x = (xx + dx).astype(np.float32)
        map_y = (yy + dy).astype(np.float32)

        warped = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return warped

class DirectionalDisplaceNode(FrameNode):
    """Directional displacement using a grayscale map."""

    node_type = "Directional Displace"
    node_category = "Distort"
    node_description = "Displace image in one direction using a grayscale map"
    node_color = (160, 100, 60)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("map", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "angle",
            slider_property(
                0, 0, 360,
                priority=0,
                group="Displace",
                label="Angle",
                description="Displacement direction",
                suffix="°",
            ),
        )
        self.set_property(
            "strength",
            slider_property(
                20, 0, 200,
                priority=1,
                group="Displace",
                label="Strength",
                description="Displacement intensity",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        frame = self.input_frame("frame")
        m = self.input_frame("map")

        if frame is None or m is None:
            return self.blank_frame()

        h, w = frame.shape[:2]
        strength = self.float_value("strength", 20.0)
        angle = np.deg2rad(self.float_value("angle", 0.0))

        dx = np.cos(angle) * m[..., 0] * strength
        dy = np.sin(angle) * m[..., 0] * strength

        xx, yy = np.meshgrid(np.arange(w), np.arange(h))
        map_x = (xx + dx).astype(np.float32)
        map_y = (yy + dy).astype(np.float32)

        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
