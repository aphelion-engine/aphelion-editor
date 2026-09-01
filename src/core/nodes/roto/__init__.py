"""Roto/rotopaint shape data model, keyframe interpolation, and rasterization."""

from core.nodes.roto.interpolation import interpolate_points
from core.nodes.roto.model import RotoDocument, RotoPoint, RotoShape

__all__ = [
    "RotoDocument",
    "RotoPoint",
    "RotoShape",
    "interpolate_points",
]
