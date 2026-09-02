"""Depth-supporting generator nodes for pseudo-3D compositing."""

from __future__ import annotations
import numpy as np
import cv2

from core.nodes.base import NodeSocketType
from core.nodes.enums import (
    VolumeSliceAxis,
    DepthRampMode,
    DepthShape,
)
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (
    slider_property,
    choice_property,
    color_property,
)

DEPTH_GEN_CATEGORY = "Depth Generator"


# ------------------------------------------------------------
# 1. DepthRampNode — linear depth ramps
# ------------------------------------------------------------

class DepthRampNode(FrameNode):
    """Generate a linear depth ramp."""

    node_type = "Depth Ramp"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Linear depth ramp: horizontal, vertical, radial"
    node_color = (140, 120, 200)

    def _setup_sockets(self) -> None:
        self.add_output("depth", NodeSocketType.Frame)
        self.set_property(
            "mode",
            choice_property(
                DepthRampMode.Horizontal,
                priority=10,
                group="Ramp",
                label="Mode",
                description="Ramp direction.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        mode: DepthRampMode = self.enum_value(
            "mode", DepthRampMode, DepthRampMode.Horizontal
        )

        if mode == DepthRampMode.Horizontal:
            ramp = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
        elif mode == DepthRampMode.Vertical:
            ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
        else:
            yy, xx = np.indices((height, width))
            cx, cy = width / 2.0, height / 2.0
            r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            ramp = r / (r.max() if r.max() > 0 else 1.0)

        return ramp[..., None]


# ------------------------------------------------------------
# 2. DepthNoiseNode — procedural depth fields
# ------------------------------------------------------------

class DepthNoiseNode(FrameNode):
    """Generate procedural depth noise."""

    node_type = "Depth Noise"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Perlin-style depth noise for fog and displacement"
    node_color = (160, 120, 180)

    def _setup_sockets(self) -> None:
        self.add_output("depth", NodeSocketType.Frame)
        self.set_property(
            "scale",
            slider_property(
                32,
                1,
                256,
                priority=10,
                group="Noise",
                label="Scale",
                description="Noise blur scale.",
                suffix=" px",
            ),
        )
        self.set_property(
            "seed",
            slider_property(
                0,
                0,
                9999,
                priority=11,
                group="Noise",
                label="Seed",
                description="Random seed.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        scale = self.float_value("scale", 32.0)
        seed = int(self.float_value("seed", 0.0))

        rng = np.random.default_rng(seed)
        base = rng.random((height, width), dtype=np.float32)
        noise = cv2.GaussianBlur(base, (0, 0), scale)

        return np.clip(noise, 0.0, 1.0)[..., None]


# ------------------------------------------------------------
# 3. DepthShapeNode — synthetic 3D shapes
# ------------------------------------------------------------

class DepthShapeNode(FrameNode):
    """Generate depth for sphere, box, cylinder."""

    node_type = "Depth Shape"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Depth maps for sphere, box, cylinder"
    node_color = (180, 140, 160)

    def _setup_sockets(self) -> None:
        self.add_output("depth", NodeSocketType.Frame)
        self.set_property(
            "shape",
            choice_property(
                DepthShape.Sphere,
                priority=10,
                group="Shape",
                label="Shape",
                description="Depth shape type.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        yy, xx = np.indices((height, width))
        cx, cy = width / 2.0, height / 2.0

        dx = (xx - cx) / (cx if cx != 0 else 1.0)
        dy = (yy - cy) / (cy if cy != 0 else 1.0)

        shape: DepthShape = self.enum_value("shape", DepthShape, DepthShape.Sphere)

        if shape == DepthShape.Sphere:
            r = np.sqrt(dx * dx + dy * dy)
            depth = np.clip(r, 0.0, 1.0)
        elif shape == DepthShape.Box:
            depth = np.maximum(np.abs(dx), np.abs(dy))
        elif shape == DepthShape.Cylinder:
            depth = np.abs(dx)
        else:
            depth = np.zeros_like(dx, dtype=np.float32)

        return depth.astype(np.float32)[..., None]


# ------------------------------------------------------------
# 4. DepthGradientNode — multi-stop depth gradient
# ------------------------------------------------------------

class DepthGradientNode(FrameNode):
    """Multi-stop depth gradient."""

    node_type = "Depth Gradient"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Near/Mid/Far depth gradient"
    node_color = (200, 140, 180)

    def _setup_sockets(self) -> None:
        self.add_output("depth", NodeSocketType.Frame)
        self.set_property(
            "near",
            slider_property(
                0.0,
                0.0,
                1.0,
                priority=10,
                group="Gradient",
                label="Near",
                description="Near depth value.",
            ),
        )
        self.set_property(
            "mid",
            slider_property(
                0.5,
                0.0,
                1.0,
                priority=11,
                group="Gradient",
                label="Mid",
                description="Mid depth value.",
            ),
        )
        self.set_property(
            "far",
            slider_property(
                1.0,
                0.0,
                1.0,
                priority=12,
                group="Gradient",
                label="Far",
                description="Far depth value.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, _ = self.evaluation_frame_size()

        near = self.float_value("near", 0.0)
        mid = self.float_value("mid", 0.5)
        far = self.float_value("far", 1.0)

        ramp = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
        depth = np.interp(ramp, [0.0, 0.5, 1.0], [near, mid, far])

        return depth[..., None]


# ------------------------------------------------------------
# 5. NormalFromDepthNode — compute normals from depth
# ------------------------------------------------------------

class NormalFromDepthNode(FrameNode):
    """Compute normals from depth map."""

    node_type = "Normal From Depth"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Generate normal map from depth"
    node_color = (160, 180, 200)

    def _setup_sockets(self) -> None:
        self.add_input("depth", NodeSocketType.Frame)
        self.add_output("normal", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        d = self.input_frame("depth")
        if d is None:
            return self.blank_frame()

        depth = d[..., 0].astype(np.float32)
        gx = cv2.Sobel(depth, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(depth, cv2.CV_32F, 0, 1)
        nz = np.ones_like(depth, dtype=np.float32)

        normal = np.dstack([gx, gy, nz])
        norm = np.linalg.norm(normal, axis=2, keepdims=True)
        normal /= (norm + 1e-6)

        return normal.astype(np.float32)


# ------------------------------------------------------------
# 6. NormalShapeNode — normals for synthetic shapes
# ------------------------------------------------------------

class NormalShapeNode(FrameNode):
    """Generate normals for sphere, box, cylinder."""

    node_type = "Normal Shape"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Normal maps for sphere, box, cylinder"
    node_color = (180, 160, 200)

    def _setup_sockets(self) -> None:
        self.add_output("normal", NodeSocketType.Frame)
        self.set_property(
            "shape",
            choice_property(
                DepthShape.Sphere,
                priority=10,
                group="Shape",
                label="Shape",
                description="Normal shape type.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        yy, xx = np.indices((height, width))
        cx, cy = width / 2.0, height / 2.0

        dx = (xx - cx) / (cx if cx != 0 else 1.0)
        dy = (yy - cy) / (cy if cy != 0 else 1.0)

        shape: DepthShape = self.enum_value("shape", DepthShape, DepthShape.Sphere)

        if shape == DepthShape.Sphere:
            nz = np.sqrt(1.0 - np.clip(dx * dx + dy * dy, 0.0, 1.0))
            normal = np.dstack([dx, dy, nz])
        elif shape == DepthShape.Box:
            normal = np.dstack([np.sign(dx), np.sign(dy), np.ones_like(dx, dtype=np.float32)])
        elif shape == DepthShape.Cylinder:
            nz = np.sqrt(1.0 - np.clip(dx * dx, 0.0, 1.0))
            normal = np.dstack([dx, np.zeros_like(dx, dtype=np.float32), nz])
        else:
            normal = np.dstack([
                np.zeros_like(dx, dtype=np.float32),
                np.zeros_like(dy, dtype=np.float32),
                np.ones_like(dx, dtype=np.float32),
            ])

        norm = np.linalg.norm(normal, axis=2, keepdims=True)
        normal /= (norm + 1e-6)

        return normal.astype(np.float32)


# ------------------------------------------------------------
# 7. PositionMapNode — XYZ position per pixel
# ------------------------------------------------------------

class PositionMapNode(FrameNode):
    """Generate XYZ position map."""

    node_type = "Position Map"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "XYZ position per pixel"
    node_color = (200, 160, 140)

    def _setup_sockets(self) -> None:
        self.add_output("position", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        yy, xx = np.indices((height, width))

        pos = np.dstack([
            xx.astype(np.float32),
            yy.astype(np.float32),
            np.zeros((height, width), dtype=np.float32),
        ])
        return pos


# ------------------------------------------------------------
# 8. CameraDepthNode — depth from camera intrinsics
# ------------------------------------------------------------

class CameraDepthNode(FrameNode):
    """Generate camera-space depth map."""

    node_type = "Camera Depth"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Depth from camera intrinsics"
    node_color = (160, 200, 140)

    def _setup_sockets(self) -> None:
        self.add_output("depth", NodeSocketType.Frame)
        self.set_property(
            "fov",
            slider_property(
                60,
                10,
                120,
                priority=10,
                group="Camera",
                label="FOV",
                description="Field of view.",
                suffix="°",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        fov_rad = np.deg2rad(self.float_value("fov", 60.0))

        yy, xx = np.indices((height, width))
        cx, cy = width / 2.0, height / 2.0

        dx = (xx - cx) / (cx if cx != 0 else 1.0)
        dy = (yy - cy) / (cy if cy != 0 else 1.0)

        depth = np.sqrt(dx * dx + dy * dy) / np.tan(fov_rad / 2.0)
        return depth.astype(np.float32)[..., None]


# ------------------------------------------------------------
# 9. HeightMapNode — height maps
# ------------------------------------------------------------

class HeightMapNode(FrameNode):
    """Generate height map from noise."""

    node_type = "Height Map"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Height map for displacement"
    node_color = (200, 140, 120)

    def _setup_sockets(self) -> None:
        self.add_output("height", NodeSocketType.Frame)
        self.set_property(
            "scale",
            slider_property(
                32,
                1,
                256,
                priority=10,
                group="Height",
                label="Scale",
                description="Noise scale.",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        scale = self.float_value("scale", 32.0)

        base = np.random.random((height, width)).astype(np.float32)
        height_map = cv2.GaussianBlur(base, (0, 0), scale)

        return height_map[..., None]


# ------------------------------------------------------------
# 10. DisplacementMapNode — dx/dy displacement
# ------------------------------------------------------------

class DisplacementMapNode(FrameNode):
    """Generate dx/dy displacement map."""

    node_type = "Displacement Map"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Generate 2-channel displacement map"
    node_color = (180, 120, 140)

    def _setup_sockets(self) -> None:
        self.add_output("displace", NodeSocketType.Frame)
        self.set_property(
            "scale",
            slider_property(
                16,
                1,
                128,
                priority=10,
                group="Displace",
                label="Scale",
                description="Noise scale.",
                suffix=" px",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        scale = self.float_value("scale", 16.0)

        base = np.random.random((height, width)).astype(np.float32)
        dx = cv2.GaussianBlur(base, (0, 0), scale)
        dy = cv2.GaussianBlur(base, (0, 0), scale * 0.8)

        return np.dstack([
            dx.astype(np.float32),
            dy.astype(np.float32),
            np.zeros_like(dx, dtype=np.float32),
        ])


# ------------------------------------------------------------
# 11. UVGridNode — UV debug grid
# ------------------------------------------------------------

class UVGridNode(FrameNode):
    """Generate UV debug grid."""

    node_type = "UV Grid"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "UV grid for projection debugging"
    node_color = (160, 160, 200)

    def _setup_sockets(self) -> None:
        self.add_output("uv", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()

        u = np.linspace(0.0, 1.0, width, dtype=np.float32)
        v = np.linspace(0.0, 1.0, height, dtype=np.float32)
        uu, vv = np.meshgrid(u, v)

        return np.dstack([
            uu,
            vv,
            np.zeros_like(uu, dtype=np.float32),
        ])


# ------------------------------------------------------------
# 12. UVSphereNode — spherical UV unwrap
# ------------------------------------------------------------

class UVSphereNode(FrameNode):
    """Generate spherical UV coordinates."""

    node_type = "UV Sphere"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "UV unwrap for sphere"
    node_color = (180, 160, 200)

    def _setup_sockets(self) -> None:
        self.add_output("uv", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        yy, xx = np.indices((height, width))

        u = (xx.astype(np.float32) / max(width - 1, 1))
        v = (yy.astype(np.float32) / max(height - 1, 1))

        return np.dstack([
            u,
            v,
            np.zeros_like(u, dtype=np.float32),
        ])


# ------------------------------------------------------------
# 13. VolumeNoiseNode — 3D noise slice
# ------------------------------------------------------------

class VolumeNoiseNode(FrameNode):
    """Generate 3D noise slice."""

    node_type = "Volume Noise"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "3D noise slice for volumetric effects"
    node_color = (200, 180, 160)

    def _setup_sockets(self) -> None:
        self.add_output("volume", NodeSocketType.Frame)
        self.set_property(
            "slice",
            slider_property(
                0,
                0,
                100,
                priority=10,
                group="Volume",
                label="Slice",
                description="Noise slice index.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        width, height = self.evaluation_frame_size()
        slice_idx = int(self.float_value("slice", 0.0))

        rng = np.random.default_rng(slice_idx)
        base = rng.random((height, width), dtype=np.float32)
        noise = cv2.GaussianBlur(base, (0, 0), 16.0)

        return noise[..., None]


# ------------------------------------------------------------
# 14. VolumeSliceNode — slice from 3D volume
# ------------------------------------------------------------

class VolumeSliceNode(FrameNode):
    """Extract slice from 3D volume."""

    node_type = "Volume Slice"
    node_category = DEPTH_GEN_CATEGORY
    node_description = "Extract XY/XZ/YZ slice from volume"
    node_color = (160, 200, 180)

    def _setup_sockets(self) -> None:
        self.add_input("volume", NodeSocketType.Frame)
        self.add_output("slice", NodeSocketType.Frame)
        self.set_property(
            "axis",
            choice_property(
                VolumeSliceAxis.XY,
                priority=10,
                group="Slice",
                label="Axis",
                description="Slice axis.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray:
        del frame_num
        vol = self.input_frame("volume")
        if vol is None:
            return self.blank_frame()

        axis: VolumeSliceAxis = self.enum_value(
            "axis", VolumeSliceAxis, VolumeSliceAxis.XY
        )

        if axis == VolumeSliceAxis.XY:
            return vol
        elif axis == VolumeSliceAxis.XZ:
            return vol[:, :, :1]
        elif axis == VolumeSliceAxis.YZ:
            return vol[:, :1, :]
        return vol
