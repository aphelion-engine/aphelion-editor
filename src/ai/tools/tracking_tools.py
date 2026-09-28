"""Tracking tools.

Everything here is grounded in the properties the tracker nodes actually
declare. ``tracking.configure`` rejects unknown keys outright, so the model
cannot invent a "robustness" knob that does not exist; the ``preset`` shortcut
is simply a documented bundle of real properties, and the applied bundle is
returned so the user can see exactly what changed.
"""

from __future__ import annotations

from typing import Any

from ai.errors import ToolError
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_node, short_list
from ai.tools.node_tools import _coerce_property_value, _display
from ai.types import Permission, ToolResult
from core.history.commands import SetPropertyCommand
from core.nodes.tracking_nodes import PlanarTrackerNode, Tracker

#: Documented quality bundles. Each maps onto properties that really exist;
#: keys absent from a given tracker type are skipped.
TRACKING_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {
        "region_size": 6.0,
        "search_radius": 20.0,
        "track_threshold": 0.35,
        "ambiguity_margin": 0.04,
        "max_jump": 14.0,
        "max_lost_frames": 15,
    },
    "balanced": {
        "region_size": 8.0,
        "search_radius": 15.0,
        "track_threshold": 0.45,
        "reacquire_threshold": 0.65,
        "ambiguity_margin": 0.08,
        "max_jump": 10.0,
        "max_lost_frames": 30,
        "confirmation_frames": 2,
    },
    "accurate": {
        "region_size": 12.0,
        "search_radius": 10.0,
        "track_threshold": 0.60,
        "reacquire_threshold": 0.75,
        "ambiguity_margin": 0.12,
        "max_jump": 6.0,
        "max_lost_frames": 45,
        "confirmation_frames": 3,
        "max_search_multiplier": 6,
    },
}

#: Corners used by planar trackers, in canonical order.
PLANAR_CORNERS: tuple[str, ...] = (
    "top_left",
    "top_right",
    "bottom_right",
    "bottom_left",
)


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="tracking.inspect",
            description=(
                "Inspect a tracker node: its type, seed/region/search settings, "
                "recovery thresholds, gap policy, how many frames it has tracked, "
                "and the upstream source feeding it. Use this before answering "
                "'why is this tracker drifting?'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Tracker node id or name."}
                },
                "required": ["node"],
            },
            permission=Permission.READ_PROJECT,
            handler=_inspect,
            category="Tracking",
        )
    )

    registry.register(
        ToolSpec(
            name="tracking.configure",
            description=(
                "Change settings on a tracker. Every key must be a real property "
                "of that tracker; unknown keys are rejected with the list of "
                "valid ones. Alternatively pass a 'preset' of fast, balanced, or "
                "accurate, which sets a documented bundle of real properties."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Tracker node id or name."},
                    "preset": {
                        "type": "string",
                        "enum": ["fast", "balanced", "accurate"],
                        "description": "Apply a documented quality bundle.",
                    },
                    "settings": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Explicit property values keyed by property name.",
                    },
                },
                "required": ["node"],
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_configure,
            mutates=True,
            category="Tracking",
        )
    )

    registry.register(
        ToolSpec(
            name="tracking.set_region",
            description=(
                "Set the tracked region for a tracker using normalized "
                "coordinates (0.0–1.0). Point trackers take a center and size; "
                "planar trackers take a rectangle that seeds their four corners. "
                "Vision-derived regions should always be shown to the user for "
                "confirmation before use."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Tracker node id or name."},
                    "center": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y] normalized center (0.0–1.0).",
                    },
                    "size": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[w, h] normalized size (0.0–1.0).",
                    },
                    "rect": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y, w, h] normalized rectangle for planar trackers.",
                    },
                },
                "required": ["node"],
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_set_region,
            mutates=True,
            category="Tracking",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _tracker_node(ctx: ToolContext, reference: str) -> tuple[str, Any]:
    node_id, node = resolve_node(ctx, reference)
    # Point trackers subclass ``TrackerNode``; planar ones subclass
    # ``PlanarTrackerNode``. ``Tracker`` is the common base both share, so it
    # is the only correct isinstance check for "is this a tracker at all".
    if not isinstance(node, Tracker):
        raise ToolError(
            "NOT_A_TRACKER",
            f"'{node.name}' is a {node.node_type}, not a tracker. Trackers are: "
            "Tracker, Planar Tracker, Planar Homography Tracker, Surface Tracker, "
            "and the professional tracker nodes.",
        )
    return node_id, node


def _inspect(ctx: ToolContext) -> ToolResult:
    from ai.graph_model import describe_node_instance

    node_id, node = _tracker_node(ctx, str(ctx.args["node"]))
    detail = describe_node_instance(node_id, node)
    detail["kind"] = "planar" if isinstance(node, PlanarTrackerNode) else "point"

    tracked_frames = 0
    if isinstance(node, PlanarTrackerNode):
        for curve_x, _ in node.corner_curves.values():
            tracked_frames = max(tracked_frames, len(curve_x.keyframes))
        detail["diagnostic_frames"] = len(getattr(node, "tracking_diagnostics", {}))
    else:
        tracked_frames = max(
            len(node.track_x.keyframes), len(node.track_y.keyframes)
        )
        detail["sample_frames"] = len(getattr(node, "track_samples", {}))

    detail["tracked_frames"] = tracked_frames
    detail["has_tracking_data"] = tracked_frames > 0
    detail["upstream"] = [
        {
            "node": connection.output_node_id,
            "port": connection.output_slot,
            "name": _node_name(ctx.project, connection.output_node_id),
        }
        for connection in ctx.project.connections
        if connection.input_node_id == node_id and connection.input_slot == "frame"
    ]
    supported = sorted(
        key for key in node.properties if not key.startswith("_input_")
    )
    detail["supported_settings"] = supported

    notes: list[str] = []
    if not detail["has_tracking_data"]:
        notes.append(
            "No tracking data yet: only the seed position is available. The user "
            "must run the tracker before quality questions are answerable."
        )
    if not detail["upstream"]:
        notes.append("The tracker has no frame input connected.")
    detail["notes"] = notes

    return ToolResult(
        ok=True,
        summary=f"{node.name} ({node.node_type}), {tracked_frames} tracked frame(s).",
        data=detail,
    )


