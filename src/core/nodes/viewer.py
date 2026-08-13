"""Viewer node — preview sink with playback/display settings."""

from __future__ import annotations

import numpy as np

from config.constants import DEFAULT_PREVIEW_MAX_WIDTH
from core.nodes.base import Node, NodeProperty, NodePropertyInputType, NodeSocketType
from render.preview import ViewerBackground, ViewportFitMode


class ViewerNode(Node):
    """Connects to an input source to view a video stream."""

    node_type = "Viewer"
    node_category = "Input/Output"
    node_description = "Connects to an input source to view a video stream"
    node_color = (200, 50, 50)

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)
        self.set_property(
            "enabled",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=0,
                group="Display",
                label="Enabled",
                description="Show the connected frame in the viewport.",
            ),
        )
        self.set_property(
            "fit_mode",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=ViewportFitMode.Fit,
                priority=10,
                group="Display",
                label="Fit",
                description="How the frame is fitted inside the viewport.",
            ),
        )
        self.set_property(
            "preview_max_width",
            NodeProperty(
                input_type=NodePropertyInputType.Slider,
                value=DEFAULT_PREVIEW_MAX_WIDTH,
                slider_min_value=320,
                slider_max_value=1920,
                priority=20,
                group="Performance",
                label="Proxy Width",
                description="Maximum decode width used for interactive preview.",
                suffix=" px",
            ),
        )
        self.set_property(
            "apply_exposure",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=30,
                group="Display Transform",
                label="Apply Exposure",
                description="Apply the viewer-only exposure multiplier.",
            ),
        )
        self.set_property(
            "exposure",
            NodeProperty(
                input_type=NodePropertyInputType.Slider,
                value=100,
                slider_min_value=25,
                slider_max_value=200,
                priority=31,
                group="Display Transform",
                label="Exposure",
                description="Viewer-only display gain.",
                suffix="%",
            ),
        )
        self.set_property(
            "flip_horizontal",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=False,
                priority=40,
                group="Display Transform",
                label="Flip H",
                description="Mirror the preview horizontally.",
            ),
        )
        self.set_property(
            "flip_vertical",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=False,
                priority=41,
                group="Display Transform",
                label="Flip V",
                description="Mirror the preview vertically.",
            ),
        )
        self.set_property(
            "background",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=ViewerBackground.Black,
                priority=50,
                group="Display",
                label="Background",
                description="Viewport background behind the displayed frame.",
            ),
        )
        self.set_property(
            "prefetch_frames",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=2,
                slider_min_value=0,
                slider_max_value=6,
                priority=60,
                group="Performance",
                label="Prefetch",
                description="Frames requested ahead during playback.",
                suffix=" fr",
            ),
        )

    def _bool_prop(self, key: str, default: bool) -> bool:
        prop = self.get_property(key)
        if prop is None or prop.value is None:
            return default
        return bool(prop.value)

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Return the connected frame with optional exposure / flips."""
        del frame_num
        if not self._bool_prop("enabled", True):
            return self.blank_frame()

        input_frame: object | None = self.get_input_value("frame")
        if not isinstance(input_frame, np.ndarray):
            return self.blank_frame()

        frame: np.ndarray = input_frame
        if self._bool_prop("flip_horizontal", False):
            frame = np.ascontiguousarray(np.fliplr(frame))
        if self._bool_prop("flip_vertical", False):
            frame = np.ascontiguousarray(np.flipud(frame))

        if not self._bool_prop("apply_exposure", True):
            return frame

        exposure_prop = self.get_property("exposure")
        if exposure_prop is None or exposure_prop.value is None:
            return frame

        gain = float(exposure_prop.value) / 100.0
        if abs(gain - 1.0) < 0.001:
            return frame

        adjusted: np.ndarray = frame * np.float32(gain)
        return adjusted
