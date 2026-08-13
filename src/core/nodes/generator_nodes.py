"""Built-in procedural frame generator nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import WHITE_COLOR_RGB, NodeProperty, NodeSocketType
from core.nodes.enums import GradientMode
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import choice_property, color_property, slider_property
from effects.generators import checkerboard, color_bars, gradient, solid_color

GENERATOR_CATEGORY: str = "Generator"


class SolidColorNode(FrameNode):
    """Generate a constant RGB frame."""

    node_type: str = "Solid Color"
    node_category: str = GENERATOR_CATEGORY
    node_description: str = "Generate a project-sized frame filled with one color"
    node_color: tuple[int, int, int] = (148, 92, 170)

    def _setup_sockets(self) -> None:
        """Register output and fill color."""
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "color",
            color_property(
                (32, 32, 32),
                priority=0,
                group="Generator",
                label="Color",
                description="Solid output color.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Generate the requested frame."""
        del frame_num
        width: int
        height: int
        width, height = self.evaluation_frame_size()
        return solid_color(width, height, self.color_value("color", (32, 32, 32)))


class GradientNode(FrameNode):
    """Generate two-color linear or radial gradients."""

    node_type: str = "Gradient"
    node_category: str = GENERATOR_CATEGORY
    node_description: str = (
        "Generate horizontal, vertical, diagonal, or radial gradients"
    )
    node_color: tuple[int, int, int] = (154, 88, 176)

    def _setup_sockets(self) -> None:
        """Register output and gradient controls."""
        self.add_output("frame", NodeSocketType.Frame)
        self._setup_gradient_properties()
        self._setup_center_properties()

    def _setup_gradient_properties(self) -> None:
        """Register colors and gradient mode."""
        self.set_property(
            "start_color",
            color_property(
                (0, 0, 0),
                priority=10,
                group="Gradient",
                label="Start",
                description="Color at gradient origin.",
            ),
        )
        self.set_property(
            "end_color",
            color_property(
                WHITE_COLOR_RGB,
                priority=11,
                group="Gradient",
                label="End",
                description="Color at gradient destination.",
            ),
        )
        self.set_property(
            "mode",
            choice_property(
                GradientMode.Horizontal,
                priority=12,
                group="Gradient",
                label="Mode",
                description="Gradient direction or radial shape.",
            ),
        )

    def _setup_center_properties(self) -> None:
        """Register radial center controls."""
        self.set_property(
            "center_x",
            _generator_slider(
                50, 0, 100, 20, "Center X", "Radial center X position.", "%"
            ),
        )
        self.set_property(
            "center_y",
            _generator_slider(
                50, 0, 100, 21, "Center Y", "Radial center Y position.", "%"
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Generate the gradient frame."""
        del frame_num
        width: int
        height: int
        width, height = self.evaluation_frame_size()
        mode: GradientMode = self.enum_value(
            "mode", GradientMode, GradientMode.Horizontal
        )
        return gradient(
            width,
            height,
            start_color=self.color_value("start_color", (0, 0, 0)),
            end_color=self.color_value("end_color", WHITE_COLOR_RGB),
            mode=mode,
            center_x=self.float_value("center_x", 50.0) / 100.0,
            center_y=self.float_value("center_y", 50.0) / 100.0,
        )


class CheckerboardNode(FrameNode):
    """Generate a configurable checkerboard."""

    node_type: str = "Checkerboard"
    node_category: str = GENERATOR_CATEGORY
    node_description: str = "Generate a two-color checkerboard reference frame"
    node_color: tuple[int, int, int] = (142, 90, 166)

    def _setup_sockets(self) -> None:
        """Register output and checker controls."""
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "color_a",
            color_property(
                (48, 48, 48),
                priority=10,
                group="Checkerboard",
                label="Color A",
                description="First checker color.",
            ),
        )
        self.set_property(
            "color_b",
            color_property(
                (96, 96, 96),
                priority=11,
                group="Checkerboard",
                label="Color B",
                description="Second checker color.",
            ),
        )
        self.set_property(
            "cell_size",
            _generator_slider(64, 2, 512, 12, "Cell Size", "Checker cell size.", " px"),
        )
        self.set_property(
            "offset_x",
            _generator_slider(
                0, -512, 512, 20, "Offset X", "Horizontal pattern offset.", " px"
            ),
        )
        self.set_property(
            "offset_y",
            _generator_slider(
                0, -512, 512, 21, "Offset Y", "Vertical pattern offset.", " px"
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Generate the checkerboard frame."""
        del frame_num
        width: int
        height: int
        width, height = self.evaluation_frame_size()
        return checkerboard(
            width,
            height,
            color_a=self.color_value("color_a", (48, 48, 48)),
            color_b=self.color_value("color_b", (96, 96, 96)),
            cell_size=self.int_value("cell_size", 64),
            offset_x=self.int_value("offset_x", 0),
            offset_y=self.int_value("offset_y", 0),
        )


class ColorBarsNode(FrameNode):
    """Generate standard seven-bar reference colors."""

    node_type: str = "Color Bars"
    node_category: str = GENERATOR_CATEGORY
    node_description: str = "Generate standard 75% intensity color bars"
    node_color: tuple[int, int, int] = (154, 94, 168)

    def _setup_sockets(self) -> None:
        """Register frame output."""
        self.add_output("frame", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Generate the color-bar frame."""
        del frame_num
        width: int
        height: int
        width, height = self.evaluation_frame_size()
        return color_bars(width, height)


def _generator_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    description: str,
    suffix: str,
) -> NodeProperty:
    """Create a generator slider."""
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group="Position",
        label=label,
        description=description,
        suffix=suffix,
    )
