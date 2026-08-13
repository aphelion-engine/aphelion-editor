"""Still image input node — load a PNG/JPG/etc. as a Frame plus alpha Mask.

Meant for overlays (logos, watermarks, lower-thirds, graphics): the decoded
image's alpha channel (or full opacity, if the file has none) is exposed as
a second output so it drops straight into a ``Merge`` node's mask input
without any extra keying step.
"""

from __future__ import annotations

import os

import cv2
import numpy as np

from core.nodes.base import NodeSocketType, NodeValue
from core.nodes.enums import ImageFitMode
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import choice_property, image_file_property, number_property
from effects.image_placement import place_image


class ImageInputNode(FrameNode):
    """Load a still image and place it on a Frame + Mask output pair."""

    node_type: str = "Image Input"
    node_category: str = "Input/Output"
    node_description: str = "Load a still image (PNG/JPG/...) as a Frame with an alpha Mask"
    node_color: tuple[int, int, int] = (60, 150, 132)

    def __init__(self, name: str | None = None) -> None:
        self._cached_path: str | None = None
        self._cached_rgba: np.ndarray | None = None
        super().__init__(name)

    def _setup_sockets(self) -> None:
        """Register the Frame/Mask outputs and placement controls."""
        self.add_output("frame", NodeSocketType.Frame)
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property(
            "file_path",
            image_file_property(
                "",
                priority=0,
                group="Source",
                label="File",
                description="Still image decoded by this source node.",
            ),
        )
        self.set_property(
            "fit_mode",
            choice_property(
                ImageFitMode.Fit,
                priority=10,
                group="Placement",
                label="Fit",
                description=(
                    "Fit: contain, transparent padding. Fill: crop to fill. "
                    "Stretch: fill exactly, aspect ignored. Native: no scaling."
                ),
            ),
        )
        self.set_property(
            "scale",
            number_property(
                100.0,
                1.0,
                1000.0,
                priority=11,
                group="Placement",
                label="Scale",
                description="Additional scale applied on top of Fit.",
                suffix="%",
            ),
        )
        self.set_property(
            "position_x",
            number_property(
                0.0,
                -200.0,
                200.0,
                priority=12,
                group="Placement",
                label="Position X",
                description="Horizontal offset from center, as a percent of frame width.",
                suffix="%",
            ),
        )
        self.set_property(
            "position_y",
            number_property(
                0.0,
                -200.0,
                200.0,
                priority=13,
                group="Placement",
                label="Position Y",
                description="Vertical offset from center, as a percent of frame height.",
                suffix="%",
            ),
        )
        for key in ("scale", "position_x", "position_y"):
            self.expose_modulation_input(key)

    def _load_native_rgba(self, path: str) -> np.ndarray | None:
        """Decode ``path`` into a float32 ``HxWx4`` RGBA array, cached by path."""
        if path == self._cached_path and self._cached_rgba is not None:
            return self._cached_rgba
        self._cached_path = None
        self._cached_rgba = None
        if not path or not os.path.isfile(path):
            return None

        raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if raw is None:
            return None

        if raw.dtype == np.uint16:
            raw = (raw.astype(np.float32) * (255.0 / 65535.0)).astype(np.uint8)

        if raw.ndim == 2:
            bgra = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGRA)
        elif raw.shape[2] == 3:
            bgra = cv2.cvtColor(raw, cv2.COLOR_BGR2BGRA)
        else:
            bgra = raw

        rgba_u8 = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
        rgba_f32 = rgba_u8.astype(np.float32) * np.float32(1.0 / 255.0)
        self._cached_path = path
        self._cached_rgba = rgba_f32
        return rgba_f32

    def evaluate(self, frame_num: int) -> NodeValue:
        """Place the loaded image (or a transparent blank) onto the canvas."""
        del frame_num
        path = self.string_value("file_path", "")
        rgba = self._load_native_rgba(path) if path else None
        if rgba is None:
            blank = self.blank_frame()
            return {"frame": blank, "mask": blank.copy()}

        fit_mode = self.enum_value("fit_mode", ImageFitMode, ImageFitMode.Fit)
        canvas_width, canvas_height = self.evaluation_frame_size()
        frame, mask = place_image(
            rgba,
            canvas_width,
            canvas_height,
            fit_mode=fit_mode,
            scale=self.float_value("scale", 100.0) / 100.0,
            offset_x=self.float_value("position_x", 0.0) / 100.0,
            offset_y=self.float_value("position_y", 0.0) / 100.0,
        )
        return {"frame": frame, "mask": mask}
