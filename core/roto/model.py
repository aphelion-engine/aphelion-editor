"""Roto shape data model: points, shapes, and the shape document.

All coordinates are normalized to the 0-1 range (fraction of frame width /
height) so shapes stay correct across proxy resolutions and frame-size
changes. Dataclasses expose ``to_dict``/``from_dict`` using only JSON-native
types (``dict``, ``list``, ``str``, ``int``, ``float``, ``bool``) so they
round-trip through ``core.serialization.encode_value``/``decode_value``
without any dedicated serializer code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PointHandle = tuple[float, float]


@dataclass
class RotoPoint:
    """A single roto vertex, normalized to the 0-1 frame coordinate space.

    ``handle_in``/``handle_out`` are reserved for future bezier tangent-handle
    editing. They are currently unused whenever a shape's ``smooth`` flag is
    ``False`` (the only mode supported in v1), but the field exists so a
    future bezier editor needs no data migration.
    """

    x: float
    y: float
    handle_in: PointHandle | None = None
    handle_out: PointHandle | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-native types."""
        return {
            "x": float(self.x),
            "y": float(self.y),
            "handle_in": list(self.handle_in) if self.handle_in is not None else None,
            "handle_out": (
                list(self.handle_out) if self.handle_out is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RotoPoint:
        """Restore a point from a decoded document dict."""
        handle_in_raw = data.get("handle_in")
        handle_out_raw = data.get("handle_out")
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            handle_in=_as_handle(handle_in_raw),
            handle_out=_as_handle(handle_out_raw),
        )


def _as_handle(value: Any) -> PointHandle | None:
    """Coerce a decoded list/tuple into a two-float handle, or ``None``."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return None


@dataclass
class RotoShape:
    """One roto shape with keyframed point sets.

    ``keyframes`` maps an integer frame number to the list of points that
    define the shape's outline at that frame. Frames between keys are
    resolved by ``core.roto.interpolation.interpolate_points``.
    """

    shape_id: str
    closed: bool = True
    smooth: bool = False
    feather: float = 0.0
    invert: bool = False
    keyframes: dict[int, list[RotoPoint]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-native types (integer keys become strings)."""
        return {
            "shape_id": self.shape_id,
            "closed": bool(self.closed),
            "smooth": bool(self.smooth),
            "feather": float(self.feather),
            "invert": bool(self.invert),
            "keyframes": {
                str(frame_num): [point.to_dict() for point in points]
                for frame_num, points in self.keyframes.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RotoShape:
        """Restore a shape from a decoded document dict."""
        raw_keyframes = data.get("keyframes", {})
        keyframes: dict[int, list[RotoPoint]] = {}
        if isinstance(raw_keyframes, dict):
            for frame_key, raw_points in raw_keyframes.items():
                if not isinstance(raw_points, list):
                    continue
                try:
                    frame_num = int(frame_key)
                except (TypeError, ValueError):
                    continue
                keyframes[frame_num] = [
                    RotoPoint.from_dict(point)
                    for point in raw_points
                    if isinstance(point, dict)
                ]
        return cls(
            shape_id=str(data.get("shape_id", "")),
            closed=bool(data.get("closed", True)),
            smooth=bool(data.get("smooth", False)),
            feather=float(data.get("feather", 0.0)),
            invert=bool(data.get("invert", False)),
            keyframes=keyframes,
        )


@dataclass
class RotoDocument:
    """The full set of roto shapes owned by a single ``RotoNode``."""

    shapes: list[RotoShape] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-native types."""
        return {"shapes": [shape.to_dict() for shape in self.shapes]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RotoDocument:
        """Restore a document from a decoded document dict (or ``None``)."""
        if not isinstance(data, dict):
            return cls()
        raw_shapes = data.get("shapes", [])
        if not isinstance(raw_shapes, list):
            return cls()
        return cls(
            shapes=[
                RotoShape.from_dict(shape)
                for shape in raw_shapes
                if isinstance(shape, dict)
            ]
        )
