"""2D and planar (4-corner) tracker nodes.

Tracking itself never runs inside ``evaluate`` — it is a background job
(see ``render.tracking_worker``) that samples the connected "frame" input
across a range and writes the results into these nodes' own
``AnimationCurve`` storage (paralleling ``RotoNode.document``). ``evaluate``
only resolves the already-tracked curves (or an untracked seed position) at
the current frame, which is cheap and keeps interactive playback smooth.
"""

from __future__ import annotations

from typing import Any

from core.animation import AnimationCurve
from core.nodes.base import NodeSocketType, NodeValue
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import number_property

TRACKING_CATEGORY: str = "Tracking"

# (name, seed_x_percent, seed_y_percent) — matches CornerPinNode's identity
# rectangle so the two nodes line up visually by default when connected.
_PLANAR_CORNERS: tuple[tuple[str, float, float], ...] = (
    ("top_left", 0.0, 0.0),
    ("top_right", 100.0, 0.0),
    ("bottom_right", 100.0, 100.0),
    ("bottom_left", 0.0, 100.0),
)


class TrackerNode(FrameNode):
    """Track one 2D point across a frame range via template matching."""

    node_type: str = "Tracker"
    node_category: str = TRACKING_CATEGORY
    node_description: str = (
        "Track a single point across frames; outputs its X/Y as Number sockets"
    )
    node_color: tuple[int, int, int] = (206, 100, 130)

    def __init__(self, name: str | None = None) -> None:
        self.track_x: AnimationCurve = AnimationCurve()
        self.track_y: AnimationCurve = AnimationCurve()
        super().__init__(name)

    def _setup_sockets(self) -> None:
        """Register the tracked plate input and X/Y Number outputs."""
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("x", NodeSocketType.Number)
        self.add_output("y", NodeSocketType.Number)
        self.set_property(
            "center_x",
            number_property(
                50.0, 0.0, 100.0, priority=0, group="Seed", label="Center X",
                description="Seed X position (percent of frame width) before tracking.",
                suffix="%",
            ),
        )
        self.set_property(
            "center_y",
            number_property(
                50.0, 0.0, 100.0, priority=1, group="Seed", label="Center Y",
                description="Seed Y position (percent of frame height) before tracking.",
                suffix="%",
            ),
        )
        self.set_property(
            "region_size",
            number_property(
                8.0, 1.0, 50.0, priority=10, group="Pattern", label="Pattern Size",
                description="Tracked patch size (percent of frame width).",
                suffix="%",
            ),
        )
        self.set_property(
            "search_radius",
            number_property(
                15.0, 1.0, 100.0, priority=11, group="Pattern", label="Search Radius",
                description="Max per-frame search distance (percent of frame width).",
                suffix="%",
            ),
        )

    def seed_position(self) -> tuple[float, float]:
        """Return the normalized seed position from the Center X/Y properties."""
        return (
            self.float_value("center_x", 50.0) / 100.0,
            self.float_value("center_y", 50.0) / 100.0,
        )

    def region_size_normalized(self) -> tuple[float, float]:
        """Return the tracked patch size as normalized ``(w, h)`` (square)."""
        size = self.float_value("region_size", 8.0) / 100.0
        return size, size

    def search_radius_normalized(self) -> float:
        """Return the search radius as a normalized fraction of frame width."""
        return self.float_value("search_radius", 15.0) / 100.0

    def evaluate(self, frame_num: int) -> NodeValue:
        """Resolve the tracked (or seed) X/Y at ``frame_num`` as percents."""
        if self.track_x.is_empty or self.track_y.is_empty:
            x, y = self.seed_position()
        else:
            x = self.track_x.value_at(frame_num)
            y = self.track_y.value_at(frame_num)
        # Number outputs use the same 0–100 percent scale as transform nodes.
        return {"x": x * 100.0, "y": y * 100.0}

    def to_dict(self) -> dict[str, Any]:
        """Serialize base node data plus the tracked X/Y curves."""
        data = super().to_dict()
        data["track_x"] = self.track_x.to_dict()
        data["track_y"] = self.track_y.to_dict()
        return data

    def apply_document(self, data: dict[str, Any]) -> None:
        """Restore base node data plus the tracked X/Y curves."""
        super().apply_document(data)
        self.track_x = AnimationCurve.from_dict(data.get("track_x") or {})
        self.track_y = AnimationCurve.from_dict(data.get("track_y") or {})


