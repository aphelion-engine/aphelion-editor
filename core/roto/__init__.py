"""Roto/rotopaint shape data model, keyframe interpolation, and rasterization."""

from core.roto.interpolation import interpolate_points
from core.roto.model import RotoDocument, RotoPoint, RotoShape

__all__ = [
    "RotoDocument",
    "RotoPoint",
    "RotoShape",
    "interpolate_points",
]
