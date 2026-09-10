"""Built-in procedural frame generator nodes."""

from __future__ import annotations

import cv2
import numpy as np
from core.nodes.base import WHITE_COLOR_RGB, NodeProperty, NodeSocketType
from core.nodes.enums import GradientMode, NoiseType
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (choice_property, color_property,
                                         slider_property)
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

class NoiseNode(FrameNode):
    """Generate procedural noise: Perlin, Simplex, or FBM."""

    node_type = "Noise"
    node_category = GENERATOR_CATEGORY
    node_description = "Procedural noise for VFX: Perlin, Simplex, FBM"
    node_color = (120, 80, 180)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "type",
            choice_property(
                # pyrefly: ignore [bad-argument-type]
                NoiseType,
                priority=0,
                group="Noise",
                label="Type",
                description="Noise algorithm",
            ),
        )
        self.set_property(
            "scale",
            slider_property(
                8, 1, 256,
                priority=1,
                group="Noise",
                label="Scale",
                description="Noise frequency",
                suffix=" px",
            ),
        )
        self.set_property(
            "octaves",
            slider_property(
                4, 1, 8,
                priority=2,
                group="Noise",
                label="Octaves",
                description="FBM layers",
            ),
        )
        self.set_property(
            "seed",
            slider_property(
                0, 0, 9999,
                priority=3,
                group="Noise",
                label="Seed",
                description="Random seed",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        scale = self.float_value("scale", 8.0)
        octaves = int(self.float_value("octaves", 4))
        seed = int(self.float_value("seed", 0))
        mode = self.get_input_value("type")

        rng = np.random.default_rng(seed)
        base = rng.random((h, w)).astype(np.float32)

        if mode == "perlin":
            noise = cv2.GaussianBlur(base, (0, 0), scale)
        elif mode == "simplex":
            noise = cv2.GaussianBlur(base, (0, 0), scale * 0.5)
        else:  # FBM
            noise = np.zeros_like(base)
            freq = scale
            amp = 1.0
            for _ in range(octaves):
                layer = cv2.GaussianBlur(base, (0, 0), freq)
                noise += layer * amp
                freq *= 0.5
                amp *= 0.5

        noise = np.clip(noise, 0, 1)
        return np.dstack([noise, noise, noise])

class FogNode(FrameNode):
    """Generate procedural fog using fractal noise."""

    node_type = "Fog"
    node_category = GENERATOR_CATEGORY
    node_description = "Procedural fog for atmospheric VFX"
    node_color = (100, 120, 160)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "density",
            slider_property(
                50, 0, 200,
                priority=0,
                group="Fog",
                label="Density",
                description="Fog opacity",
                suffix="%",
            ),
        )
        self.set_property(
            "scale",
            slider_property(
                32, 1, 256,
                priority=1,
                group="Fog",
                label="Scale",
                description="Noise scale",
                suffix=" px",
            ),
        )
        self.set_property(
            "color",
            color_property(
                (200, 200, 200),
                priority=2,
                group="Fog",
                label="Color",
                description="Fog tint",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        scale = self.float_value("scale", 32.0)
        density = self.float_value("density", 50.0) / 100.0
        color = np.array(self.color_value("color", (200, 200, 200))) / 255.0

        base = np.random.random((h, w)).astype(np.float32)
        fog = cv2.GaussianBlur(base, (0, 0), scale)
        fog = np.clip(fog * density, 0, 1)

        return fog[..., None] * color

class HeatDistortionNode(FrameNode):
    """Generate a heat distortion displacement map."""

    node_type = "Heat Distortion"
    node_category = GENERATOR_CATEGORY
    node_description = "Procedural heat distortion for fire/explosions"
    node_color = (180, 90, 60)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "strength",
            slider_property(
                20, 0, 200,
                priority=0,
                group="Heat",
                label="Strength",
                description="Distortion intensity",
                suffix=" px",
            ),
        )
        self.set_property(
            "scale",
            slider_property(
                16, 1, 128,
                priority=1,
                group="Heat",
                label="Scale",
                description="Noise scale",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        strength = self.float_value("strength", 20.0)
        scale = self.float_value("scale", 16.0)

        base = np.random.random((h, w)).astype(np.float32)
        blur = cv2.GaussianBlur(base, (0, 0), scale)

        dx = blur * strength
        dy = cv2.GaussianBlur(base, (0, 0), scale * 0.8) * strength

        disp = np.dstack([dx, dy, np.zeros_like(dx)])
        return disp

class LensFlareNode(FrameNode):
    """Generate a procedural lens flare."""

    node_type = "Lens Flare"
    node_category = GENERATOR_CATEGORY
    node_description = "Procedural cinematic lens flare"
    node_color = (200, 140, 80)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "intensity",
            slider_property(
                100, 0, 300,
                priority=0,
                group="Flare",
                label="Intensity",
                description="Flare brightness",
                suffix="%",
            ),
        )
        self.set_property(
            "streak_length",
            slider_property(
                40, 0, 200,
                priority=1,
                group="Flare",
                label="Streak Length",
                description="Horizontal streak size",
                suffix=" px",
            ),
        )
        self.set_property(
            "color",
            color_property(
                (255, 200, 160),
                priority=2,
                group="Flare",
                label="Color",
                description="Flare tint",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        intensity = self.float_value("intensity", 100.0) / 100.0
        streak_len = int(self.float_value("streak_length", 40.0))
        color = np.array(self.color_value("color", (255, 200, 160))) / 255.0

        flare = np.zeros((h, w), np.float32)
        cx, cy = w // 2, h // 2

        flare[cy, :] = 1.0  # horizontal streak
        flare = cv2.GaussianBlur(flare, (0, 0), streak_len)

        flare = flare * intensity
        return flare[..., None] * color

class RampNode(FrameNode):
    """Generate a multi-stop gradient ramp."""

    node_type = "Ramp"
    node_category = GENERATOR_CATEGORY
    node_description = "Multi-stop gradient ramp"
    node_color = (160, 100, 180)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "color_a",
            color_property((0, 0, 0), priority=0, group="Ramp", label="Color A", description="RGB color A"),
        )
        self.set_property(
            "color_b",
            color_property((255, 255, 255), priority=1, group="Ramp", label="Color B", description="RGB color B"),
        )
        self.set_property(
            "angle",
            slider_property(
                0, 0, 360,
                priority=2,
                group="Ramp",
                label="Angle",
                description="Ramp direction",
                suffix="°",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        angle = np.deg2rad(self.float_value("angle", 0.0))
        ca = np.array(self.color_value("color_a", (0, 0, 0))) / 255.0
        cb = np.array(self.color_value("color_b", (255, 255, 255))) / 255.0

        xv, yv = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
        ramp = xv * np.cos(angle) + yv * np.sin(angle)
        ramp = np.clip(ramp, 0, 1)

        return ramp[..., None] * cb + (1 - ramp[..., None]) * ca

class UVMapNode(FrameNode):
    """Generate a UV coordinate map."""

    node_type = "UV Map"
    node_category = GENERATOR_CATEGORY
    node_description = "Generate UV coordinates for warping and debugging"
    node_color = (100, 180, 200)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        u = np.linspace(0, 1, w)
        v = np.linspace(0, 1, h)
        uu, vv = np.meshgrid(u, v)

        return np.dstack([uu, vv, np.zeros_like(uu)])

class VolumetricLightNode(FrameNode):
    """Generate volumetric light rays."""

    node_type = "Volumetric Light"
    node_category = GENERATOR_CATEGORY
    node_description = "Procedural volumetric light rays"
    node_color = (200, 160, 100)

    def _setup_sockets(self):
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "intensity",
            slider_property(
                100, 0, 300,
                priority=0,
                group="Volume",
                label="Intensity",
                description="Ray brightness",
                suffix="%",
            ),
        )
        self.set_property(
            "samples",
            slider_property(
                32, 1, 128,
                priority=1,
                group="Volume",
                label="Samples",
                description="Ray marching samples",
            ),
        )
        self.set_property(
            "center_x",
            slider_property(
                50, 0, 100,
                priority=2,
                group="Volume",
                label="Center X",
                description="Light source X",
                suffix="%",
            ),
        )
        self.set_property(
            "center_y",
            slider_property(
                50, 0, 100,
                priority=3,
                group="Volume",
                label="Center Y",
                description="Light source Y",
                suffix="%",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        frame = self.input_frame()
        if frame is None:
            return self.blank_frame()

        h, w = frame.shape[:2]
        cx = int(self.float_value("center_x", 50.0) / 100.0 * w)
        cy = int(self.float_value("center_y", 50.0) / 100.0 * h)
        intensity = self.float_value("intensity", 100.0) / 100.0
        samples = max(1, int(self.float_value("samples", 32)))

        # Bilinear interpolation is linear, so collapsing the source to
        # luminance *once* is mathematically identical to averaging each of
        # the ``samples`` remapped RGB frames. It also drops every remap to a
        # single channel instead of three, and removes the per-sample
        # ``mean(axis=2)`` reduction that dominated this node's cost.
        gray = frame[..., :3].mean(axis=2, dtype=np.float32)

        # float32 maps avoid the two full-frame int64 -> float32 casts that
        # the default ``np.indices`` dtype forced on every sample.
        yy, xx = np.indices((h, w), dtype=np.float32)
        dx = cx - xx
        dy = cy - yy

        rays = np.zeros((h, w), np.float32)
        # Reused per-sample buffers: the ray-march loop otherwise allocates
        # four full-resolution arrays on every iteration.
        sx = np.empty((h, w), np.float32)
        sy = np.empty((h, w), np.float32)
        sample = np.empty((h, w), np.float32)

        for i in range(samples):
            t = i / samples

            np.multiply(dx, t, out=sx)
            np.add(sx, xx, out=sx)
            np.multiply(dy, t, out=sy)
            np.add(sy, yy, out=sy)

            cv2.remap(gray, sx, sy, cv2.INTER_LINEAR, dst=sample)
            np.add(rays, sample, out=rays)

        np.multiply(rays, intensity / samples, out=rays)
        np.clip(rays, 0.0, 1.0, out=rays)

        return np.dstack([rays, rays, rays])

class ZFogNode(FrameNode):
    """Depth-based fog."""

    node_type = "Z Fog"
    node_category = "Generator"
    node_description = "Fog based on Z-depth map"
    node_color = (140, 160, 180)

    def _setup_sockets(self):
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "density",
            slider_property(
                50, 0, 200,
                priority=0,
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
                priority=1,
                group="Fog",
                label="Color",
                description="Fog tint",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        depth = self.input_frame("depth")
        if depth is None:
            return self.blank_frame()

        fog_color = np.array(self.color_value("color", (200, 200, 200))) / 255.0
        density = self.float_value("density", 50.0) / 100.0

        fog = depth[..., 0].astype(np.float32)
        fog = cv2.GaussianBlur(fog, (0, 0), 16)
        fog = np.clip(fog * density, 0, 1)

        return fog[..., None] * fog_color

class ParticleMapNode(FrameNode):
    """Generate a procedural particle field."""

    node_type = "Particle Map"
    node_category = "Generator"
    node_description = "Procedural particles: dust, stars, sparks, snow"
    node_color = (180, 180, 200)

    def _setup_sockets(self):
        self.add_output("frame", NodeSocketType.Frame)

        self.set_property(
            "density",
            slider_property(
                100, 0, 1000,
                priority=0,
                group="Particles",
                label="Density",
                description="Number of particles",
            ),
        )
        self.set_property(
            "size",
            slider_property(
                2, 1, 20,
                priority=1,
                group="Particles",
                label="Size",
                description="Particle radius",
                suffix=" px",
            ),
        )
        self.set_property(
            "color",
            color_property(
                (255, 255, 255),
                priority=2,
                group="Particles",
                label="Color",
                description="Particle color",
            ),
        )

    def evaluate(self, frame_num):
        del frame_num
        w, h = self.evaluation_frame_size()

        density = int(self.float_value("density", 100))
        size = int(self.float_value("size", 2))
        color = np.array(self.color_value("color", (255, 255, 255))) / 255.0

        img = np.zeros((h, w, 3), np.float32)
        rng = np.random.default_rng()

        xs = rng.integers(0, w, density)
        ys = rng.integers(0, h, density)

        for x, y in zip(xs, ys):
            cv2.circle(img, (x, y), size, color.tolist(), -1)

        return img