def _configure(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("configure a tracker")
    node_id, node = _tracker_node(ctx, str(ctx.args["node"]))

    requested: dict[str, Any] = {}
    preset_name = ctx.args.get("preset")
    if preset_name:
        bundle = TRACKING_PRESETS.get(str(preset_name))
        if bundle is None:
            raise ToolError(
                "UNKNOWN_PRESET",
                f"Unknown preset '{preset_name}'. Options: "
                f"{', '.join(sorted(TRACKING_PRESETS))}.",
            )
        requested.update(
            {key: value for key, value in bundle.items() if node.get_property(key)}
        )
    settings = ctx.args.get("settings")
    if isinstance(settings, dict):
        for key, value in settings.items():
            if node.get_property(key) is None:
                raise ToolError(
                    "UNKNOWN_PROPERTY",
                    f"'{node.node_type}' has no property '{key}'. Supported: "
                    f"{short_list(sorted(k for k in node.properties if not k.startswith('_input_')))}",
                )
            requested[key] = value

    if not requested:
        raise ToolError(
            "INVALID_ARGUMENT", "Provide 'preset' and/or 'settings' to change."
        )

    applied: list[str] = []
    for key, raw in requested.items():
        member = _coerce_property_value(node, key, raw)
        prop = node.get_property(key)
        if prop is not None and _display(prop.value) == _display(member):
            continue
        if transaction.apply(
            ctx.project,
            SetPropertyCommand(node_id, key, member),
            action=f"~ Set {node.name}.{key} → {_display(member)}",
        ):
            applied.append(f"{key}={_display(member)}")

    if not applied:
        return ToolResult(
            ok=True,
            summary=f"{node.name} already matches that configuration.",
            data={"applied": [], "skipped": sorted(requested)},
        )
    return ToolResult(
        ok=True,
        summary=f"Updated {len(applied)} setting(s) on {node.name}.",
        details=[f"~ Set {node.name}.{entry}" for entry in applied],
        data={
            "node_id": node_id,
            "applied": applied,
            "preset": preset_name,
            "skipped": sorted(set(requested) - {entry.split("=")[0] for entry in applied}),
        },
        changed_node_ids=[node_id],
    )


def _set_region(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("set a tracking region")
    node_id, node = _tracker_node(ctx, str(ctx.args["node"]))
    center = ctx.args.get("center")
    size = ctx.args.get("size")
    rect = ctx.args.get("rect")

    if rect is not None:
        x, y, width, height = (float(v) for v in rect)
        center = center or [x + width / 2.0, y + height / 2.0]
        size = size or [width, height]
    if center is None or size is None:
        raise ToolError(
            "INVALID_ARGUMENT",
            "Provide 'center' and 'size', or a 'rect' of [x, y, width, height].",
        )

    for value in (*center, *size):
        if not -1.0 <= float(value) <= 2.0:
            raise ToolError(
                "REGION_OUT_OF_BOUNDS",
                "Normalized coordinates must be within -1.0 to 2.0.",
            )

    changes: dict[str, Any] = {}
    if isinstance(node, PlanarTrackerNode):
        left = float(center[0]) - float(size[0]) / 2.0
        top = float(center[1]) - float(size[1]) / 2.0
        right = float(center[0]) + float(size[0]) / 2.0
        bottom = float(center[1]) + float(size[1]) / 2.0
        corners = {
            "top_left": (left, top),
            "top_right": (right, top),
            "bottom_right": (right, bottom),
            "bottom_left": (left, bottom),
        }
        for corner, (cx, cy) in corners.items():
            changes[f"{corner}_seed_x"] = cx * 100.0
            changes[f"{corner}_seed_y"] = cy * 100.0
        changes["region_size"] = max(1.0, float(size[0]) * 100.0 / 2.0)
    else:
        changes["center_x"] = float(center[0]) * 100.0
        changes["center_y"] = float(center[1]) * 100.0
        changes["region_size"] = max(1.0, min(50.0, float(size[0]) * 100.0))

    applied: list[str] = []
    for key, raw in changes.items():
        if node.get_property(key) is None:
            continue
        member = _coerce_property_value(node, key, raw)
        if transaction.apply(
            ctx.project,
            SetPropertyCommand(node_id, key, member),
            action=f"~ Set {node.name}.{key} → {_display(member)}",
        ):
            applied.append(key)

    return ToolResult(
        ok=True,
        summary=f"Set the tracked region on {node.name} ({len(applied)} value(s)).",
        details=[f"~ Set region on {node.name}"],
        data={
            "node_id": node_id,
            "center": list(center),
            "size": list(size),
            "applied": applied,
        },
        changed_node_ids=[node_id],
    )


def _node_name(project: Any, node_id: str) -> str:
    node = project.nodes.get(node_id)
    return node.name if node is not None else node_id
