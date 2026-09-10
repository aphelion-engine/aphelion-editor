"""Depth-based and pseudo-3D compositing nodes."""

from __future__ import annotations

import cv2
import numpy as np
from core.nodes.base import NodeSocketType
from core.nodes.enums import AnaglyphMode, ZMergeMode
from core.nodes.frame_base import FrameEffectNode, FrameNode
from core.nodes.property_factory import (choice_property, color_property,
                                         slider_property, toggle_property)
from effects.depth import (anaglyph, depth_haze, depth_of_field, depth_relight,
                           depth_slice)

DEPTH_CATEGORY = "Depth"


# ------------------------------------------------------------
# 1. ZCompositeNode — depth-aware compositing
# ------------------------------------------------------------

class ZCompositeNode(FrameNode):
    """Composite foreground and background based on depth."""

    node_type = "Z Composite"
    node_category = DEPTH_CATEGORY
    node_description = "Composite layers using depth maps for occlusion"
    node_color = (120, 160, 200)

    def _setup_sockets(self):
        self.add_input("background", NodeSocketType.Frame)
        self.add_input("foreground", NodeSocketType.Frame)
        self.add_input("depth_bg", NodeSocketType.Frame)
        self.add_input("depth_fg", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "softness",
            slider_property(
                0.02, 0.0, 0.5,
                priority=10,
                group="Depth",
                label="Softness",
                description="Soft depth blending",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        bg = self.input_frame("background")
        fg = self.input_frame("foreground")
        db = self.input_frame("depth_bg")
        df = self.input_frame("depth_fg")

        if bg is None:
            return fg if fg is not None else self.blank_frame()
        if fg is None:
            return bg

        if db is None or df is None:
            return fg

        softness = self.float_value("softness", 0.02)

        db = db[..., 0].astype(np.float32)
        df = df[..., 0].astype(np.float32)

        mask = 1.0 / (1.0 + np.exp((df - db) / softness))
        mask = np.clip(mask, 0, 1)

        out = fg[..., :3] * mask + bg[..., :3] * (1 - mask)
        return out


# ------------------------------------------------------------
# 2. ZMergeNode — merge depth maps
# ------------------------------------------------------------

class ZMergeNode(FrameNode):
    """Merge two depth maps."""

    node_type = "Z Merge"
    node_category = DEPTH_CATEGORY
    node_description = "Combine depth maps using min/max/avg"
    node_color = (140, 160, 180)

    def _setup_sockets(self):
        self.add_input("a", NodeSocketType.Frame)
        self.add_input("b", NodeSocketType.Frame)
        self.add_output("depth", NodeSocketType.Frame)

        self.set_property(
            "mode",
            choice_property(
                # pyrefly: ignore [bad-argument-type]
                ZMergeMode,
                priority=10,
                group="Depth",
                label="Mode",
                description="Depth merge mode",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        a = self.input_frame("a")
        b = self.input_frame("b")

        if a is None:
            return b if b is not None else self.blank_frame()
        if b is None:
            return a

        da = a[..., 0]
        db = b[..., 0]

        mode = self.get_property("mode")

        if mode == ZMergeMode.Min:
            out = np.minimum(da, db)
        elif mode == ZMergeMode.Max:
            out = np.maximum(da, db)
        else:
            out = (da + db) * 0.5

        return out[..., None]


# ------------------------------------------------------------
# 3. ZMaskNode — depth-based matte
# ------------------------------------------------------------

class ZMaskNode(FrameNode):
    """Generate matte from depth range."""

    node_type = "Z Mask"
    node_category = DEPTH_CATEGORY
    node_description = "Create matte from depth range"
    node_color = (160, 140, 200)

    def _setup_sockets(self):
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("mask", NodeSocketType.Mask)

        self.set_property(
            "near",
            slider_property(
                0.2, 0.0, 1.0,
                priority=10,
                group="Mask",
                label="Near",
                description="Near depth threshold",
            ),
        )
        self.set_property(
            "far",
            slider_property(
                0.8, 0.0, 1.0,
                priority=11,
                group="Mask",
                label="Far",
                description="Far depth threshold",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        d = self.input_frame("depth")
        if d is None:
            return self.blank_frame()

        near = self.float_value("near", 0.2)
        far = self.float_value("far", 0.8)

        z = d[..., 0]
        mask = np.clip((z - near) / (far - near), 0, 1)
        return mask[..., None]


# ------------------------------------------------------------
# 4. DepthParallaxNode — fake camera movement
# ------------------------------------------------------------

class DepthParallaxNode(FrameNode):
    """Simulate camera parallax using depth."""

    node_type = "Depth Parallax"
    node_category = DEPTH_CATEGORY
    node_description = "Fake camera movement using depth"
    node_color = (180, 140, 160)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "shift_x",
            slider_property(
                0, -200, 200,
                priority=10,
                group="Parallax",
                label="Shift X",
                description="Horizontal camera shift",
                suffix=" px",
            ),
        )
        self.set_property(
            "shift_y",
            slider_property(
                0, -200, 200,
                priority=11,
                group="Parallax",
                label="Shift Y",
                description="Vertical camera shift",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        f = self.input_frame("frame")
        d = self.input_frame("depth")
        if f is None or d is None:
            return self.blank_frame()

        h, w = f.shape[:2]
        sx = self.float_value("shift_x", 0)
        sy = self.float_value("shift_y", 0)

        depth = d[..., 0].astype(np.float32)
        xx, yy = np.meshgrid(np.arange(w), np.arange(h))

        map_x = xx + depth * sx
        map_y = yy + depth * sy

        return cv2.remap(f, map_x.astype(np.float32), map_y.astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ------------------------------------------------------------
# 5. DepthDisplaceNode — depth-based displacement
# ------------------------------------------------------------

class DepthDisplaceNode(FrameNode):
    """Displace pixels based on depth."""

    node_type = "Depth Displace"
    node_category = DEPTH_CATEGORY
    node_description = "Displace pixels using depth map"
    node_color = (200, 140, 140)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "strength",
            slider_property(
                20, 0, 200,
                priority=10,
                group="Displace",
                label="Strength",
                description="Displacement intensity",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        f = self.input_frame("frame")
        d = self.input_frame("depth")
        if f is None or d is None:
            return self.blank_frame()

        h, w = f.shape[:2]
        strength = self.float_value("strength", 20)

        depth = d[..., 0].astype(np.float32)
        xx, yy = np.meshgrid(np.arange(w), np.arange(h))

        map_x = xx + depth * strength
        map_y = yy + depth * strength * 0.5

        return cv2.remap(f, map_x.astype(np.float32), map_y.astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ------------------------------------------------------------
# 6. ZFogAdvancedNode — advanced fog
# ------------------------------------------------------------

class ZFogAdvancedNode(FrameNode):
    """Depth-based fog with color and noise."""

    node_type = "Z Fog (Advanced)"
    node_category = DEPTH_CATEGORY
    node_description = "Depth fog with noise modulation"
    node_color = (160, 180, 200)

    def _setup_sockets(self):
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "density",
            slider_property(
                50, 0, 200,
                priority=10,
                group="Fog",
                label="Density",
                description="Fog strength",
                suffix="%",
            ),
        )
        self.set_property(
            "color",
            color_property(
                (200, 200, 200),
                priority=11,
                group="Fog",
                label="Color",
                description="Fog tint",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        d = self.input_frame("depth")
        if d is None:
            return self.blank_frame()

        density = self.float_value("density", 50) / 100.0
        color = np.array(self.color_value("color", (200, 200, 200))) / 255.0

        z = d[..., 0].astype(np.float32)
        fog = np.clip(z * density, 0, 1)

        return fog[..., None] * color


# ------------------------------------------------------------
# 7. ZGlowAdvancedNode — glow based on depth
# ------------------------------------------------------------

class ZGlowAdvancedNode(FrameNode):
    """Glow that increases with depth."""

    node_type = "Z Glow"
    node_category = DEPTH_CATEGORY
    node_description = "Glow intensity increases with depth"
    node_color = (200, 160, 180)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "strength",
            slider_property(
                1.0, 0.0, 5.0,
                priority=10,
                group="Glow",
                label="Strength",
                description="Glow multiplier",
            ),
        )
        self.set_property(
            "radius",
            slider_property(
                12, 1, 64,
                priority=11,
                group="Glow",
                label="Radius",
                description="Blur radius",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        f = self.input_frame("frame")
        d = self.input_frame("depth")
        if f is None or d is None:
            return self.blank_frame()

        strength = self.float_value("strength", 1.0)
        radius = int(self.float_value("radius", 12))

        depth = d[..., 0].astype(np.float32)
        glow = cv2.GaussianBlur(depth, (0, 0), radius)
        glow = glow[..., None] * strength

        return np.clip(f[..., :3] + glow, 0, 1)


# ------------------------------------------------------------
# 8. DepthTiltShiftNode — depth-based blur
# ------------------------------------------------------------

class DepthTiltShiftNode(FrameNode):
    """Tilt-shift blur based on depth."""

    node_type = "Depth Tilt Shift"
    node_category = DEPTH_CATEGORY
    node_description = "Blur based on depth range"
    node_color = (180, 180, 160)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "blur_near",
            slider_property(
                0, 0, 64,
                priority=10,
                group="Blur",
                label="Near Blur",
                description="Blur for near objects",
                suffix=" px",
            ),
        )
        self.set_property(
            "blur_far",
            slider_property(
                32, 0, 64,
                priority=11,
                group="Blur",
                label="Far Blur",
                description="Blur for far objects",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        f = self.input_frame("frame")
        d = self.input_frame("depth")
        if f is None or d is None:
            return self.blank_frame()

        bn = int(self.float_value("blur_near", 0))
        bf = int(self.float_value("blur_far", 32))

        # A zero blur means "do not blur", not an error. With
        # ``ksize=(0, 0)`` OpenCV derives the kernel size from sigma and
        # asserts on sigma <= 0, so the default Near Blur of 0 used to raise
        # on every frame. Skipping the pass is both correct and free.
        if bn <= 0 and bf <= 0:
            return f[..., :3]

        depth = d[..., 0].astype(np.float32)

        near_blur = f if bn <= 0 else cv2.GaussianBlur(f, (0, 0), bn)
        far_blur = f if bf <= 0 else cv2.GaussianBlur(f, (0, 0), bf)

        mask = depth[..., None]
        return near_blur * (1 - mask) + far_blur * mask


# ------------------------------------------------------------
# 9. DepthRimLightNode — rim light from depth gradient
# ------------------------------------------------------------

class DepthRimLightNode(FrameNode):
    """Rim light based on depth gradient."""

    node_type = "Depth Rim Light"
    node_category = DEPTH_CATEGORY
    node_description = "Add rim light using depth gradient"
    node_color = (200, 140, 200)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "strength",
            slider_property(
                1.0, 0.0, 5.0,
                priority=10,
                group="Rim",
                label="Strength",
                description="Rim light intensity",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        f = self.input_frame("frame")
        d = self.input_frame("depth")
        if f is None or d is None:
            return self.blank_frame()

        depth = d[..., 0].astype(np.float32)
        grad = cv2.Laplacian(depth, cv2.CV_32F)
        rim = np.clip(grad, 0, 1)[..., None] * self.float_value("strength", 1.0)

        return np.clip(f[..., :3] + rim, 0, 1)


# ------------------------------------------------------------
# 10. DepthEdgeNode — depth discontinuity edges
# ------------------------------------------------------------

class DepthEdgeNode(FrameNode):
    """Detect edges based on depth discontinuities."""

    node_type = "Depth Edge"
    node_category = DEPTH_CATEGORY
    node_description = "Detect edges from depth discontinuities"
    node_color = (160, 120, 200)

    def _setup_sockets(self):
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("mask", NodeSocketType.Mask)

        self.set_property(
            "strength",
            slider_property(
                1.0, 0.0, 5.0,
                priority=10,
                group="Edge",
                label="Strength",
                description="Edge intensity",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        d = self.input_frame("depth")
        if d is None:
            return self.blank_frame()

        depth = d[..., 0].astype(np.float32)
        edges = cv2.Canny((depth * 255).astype(np.uint8), 40, 120).astype(np.float32) / 255.0
        edges *= self.float_value("strength", 1.0)

        return edges[..., None]


# ------------------------------------------------------------
# 11. DepthOfFieldNode — depth-driven defocus
# ------------------------------------------------------------

class DepthOfFieldNode(FrameEffectNode):
    """Defocus the frame based on distance from a focal plane."""

    node_type = "Depth of Field"
    node_category = DEPTH_CATEGORY
    node_description = "Depth-driven defocus with a controllable focal plane"
    node_color = (108, 152, 212)

    def setup_effect_properties(self) -> None:
        """Add the depth input and register the focus controls."""
        self.add_input("depth", NodeSocketType.Frame)
        self.set_property(
            "focus",
            slider_property(
                50, 0, 100,
                priority=10,
                group="Focus",
                label="Focus",
                description="Depth value that stays sharp.",
                suffix="%",
            ),
        )
        self.set_property(
            "focus_range",
            slider_property(
                25, 1, 100,
                priority=11,
                group="Focus",
                label="Focus Range",
                description="Depth span that remains in focus.",
                suffix="%",
            ),
        )
        self.set_property(
            "max_blur",
            slider_property(
                12, 1, 64,
                priority=12,
                group="Focus",
                label="Max Blur",
                description="Blur applied to the most out-of-focus pixels.",
                suffix=" px",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=13,
                group="Depth",
                label="Invert Depth",
                description="Treat dark depth pixels as near instead of far.",
            ),
        )
        # Keyframe or modulate Focus for a rack focus between subjects.
        self.expose_modulation_input("focus")
        self.expose_modulation_input("max_blur")

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the defocused frame, or the source when depth is unwired."""
        del frame_num
        depth: np.ndarray | None = self.input_frame("depth")
        if depth is None:
            return frame
        return depth_of_field(
            frame,
            depth,
            focus=self.float_value("focus", 50.0) / 100.0,
            focus_range=self.float_value("focus_range", 25.0) / 100.0,
            max_blur=self.float_value("max_blur", 12.0),
            invert=self.bool_value("invert", False),
        )


# ------------------------------------------------------------
# 12. DepthHazeNode — atmospheric perspective
# ------------------------------------------------------------

class DepthHazeNode(FrameEffectNode):
    """Fade distant pixels toward an atmospheric color."""

    node_type = "Depth Haze"
    node_category = DEPTH_CATEGORY
    node_description = "Depth-based atmospheric haze for aerial perspective"
    node_color = (150, 172, 200)

    def setup_effect_properties(self) -> None:
        """Add the depth input and register the haze controls."""
        self.add_input("depth", NodeSocketType.Frame)
        self.set_property(
            "near",
            slider_property(
                40, 0, 100,
                priority=10,
                group="Atmosphere",
                label="Near",
                description="Depth where haze starts.",
                suffix="%",
            ),
        )
        self.set_property(
            "far",
            slider_property(
                100, 0, 100,
                priority=11,
                group="Atmosphere",
                label="Far",
                description="Depth where haze reaches full density.",
                suffix="%",
            ),
        )
        self.set_property(
            "color",
            color_property(
                (170, 190, 210),
                priority=12,
                group="Atmosphere",
                label="Color",
                description="Color distant pixels fade toward.",
            ),
        )
        self.set_property(
            "density",
            slider_property(
                60, 0, 100,
                priority=13,
                group="Atmosphere",
                label="Density",
                description="Maximum haze opacity.",
                suffix="%",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=14,
                group="Depth",
                label="Invert Depth",
                description="Treat dark depth pixels as near instead of far.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the hazed frame, or the source when depth is unwired."""
        del frame_num
        depth: np.ndarray | None = self.input_frame("depth")
        if depth is None:
            return frame
        return depth_haze(
            frame,
            depth,
            near=self.float_value("near", 40.0) / 100.0,
            far=self.float_value("far", 100.0) / 100.0,
            color=self.color_value("color", (170, 190, 210)),
            density=self.float_value("density", 60.0) / 100.0,
            invert=self.bool_value("invert", False),
        )


# ------------------------------------------------------------
# 13. DepthRelightNode — 2.5D relighting
# ------------------------------------------------------------

class DepthRelightNode(FrameEffectNode):
    """Relight the frame with surface normals recovered from depth."""

    node_type = "Depth Relight"
    node_category = DEPTH_CATEGORY
    node_description = "2.5D relighting from depth-derived surface normals"
    node_color = (200, 160, 112)

    def setup_effect_properties(self) -> None:
        """Add the depth input and register the lighting controls."""
        self.add_input("depth", NodeSocketType.Frame)
        self.set_property(
            "light_x",
            slider_property(
                -50, -100, 100,
                priority=10,
                group="Light",
                label="Light X",
                description="Horizontal light direction.",
                suffix="%",
            ),
        )
        self.set_property(
            "light_y",
            slider_property(
                -65, -100, 100,
                priority=11,
                group="Light",
                label="Light Y",
                description="Vertical light direction.",
                suffix="%",
            ),
        )
        self.set_property(
            "relief",
            slider_property(
                300, 5, 2000,
                priority=12,
                group="Surface",
                label="Relief",
                description="Steepness of the recovered surface.",
            ),
        )
        self.set_property(
            "strength",
            slider_property(
                100, 0, 300,
                priority=13,
                group="Light",
                label="Strength",
                description="Intensity of the relighting.",
                suffix="%",
            ),
        )
        self.set_property(
            "ambient",
            slider_property(
                20, 0, 100,
                priority=14,
                group="Light",
                label="Ambient",
                description="Fill light in shadowed areas.",
                suffix="%",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=15,
                group="Depth",
                label="Invert Depth",
                description="Treat dark depth pixels as near instead of far.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the relit frame, or the source when depth is unwired."""
        del frame_num
        depth: np.ndarray | None = self.input_frame("depth")
        if depth is None:
            return frame
        return depth_relight(
            frame,
            depth,
            light_x=self.float_value("light_x", -50.0) / 100.0,
            light_y=self.float_value("light_y", -65.0) / 100.0,
            relief=self.float_value("relief", 300.0) / 100.0,
            strength=self.float_value("strength", 100.0) / 100.0,
            ambient=self.float_value("ambient", 20.0) / 100.0,
            invert=self.bool_value("invert", False),
        )


# ------------------------------------------------------------
# 14. Anaglyph3DNode — depth-based stereo
# ------------------------------------------------------------

class Anaglyph3DNode(FrameEffectNode):
    """Build a stereo anaglyph from a depth pass."""

    node_type = "Anaglyph 3D"
    node_category = DEPTH_CATEGORY
    node_description = "Depth-based stereo anaglyph for red/cyan 3D glasses"
    node_color = (188, 112, 128)

    def setup_effect_properties(self) -> None:
        """Add the depth input and register the stereo controls."""
        self.add_input("depth", NodeSocketType.Frame)
        self.set_property(
            "separation",
            slider_property(
                4, 0, 20,
                priority=10,
                group="Stereo",
                label="Separation",
                description="Interocular offset as a fraction of frame width.",
                suffix="%",
            ),
        )
        self.set_property(
            "mode",
            choice_property(
                AnaglyphMode.RedCyan,
                priority=11,
                group="Stereo",
                label="Glasses",
                description="Color pair matching the viewing glasses.",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=12,
                group="Depth",
                label="Invert Depth",
                description="Swap near and far for the parallax direction.",
            ),
        )

    def process_frame(self, frame: np.ndarray, frame_num: int) -> np.ndarray:
        """Return the anaglyph frame, or the source when depth is unwired."""
        del frame_num
        depth: np.ndarray | None = self.input_frame("depth")
        if depth is None:
            return frame
        return anaglyph(
            frame,
            depth,
            separation=self.float_value("separation", 4.0) / 100.0,
            mode=self.enum_value("mode", AnaglyphMode, AnaglyphMode.RedCyan),
            invert=self.bool_value("invert", False),
        )


# ------------------------------------------------------------
# 15. DepthSliceNode — depth range matte
# ------------------------------------------------------------

class DepthSliceNode(FrameNode):
    """Output a soft matte for a range of depth values."""

    node_type = "Depth Slice"
    node_category = DEPTH_CATEGORY
    node_description = "Soft matte selecting a slice of depth values"
    node_color = (168, 140, 204)

    def _setup_sockets(self) -> None:
        """Register the depth input, mask output, and range controls."""
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property(
            "near",
            slider_property(
                0, 0, 100,
                priority=10,
                group="Slice",
                label="Near",
                description="Near edge of the selected depth range.",
                suffix="%",
            ),
        )
        self.set_property(
            "far",
            slider_property(
                50, 0, 100,
                priority=11,
                group="Slice",
                label="Far",
                description="Far edge of the selected depth range.",
                suffix="%",
            ),
        )
        self.set_property(
            "softness",
            slider_property(
                8, 1, 50,
                priority=12,
                group="Slice",
                label="Softness",
                description="Feather of the matte edges.",
                suffix="%",
            ),
        )
        self.set_property(
            "invert",
            toggle_property(
                False,
                priority=13,
                group="Slice",
                label="Invert",
                description="Select everything outside the depth range.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        """Return the depth-range matte, or black when depth is unwired."""
        del frame_num
        depth: np.ndarray | None = self.input_frame("depth")
        if depth is None:
            return self.blank_frame()
        return depth_slice(
            depth,
            near=self.float_value("near", 0.0) / 100.0,
            far=self.float_value("far", 50.0) / 100.0,
            softness=self.float_value("softness", 8.0) / 100.0,
            invert=self.bool_value("invert", False),
        )