class PlanarTrackerNode(FrameNode):
    """Track four corner points across a frame range for perspective inserts.

    Wire its eight outputs directly into a ``CornerPinNode``'s eight
    modulation inputs for a match-moved insert driven entirely by tracking.
    """

    node_type: str = "Planar Tracker"
    node_category: str = TRACKING_CATEGORY
    node_description: str = (
        "Track four corner points across frames for a match-moved Corner Pin"
    )
    node_color: tuple[int, int, int] = (198, 92, 140)

    def __init__(self, name: str | None = None) -> None:
        self.corner_curves: dict[str, tuple[AnimationCurve, AnimationCurve]] = {
            corner: (AnimationCurve(), AnimationCurve()) for corner, _, _ in _PLANAR_CORNERS
        }
        super().__init__(name)

    def _setup_sockets(self) -> None:
        """Register the tracked plate input, corner outputs, and seed positions."""
        self.add_input("frame", NodeSocketType.Frame)
        for corner, seed_x, seed_y in _PLANAR_CORNERS:
            self.add_output(f"{corner}_x", NodeSocketType.Number)
            self.add_output(f"{corner}_y", NodeSocketType.Number)
            label = corner.replace("_", " ").title()
            self.set_property(
                f"{corner}_seed_x",
                number_property(
                    seed_x, -50.0, 150.0, priority=0, group="Seed",
                    label=f"{label} X", description=f"Seed X for {label} (percent).",
                    suffix="%",
                ),
            )
            self.set_property(
                f"{corner}_seed_y",
                number_property(
                    seed_y, -50.0, 150.0, priority=1, group="Seed",
                    label=f"{label} Y", description=f"Seed Y for {label} (percent).",
                    suffix="%",
                ),
            )
        self.set_property(
            "region_size",
            number_property(
                6.0, 1.0, 50.0, priority=10, group="Pattern", label="Pattern Size",
                description="Tracked patch size per corner (percent of frame width).",
                suffix="%",
            ),
        )
        self.set_property(
            "search_radius",
            number_property(
                12.0, 1.0, 100.0, priority=11, group="Pattern", label="Search Radius",
                description="Max per-frame search distance (percent of frame width).",
                suffix="%",
            ),
        )

    def seed_corners(
        self,
    ) -> tuple[
        tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]
    ]:
        """Return the four normalized seed corner positions."""
        positions: list[tuple[float, float]] = [
            (
                self.float_value(f"{corner}_seed_x", 0.0) / 100.0,
                self.float_value(f"{corner}_seed_y", 0.0) / 100.0,
            )
            for corner, _, _ in _PLANAR_CORNERS
        ]
        return positions[0], positions[1], positions[2], positions[3]

    def region_size_normalized(self) -> tuple[float, float]:
        """Return the tracked patch size as normalized ``(w, h)`` (square)."""
        size = self.float_value("region_size", 6.0) / 100.0
        return size, size

    def search_radius_normalized(self) -> float:
        """Return the search radius as a normalized fraction of frame width."""
        return self.float_value("search_radius", 12.0) / 100.0

    def evaluate(self, frame_num: int) -> NodeValue:
        """Resolve every corner's tracked (or seed) X/Y at ``frame_num`` as percents."""
        seeds = self.seed_corners()
        result: dict[str, float] = {}
        for (corner, _, _), seed in zip(_PLANAR_CORNERS, seeds):
            curve_x, curve_y = self.corner_curves[corner]
            if curve_x.is_empty or curve_y.is_empty:
                x_norm, y_norm = seed
            else:
                x_norm = curve_x.value_at(frame_num)
                y_norm = curve_y.value_at(frame_num)
            # Match ``CornerPinNode`` corner properties (0–100 percent of frame).
            result[f"{corner}_x"] = x_norm * 100.0
            result[f"{corner}_y"] = y_norm * 100.0
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize base node data plus every corner's tracked curves."""
        data = super().to_dict()
        data["corner_curves"] = {
            corner: {"x": curve_x.to_dict(), "y": curve_y.to_dict()}
            for corner, (curve_x, curve_y) in self.corner_curves.items()
        }
        return data

    def apply_document(self, data: dict[str, Any]) -> None:
        """Restore base node data plus every corner's tracked curves."""
        super().apply_document(data)
        raw = data.get("corner_curves")
        if not isinstance(raw, dict):
            return
        for corner, _, _ in _PLANAR_CORNERS:
            entry = raw.get(corner)
            if not isinstance(entry, dict):
                continue
            curve_x = AnimationCurve.from_dict(entry.get("x") or {})
            curve_y = AnimationCurve.from_dict(entry.get("y") or {})
            self.corner_curves[corner] = (curve_x, curve_y)
