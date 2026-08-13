"""Built-in blur, detail, edge, and stylization filter nodes."""

from __future__ import annotations

import numpy as np

from core.nodes.base import NodeProperty
from core.nodes.enums import EdgeDisplayMode
from core.nodes.frame_base import FrameEffectNode
from core.nodes.property_factory import choice_property, color_property, slider_property
from effects.filters import (
    bilateral_denoise,
    edge_detect,
    gaussian_blur,
    motion_blur,
    pixelate,
    unsharp_mask,
    vignette,
)

FILTER_CATEGORY: str = "Filter"


class GaussianBlurNode(FrameEffectNode):
    """Gaussian spatial blur."""

    node_type: str = "Gaussian Blur"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Smooth detail with a Gaussian kernel"
    node_color: tuple[int, int, int] = (72, 132, 190)

    def setup_effect_properties(self) -> None:
        """Register blur controls."""
        self.set_property(
            "radius",
            _filter_slider(8, 0, 50, 10, "Radius", "Kernel radius in pixels.", " px"),
        )
        self.set_property(
            "sigma",
            _filter_slider(
                0, 0, 100, 11, "Sigma", "Gaussian sigma; zero selects automatic.", ""
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Blur the source frame."""
        del frame_num
        return gaussian_blur(
            frame,
            radius=self.int_value("radius", 8),
            sigma=self.float_value("sigma", 0.0) / 10.0,
        )


class SharpenNode(FrameEffectNode):
    """Thresholded unsharp-mask detail enhancement."""

    node_type: str = "Sharpen"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Enhance detail using thresholded unsharp masking"
    node_color: tuple[int, int, int] = (64, 148, 178)

    def setup_effect_properties(self) -> None:
        """Register sharpening controls."""
        self.set_property(
            "amount",
            _filter_slider(
                100, 0, 500, 10, "Amount", "Strength of the unsharp detail.", "%"
            ),
        )
        self.set_property(
            "radius",
            _filter_slider(2, 1, 20, 11, "Radius", "Detail radius in pixels.", " px"),
        )
        self.set_property(
            "threshold",
            _filter_slider(
                3,
                0,
                64,
                12,
                "Threshold",
                "Ignore low-contrast noise below this delta.",
                "",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Sharpen the source frame."""
        del frame_num
        return unsharp_mask(
            frame,
            amount=self.float_value("amount", 100.0) / 100.0,
            radius=self.int_value("radius", 2),
            threshold=self.int_value("threshold", 3),
        )


class DenoiseNode(FrameEffectNode):
    """Edge-preserving bilateral denoise."""

    node_type: str = "Bilateral Denoise"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Reduce noise while preserving strong edges"
    node_color: tuple[int, int, int] = (72, 146, 150)

    def setup_effect_properties(self) -> None:
        """Register denoise controls."""
        self.set_property(
            "diameter",
            _filter_slider(5, 1, 15, 10, "Radius", "Neighborhood diameter.", " px"),
        )
        self.set_property(
            "color_sigma",
            _filter_slider(
                40, 1, 200, 11, "Color Sigma", "Color similarity tolerance.", ""
            ),
        )
        self.set_property(
            "space_sigma",
            _filter_slider(
                40, 1, 200, 12, "Space Sigma", "Spatial similarity tolerance.", ""
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Denoise the source frame."""
        del frame_num
        return bilateral_denoise(
            frame,
            diameter=self.int_value("diameter", 5),
            color_sigma=self.float_value("color_sigma", 40.0),
            space_sigma=self.float_value("space_sigma", 40.0),
        )


class EdgeDetectNode(FrameEffectNode):
    """Configurable Canny edge detector."""

    node_type: str = "Edge Detect"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Extract high-contrast edges with Canny thresholds"
    node_color: tuple[int, int, int] = (76, 154, 174)

    def setup_effect_properties(self) -> None:
        """Register edge detector controls."""
        self.set_property(
            "low_threshold",
            _filter_slider(60, 0, 255, 10, "Low", "Lower hysteresis threshold.", ""),
        )
        self.set_property(
            "high_threshold",
            _filter_slider(140, 1, 255, 11, "High", "Upper hysteresis threshold.", ""),
        )
        self.set_property(
            "display",
            choice_property(
                EdgeDisplayMode.WhiteOnBlack,
                priority=12,
                group="Edge",
                label="Display",
                description="Presentation of the extracted edge map.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Extract source-frame edges."""
        del frame_num
        display: EdgeDisplayMode = self.enum_value(
            "display", EdgeDisplayMode, EdgeDisplayMode.WhiteOnBlack
        )
        return edge_detect(
            frame,
            low_threshold=self.int_value("low_threshold", 60),
            high_threshold=self.int_value("high_threshold", 140),
            display=display,
        )


class PixelateNode(FrameEffectNode):
    """Block-based pixelation."""

    node_type: str = "Pixelate"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Reduce spatial resolution into hard pixel blocks"
    node_color: tuple[int, int, int] = (92, 122, 184)

    def setup_effect_properties(self) -> None:
        """Register pixel block size."""
        self.set_property(
            "block_size",
            _filter_slider(
                16, 1, 256, 10, "Block Size", "Square pixel block size.", " px"
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Pixelate the source frame."""
        del frame_num
        return pixelate(frame, block_size=self.int_value("block_size", 16))


class VignetteNode(FrameEffectNode):
    """Soft colored edge vignette."""

    node_type: str = "Vignette"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Darken or tint frame edges with a soft radial mask"
    node_color: tuple[int, int, int] = (88, 96, 156)

    def setup_effect_properties(self) -> None:
        """Register vignette controls."""
        self.set_property(
            "strength",
            _filter_slider(
                55, 0, 100, 10, "Strength", "Opacity at the outer corners.", "%"
            ),
        )
        self.set_property(
            "softness",
            _filter_slider(
                60, 5, 100, 11, "Softness", "Width of the edge transition.", "%"
            ),
        )
        self.set_property(
            "color",
            color_property(
                (0, 0, 0),
                priority=12,
                group="Vignette",
                label="Color",
                description="Color blended into the edges.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply the vignette."""
        del frame_num
        return vignette(
            frame,
            amount=self.float_value("strength", 55.0) / 100.0,
            softness=self.float_value("softness", 60.0) / 100.0,
            color=self.color_value("color", (0, 0, 0)),
        )


class MotionBlurNode(FrameEffectNode):
    """Directional linear blur simulating motion."""

    node_type: str = "Motion Blur"
    node_category: str = FILTER_CATEGORY
    node_description: str = "Simulate directional motion blur along an angle"
    node_color: tuple[int, int, int] = (80, 138, 186)

    def setup_effect_properties(self) -> None:
        """Register angle and distance controls."""
        self.set_property(
            "angle",
            _filter_slider(0, -180, 180, 10, "Angle", "Blur direction.", "°"),
        )
        self.set_property(
            "distance",
            _filter_slider(
                12, 1, 200, 11, "Distance", "Blur streak length in pixels.", " px"
            ),
        )
        self.expose_modulation_input("angle")
        self.expose_modulation_input("distance")

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Apply directional motion blur."""
        del frame_num
        return motion_blur(
            frame,
            angle_degrees=self.float_value("angle", 0.0),
            distance=self.int_value("distance", 12),
        )


def _filter_slider(
    value: int,
    minimum: int,
    maximum: int,
    priority: int,
    label: str,
    description: str,
    suffix: str,
) -> NodeProperty:
    """Create a slider in the filter's primary section."""
    return slider_property(
        value,
        minimum,
        maximum,
        priority=priority,
        group="Filter",
        label=label,
        description=description,
        suffix=suffix,
    )
