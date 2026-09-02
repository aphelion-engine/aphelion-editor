"""Built-in geometric transform nodes."""

from __future__ import annotations

import numpy as np
import cv2

from core.nodes.base import NodeProperty, NodeSocketType
from core.nodes.enums import TransformBorderMode
from core.nodes.frame_base import FrameEffectNode, FrameNode
from core.nodes.property_factory import (
    choice_property,
    color_property,
    number_property,
    slider_property,
    toggle_property,
)
from effects.transform import corner_pin, crop, transform_2d

TRANSFORM_CATEGORY: str = "Transform"


class Transform2DNode(FrameEffectNode):
    """Translate, scale, and rotate a frame."""

    node_type: str = "Transform 2D"
    node_category: str = TRANSFORM_CATEGORY
    node_description: str = "Translate, uniformly scale, and rotate a frame"
    node_color: tuple[int, int, int] = (116, 102, 196)

    def setup_effect_properties(self) -> None:
        """Register transform and border controls."""
        self._setup_translation_properties()
        self._setup_scale_properties()
        self._setup_border_properties()
        # A Tracker/Value/Math node can drive any of these live — the
        # canonical "perspective tracking drives a transform" use case.
        for key in ("translate_x", "translate_y", "rotation", "scale"):
            self.expose_modulation_input(key)

    def _setup_translation_properties(self) -> None:
        """Register horizontal and vertical offsets."""
        self.set_property(
            "translate_x",
            _transform_slider(
                0,
                -100,
                100,
                10,
                "X",
                "Horizontal translation relative to frame width.",
                "%",
            ),
        )
        self.set_property(
            "translate_y",
            _transform_slider(
                0,
                -100,
                100,
                11,
                "Y",
                "Vertical translation relative to frame height.",
                "%",
            ),
        )

    def _setup_scale_properties(self) -> None:
        """Register scale and rotation controls."""
        self.set_property(
            "scale",
            _transform_slider(
                100, 1, 400, 12, "Scale", "Uniform scale around frame center.", "%"
            ),
        )
        self.set_property(
            "rotation",
            _transform_slider(
                0,
                -180,
                180,
                13,
                "Rotation",
                "Clockwise rotation around frame center.",
                "°",
            ),
        )

    def _setup_border_properties(self) -> None:
        """Register out-of-bounds pixel controls."""
        self.set_property(
            "border_mode",
            choice_property(
                TransformBorderMode.Black,
                priority=20,
                group="Border",
                label="Mode",
                description="How pixels beyond the source edge are generated.",
            ),
        )
        self.set_property(
            "border_color",
            color_property(
                (0, 0, 0),
                priority=21,
                group="Border",
                label="Color",
                description="Fill color used by Black border mode.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply the affine transform."""
        del frame_num
        border: TransformBorderMode = self.enum_value(
            "border_mode", TransformBorderMode, TransformBorderMode.Black
        )
        return transform_2d(
            frame,
            translate_x=self.float_value("translate_x", 0.0) / 100.0,
            translate_y=self.float_value("translate_y", 0.0) / 100.0,
            scale=self.float_value("scale", 100.0) / 100.0,
            rotation_degrees=self.float_value("rotation", 0.0),
            border_mode=border,
            border_color=self.color_value("border_color", (0, 0, 0)),
        )


class CornerPinNode(FrameEffectNode):
    """Warp a frame so its four corners land at arbitrary target points.

    Each corner is independently modulatable (see
    ``FrameNode.expose_modulation_input``), so a ``PlanarTrackerNode``'s
    eight Number outputs can drive this directly for match-moved inserts.
    """

    node_type: str = "Corner Pin"
    node_category: str = TRANSFORM_CATEGORY
    node_description: str = "Warp a frame's four corners to arbitrary tracked points"
    node_color: tuple[int, int, int] = (120, 100, 200)

    _DEFAULT_CORNERS: tuple[tuple[str, float, float], ...] = (
        ("top_left", 0.0, 0.0),
        ("top_right", 100.0, 0.0),
        ("bottom_right", 100.0, 100.0),
        ("bottom_left", 0.0, 100.0),
    )

    def setup_effect_properties(self) -> None:
        """Register the four corner positions and border controls."""
        for priority, (name, default_x, default_y) in enumerate(self._DEFAULT_CORNERS):
            self.set_property(
                f"{name}_x",
                _corner_percent(default_x, priority * 2, f"{_corner_label(name)} X"),
            )
            self.set_property(
                f"{name}_y",
                _corner_percent(default_y, priority * 2 + 1, f"{_corner_label(name)} Y"),
            )
            self.expose_modulation_input(f"{name}_x")
            self.expose_modulation_input(f"{name}_y")
        self.set_property(
            "stabilize",
            toggle_property(
                False,
                priority=19,
                group="Border",
                label="Stabilize",
                description=(
                    "Solve the inverse warp (tracked quad back to a locked-off "
                    "frame) instead of forward — use this to stabilize a moving "
                    "surface before painting/roto-ing it, then turn it off and "
                    "warp the result forward again with the same tracked corners."
                ),
            ),
        )
        self.set_property(
            "border_mode",
            choice_property(
                TransformBorderMode.Black,
                priority=20,
                group="Border",
                label="Mode",
                description="How pixels beyond the warped quad are generated.",
            ),
        )
        self.set_property(
            "border_color",
            color_property(
                (0, 0, 0),
                priority=21,
                group="Border",
                label="Color",
                description="Fill color used by Black border mode.",
            ),
        )

    def _corner(self, name: str) -> tuple[float, float]:
        """Return one corner's ``(x, y)`` as 0-1 fractions of frame size."""
        return (
            self._corner_axis(f"{name}_x", 0.0),
            self._corner_axis(f"{name}_y", 0.0),
        )

    def _corner_axis(self, key: str, default_percent: float) -> float:
        """Resolve one corner axis to a 0–1 fraction (percent properties or wires)."""
        return self.float_value(key, default_percent) / 100.0

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply the perspective warp."""
        del frame_num
        border: TransformBorderMode = self.enum_value(
            "border_mode", TransformBorderMode, TransformBorderMode.Black
        )
        return corner_pin(
            frame,
            top_left=self._corner("top_left"),
            top_right=self._corner("top_right"),
            bottom_right=self._corner("bottom_right"),
            bottom_left=self._corner("bottom_left"),
            border_mode=border,
            border_color=self.color_value("border_color", (0, 0, 0)),
            stabilize=self.bool_value("stabilize", False),
        )


class CornerPinMaskNode(FrameNode):
    """Warp a mask so its four corners land at arbitrary tracked points.

    The mask-domain equivalent of ``CornerPinNode``. Lets a hand-drawn Roto
    shape "stick" to tracked motion: draw the shape once on a stabilized
    reference (see ``CornerPinNode``'s ``stabilize`` option), then warp it
    forward with the same tracked corners here so it follows the plate on
    every frame without being rotoscoped by hand.
    """

    node_type: str = "Corner Pin (Mask)"
    node_category: str = TRANSFORM_CATEGORY
    node_description: str = "Warp a mask's four corners to arbitrary tracked points"
    node_color: tuple[int, int, int] = (128, 108, 200)

    _DEFAULT_CORNERS: tuple[tuple[str, float, float], ...] = CornerPinNode._DEFAULT_CORNERS

    def _setup_sockets(self) -> None:
        """Register the mask sockets, four corner positions, and border controls."""
        self.add_input("mask", NodeSocketType.Mask)
        self.add_output("mask", NodeSocketType.Mask)
        for priority, (name, default_x, default_y) in enumerate(self._DEFAULT_CORNERS):
            self.set_property(
                f"{name}_x",
                _corner_percent(default_x, priority * 2, f"{_corner_label(name)} X"),
            )
            self.set_property(
                f"{name}_y",
                _corner_percent(default_y, priority * 2 + 1, f"{_corner_label(name)} Y"),
            )
            self.expose_modulation_input(f"{name}_x")
            self.expose_modulation_input(f"{name}_y")
        self.set_property(
            "stabilize",
            toggle_property(
                False,
                priority=19,
                group="Border",
                label="Stabilize",
                description="Solve the inverse warp instead of forward (rarely needed for masks).",
            ),
        )
        self.set_property(
            "border_mode",
            choice_property(
                TransformBorderMode.Black,
                priority=20,
                group="Border",
                label="Mode",
                description="How pixels beyond the warped quad are generated.",
            ),
        )

    def _corner(self, name: str) -> tuple[float, float]:
        """Return one corner's ``(x, y)`` as 0-1 fractions of frame size."""
        return (
            self.float_value(f"{name}_x", 0.0) / 100.0,
            self.float_value(f"{name}_y", 0.0) / 100.0,
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Warp the connected mask."""
        del frame_num
        source: np.ndarray | None = self.input_frame("mask")
        if source is None:
            return self.blank_frame()
        border: TransformBorderMode = self.enum_value(
            "border_mode", TransformBorderMode, TransformBorderMode.Black
        )
        return corner_pin(
            source,
            top_left=self._corner("top_left"),
            top_right=self._corner("top_right"),
            bottom_right=self._corner("bottom_right"),
            bottom_left=self._corner("bottom_left"),
            border_mode=border,
            border_color=(0, 0, 0),
            stabilize=self.bool_value("stabilize", False),
        )


class CropNode(FrameNode):
    """Crop independent percentages from each frame edge."""

    node_type: str = "Crop"
    node_category: str = TRANSFORM_CATEGORY
    node_description: str = (
        "Crop frame edges with optional resize back to project dimensions"
    )
    node_color: tuple[int, int, int] = (106, 112, 190)

    def _setup_sockets(self) -> None:
        """Register frame sockets and crop controls."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        for priority, key, label in (
            (10, "left", "Left"),
            (11, "right", "Right"),
            (12, "top", "Top"),
            (13, "bottom", "Bottom"),
        ):
            self.set_property(
                key,
                slider_property(
                    0,
                    0,
                    95,
                    priority=priority,
                    group="Crop",
                    label=label,
                    description=f"Percentage removed from the {label.lower()} edge.",
                    suffix="%",
                ),
            )
        self.set_property(
            "resize_to_frame",
            toggle_property(
                True,
                priority=20,
                group="Output",
                label="Resize to Frame",
                description="Scale the cropped area back to the input dimensions.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Crop the connected frame."""
        del frame_num
        source: np.ndarray | None = self.input_frame()
        if source is None:
            return self.blank_frame()
        return crop(
            source,
            left=self.float_value("left", 0.0) / 100.0,
            right=self.float_value("right", 0.0) / 100.0,
            top=self.float_value("top", 0.0) / 100.0,
            bottom=self.float_value("bottom", 0.0) / 100.0,
            resize_to_frame=self.bool_value("resize_to_frame", True),
        )

class ShearNode(FrameEffectNode):
    """Shear the frame horizontally or vertically."""

    node_type = "Shear"
    node_category = TRANSFORM_CATEGORY
    node_description = "Shear the frame horizontally or vertically"
    node_color = (140, 120, 200)

    def setup_effect_properties(self):
        self.set_property(
            "shear_x",
            slider_property(
                0, -1.0, 1.0,
                priority=10,
                group="Shear",
                label="Shear X",
                description="Horizontal shear amount",
            ),
        )
        self.set_property(
            "shear_y",
            slider_property(
                0, -1.0, 1.0,
                priority=11,
                group="Shear",
                label="Shear Y",
                description="Vertical shear amount",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        h, w = frame.shape[:2]
        sx = self.float_value("shear_x", 0.0)
        sy = self.float_value("shear_y", 0.0)

        M = np.array([[1, sx, 0],
                      [sy, 1, 0]], dtype=np.float32)

        return cv2.warpAffine(frame, M, (w, h), flags=cv2.INTER_LINEAR)

class PerspectiveNode(FrameEffectNode):
    """Apply a simple perspective warp."""

    node_type = "Perspective"
    node_category = TRANSFORM_CATEGORY
    node_description = "Simple perspective warp using tilt and skew"
    node_color = (150, 110, 210)

    def setup_effect_properties(self):
        self.set_property(
            "tilt",
            slider_property(
                0, -100.0, 100.0,
                priority=10,
                group="Perspective",
                label="Tilt",
                description="Vertical perspective tilt",
            ),
        )
        self.set_property(
            "skew",
            slider_property(
                0, -100.0, 100.0,
                priority=11,
                group="Perspective",
                label="Skew",
                description="Horizontal perspective skew",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        h, w = frame.shape[:2]
        tilt = self.float_value("tilt", 0.0) / 100.0
        skew = self.float_value("skew", 0.0) / 100.0

        # pyrefly: ignore [bad-argument-type]
        src: np.floating[np._32Bit] = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
        # pyrefly: ignore [bad-argument-type]
        dst: np.floating[np._32Bit]   = np.float32([
            [0 + skew * w, 0 + tilt * h],
            [w - skew * w, 0 + tilt * h],
            [0 - skew * w, h - tilt * h],
            [w + skew * w, h - tilt * h],
        ])

        # pyrefly: ignore [no-matching-overload]
        M = cv2.getPerspectiveTransform(src, dst)
        return cv2.warpPerspective(frame, M, (w, h))


def _corner_label(name: str) -> str:
    """Convert a corner property key into a display label."""
    return name.replace("_", " ").title()


def _corner_percent(value: float, priority: int, label: str) -> NodeProperty:
    """Create a percentage-of-frame-size property for one corner axis."""
    return number_property(
        value,
        -200.0,
        300.0,
        priority=priority,
        group="Corners",
        label=label,
        description=f"{label} as a percentage of frame size.",
        suffix="%",
    )


def _transform_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    description: str,
    suffix: str,
) -> NodeProperty:
    """Create a slider in the Transform section."""
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group="Transform",
        label=label,
        description=description,
        suffix=suffix,
    )

class SphericalWarpNode(FrameEffectNode):
    """Spherical distortion warp."""

    node_type = "Spherical Warp"
    node_category = TRANSFORM_CATEGORY
    node_description = "Spherical distortion for VR/fisheye effects"
    node_color = (130, 140, 200)

    def setup_effect_properties(self):
        self.set_property(
            "strength",
            slider_property(
                0.5, 0.0, 2.0,
                priority=10,
                group="Sphere",
                label="Strength",
                description="Spherical distortion strength",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        h, w = frame.shape[:2]
        strength = self.float_value("strength", 0.5)

        yy, xx = np.indices((h, w))
        cx, cy = w / 2, h / 2

        dx = (xx - cx) / cx
        dy = (yy - cy) / cy
        r = np.sqrt(dx * dx + dy * dy)

        factor = 1 + strength * (r * r)
        map_x = cx + dx * cx * factor
        map_y = cy + dy * cy * factor

        return cv2.remap(frame, map_x.astype(np.float32), map_y.astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

class PolarWarpNode(FrameEffectNode):
    """Polar coordinate warp."""

    node_type = "Polar Warp"
    node_category = TRANSFORM_CATEGORY
    node_description = "Convert frame to polar coordinates"
    node_color = (160, 130, 200)

    def setup_effect_properties(self):
        self.set_property(
            "reverse",
            toggle_property(
                False,
                priority=10,
                group="Polar",
                label="Reverse",
                description="Reverse polar transform",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        reverse = self.bool_value("reverse", False)
        flags = cv2.WARP_POLAR_LINEAR
        if reverse:
            flags |= cv2.WARP_INVERSE_MAP

        h, w = frame.shape[:2]
        center = (w / 2, h / 2)
        max_radius = min(center)

        return cv2.warpPolar(frame, (w, h), center, max_radius, flags)

class SwirlNode(FrameEffectNode):
    """Swirl distortion around a center point."""

    node_type = "Swirl"
    node_category = TRANSFORM_CATEGORY
    node_description = "Swirl distortion around a center point"
    node_color = (180, 100, 200)

    def setup_effect_properties(self):
        self.set_property(
            "angle",
            slider_property(
                180, -720, 720,
                priority=10,
                group="Swirl",
                label="Angle",
                description="Swirl rotation amount",
                suffix="°",
            ),
        )
        self.set_property(
            "radius",
            slider_property(
                200, 10, 2000,
                priority=11,
                group="Swirl",
                label="Radius",
                description="Swirl radius",
                suffix=" px",
            ),
        )

    def process_frame(self, frame, frame_num):
        del frame_num
        h, w = frame.shape[:2]
        angle = np.deg2rad(self.float_value("angle", 180))
        radius = self.float_value("radius", 200)

        yy, xx = np.indices((h, w))
        cx, cy = w / 2, h / 2

        dx = xx - cx
        dy = yy - cy
        r = np.sqrt(dx * dx + dy * dy)

        theta = np.arctan2(dy, dx) + angle * np.exp(-(r / radius)**2)

        map_x = cx + r * np.cos(theta)
        map_y = cy + r * np.sin(theta)

        return cv2.remap(frame, map_x.astype(np.float32), map_y.astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
