"""Keyframe tools: real animation control for the assistant.

Aphelion's animation model is deliberately minimal (see
``core.animation.curve``): a numeric property is animated by a curve of
integer frame to float value, linearly interpolated between keys and held flat
outside the keyed range. There is no bezier or ease editor, so these tools
expose exactly what the engine implements — held values and linear ramps —
instead of accepting an interpolation mode that would silently do nothing.

Every edit goes through the editor's own ``SetKeyframeCommand`` /
``RemoveKeyframeCommand``, so animation is undoable like any other change and a
whole multi-key ramp collapses into one undo step.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ai.errors import ToolError
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_node, short_list
from ai.tools.node_tools import _coerce_property_value, _display
from ai.types import Permission, ToolResult
from core.history.commands import RemoveKeyframeCommand, SetKeyframeCommand


def register_tools(registry: ToolRegistry) -> None:
    """Register every keyframe.* tool."""

    registry.register(
        ToolSpec(
            name="keyframe.list",
            description=(
                "List animation on the graph: which numeric properties are "
                "keyed, at which frames, and the value each curve resolves to. "
                "Aphelion interpolates linearly between keyframes and holds the "
                "value flat outside the keyed range."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {
                        "type": "string",
                        "description": "Restrict to one node (id, name, or 'selected').",
                    },
                    "property": {
                        "type": "string",
                        "description": "Restrict to one property key.",
                    },
                },
            },
            permission=Permission.READ_PROJECT,
            handler=_list_keyframes,
            mutates=False,
            category="Animation",
        )
    )

    registry.register(
        ToolSpec(
            name="keyframe.set",
            description=(
                "Set or overwrite one keyframe: '<property> = <value>' at "
                "<frame>. Use this for animation like 'fade in at frame 120'. "
                "The property must be a real numeric property of the node; "
                "sliders are range-checked."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id, name, or 'selected'."},
                    "property": {"type": "string", "description": "Property key to animate."},
                    "frame": {"type": "integer", "description": "Frame number.", "minimum": 0},
                    "value": {
                        "type": "number",
                        "description": (
                            "Keyed value, in the property's own units. Keyframes "
                            "are numeric; non-numeric properties cannot be keyed."
                        ),
                    },
                },
                "required": ["node", "property", "frame", "value"],
                "additionalProperties": False,
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_set_keyframe,
            mutates=True,
            category="Animation",
        )
    )

    registry.register(
        ToolSpec(
            name="keyframe.ramp",
            description=(
                "Animate a property linearly from one value to another across a "
                "frame range — the natural way to build 'fade in between frames "
                "100 and 130' or 'scale from 0 to 100% over three seconds'. "
                "Keys both ends in a single undo step."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id, name, or 'selected'."},
                    "property": {"type": "string", "description": "Property key to animate."},
                    "from_frame": {"type": "integer", "minimum": 0},
                    "to_frame": {"type": "integer", "minimum": 0},
                    "from_value": {"type": "number", "description": "Value at from_frame."},
                    "to_value": {"type": "number", "description": "Value at to_frame."},
                },
                "required": ["node", "property", "from_frame", "to_frame",
                             "from_value", "to_value"],
                "additionalProperties": False,
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_ramp,
            mutates=True,
            category="Animation",
        )
    )

    registry.register(
        ToolSpec(
            name="keyframe.remove",
            description="Remove the keyframe at one frame. The curve keeps its other keys.",
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string"},
                    "property": {"type": "string"},
                    "frame": {"type": "integer", "minimum": 0},
                },
                "required": ["node", "property", "frame"],
                "additionalProperties": False,
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_remove_keyframe,
            mutates=True,
            category="Animation",
        )
    )

    registry.register(
        ToolSpec(
            name="keyframe.clear",
            description=(
                "Remove every keyframe from one property, leaving its static "
                "value in place. Use this to un-animate a property."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string"},
                    "property": {"type": "string"},
                },
                "required": ["node", "property"],
                "additionalProperties": False,
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_clear_keyframes,
            mutates=True,
            category="Animation",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _list_keyframes(ctx: ToolContext) -> ToolResult:
    project = ctx.project
    reference = ctx.args.get("node")
    only_property = ctx.args.get("property")

    if reference:
        node_id, node = resolve_node(ctx, str(reference))
        candidates = [(node_id, node)]
    else:
        candidates = list(project.nodes.items())

    rows: list[dict[str, Any]] = []
    for node_id, node in candidates:
        animated = getattr(node, "animated_properties", {}) or {}
        for key, curve in sorted(animated.items()):
            if only_property and key != only_property:
                continue
            keyframes = sorted(curve.keyframes.items())
            if not keyframes:
                continue
            rows.append(
                {
                    "node_id": node_id,
                    "node": node.name,
                    "type": node.node_type,
                    "property": key,
                    "keyframes": [{"frame": f, "value": v} for f, v in keyframes],
                    "first_frame": keyframes[0][0],
                    "last_frame": keyframes[-1][0],
                    "value_at_current_frame": float(
                        curve.value_at(int(project.current_frame))
                    ),
                    "static_value": _display(node.get_property(key).value)
                    if node.get_property(key) is not None
                    else None,
                }
            )

    if reference and not rows:
        node_id, node = resolve_node(ctx, str(reference))
        animated_keys = sorted(getattr(node, "animated_properties", {}) or {})
        numeric = _numeric_property_keys(node)
        return ToolResult(
            ok=True,
            summary=(
                f"{node.name} has no keyframes"
                + (f" on '{only_property}'." if only_property else ".")
            ),
            data={
                "node_id": node_id,
                "animated_properties": animated_keys,
                "animatable_properties": numeric,
                "interpolation": "linear, held flat outside the keyed range",
            },
        )

    return ToolResult(
        ok=True,
        summary=f"{len(rows)} animated propert{'y' if len(rows) == 1 else 'ies'} found.",
        data={
            "current_frame": int(project.current_frame),
            "animated": rows,
            "interpolation": "linear, held flat outside the keyed range",
        },
    )


def _set_keyframe(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("set a keyframe")
    node_id, node, key, value = _keyed_target(ctx)
    frame = int(ctx.args["frame"])

    if not transaction.apply(
        ctx.project,
        SetKeyframeCommand(node_id, key, frame, value),
        action=f"~ Key {node.name}.{key} = {_display(value)} at frame {frame}",
        changed_node_ids=[node_id],
    ):
        return ToolResult.failure(
            "COMMAND_REJECTED", f"The editor refused to key {key} at frame {frame}."
        )

    return ToolResult(
        ok=True,
        summary=f"Keyed {node.name}.{key} to {_display(value)} at frame {frame}.",
        details=[f"~ Key {node.name}.{key} = {_display(value)} at frame {frame}"],
        data={"node_id": node_id, "property": key, "frame": frame, "value": value},
        changed_node_ids=[node_id],
    )


def _ramp(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("animate a property")
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    key = str(ctx.args["property"]).strip()
    _require_animatable(node, key)

    from_frame = int(ctx.args["from_frame"])
    to_frame = int(ctx.args["to_frame"])
    if to_frame <= from_frame:
        raise ToolError(
            "INVALID_ARGUMENT",
            f"to_frame ({to_frame}) must be greater than from_frame ({from_frame}).",
        )

    start = _numeric_value(node, key, ctx.args["from_value"])
    end = _numeric_value(node, key, ctx.args["to_value"])

    applied = 0
    for frame, value in ((from_frame, start), (to_frame, end)):
        if transaction.apply(
            ctx.project,
            SetKeyframeCommand(node_id, key, frame, value),
            action=f"~ Key {node.name}.{key} = {_display(value)} at frame {frame}",
            changed_node_ids=[node_id],
        ):
            applied += 1

    if not applied:
        return ToolResult.failure(
            "COMMAND_REJECTED", f"The editor refused to animate {key}."
        )

    return ToolResult(
        ok=True,
        summary=(
            f"Animated {node.name}.{key} from {_display(start)} at frame "
            f"{from_frame} to {_display(end)} at frame {to_frame} (linear)."
        ),
        details=[
            f"~ Animate {node.name}.{key}: {_display(start)} → {_display(end)} "
            f"over frames {from_frame}–{to_frame}"
        ],
        data={
            "node_id": node_id,
            "property": key,
            "from": {"frame": from_frame, "value": start},
            "to": {"frame": to_frame, "value": end},
            "interpolation": "linear",
        },
        changed_node_ids=[node_id],
    )


def _remove_keyframe(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("remove a keyframe")
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    key = str(ctx.args["property"]).strip()
    frame = int(ctx.args["frame"])

    curve = (getattr(node, "animated_properties", {}) or {}).get(key)
    if curve is None or not curve.has_keyframe_at(frame):
        raise ToolError(
            "KEYFRAME_NOT_FOUND",
            f"{node.name}.{key} has no keyframe at frame {frame}. "
            + (
                f"Keyed frames: {sorted(curve.keyframes)}."
                if curve is not None
                else "The property is not animated."
            ),
        )

    if not transaction.apply(
        ctx.project,
        RemoveKeyframeCommand(node_id, key, frame),
        action=f"~ Remove keyframe {node.name}.{key} at frame {frame}",
        changed_node_ids=[node_id],
    ):
        return ToolResult.failure("COMMAND_REJECTED", "The editor refused that removal.")

    return ToolResult(
        ok=True,
        summary=f"Removed the keyframe on {node.name}.{key} at frame {frame}.",
        details=[f"~ Remove keyframe {node.name}.{key} at frame {frame}"],
        changed_node_ids=[node_id],
    )


def _clear_keyframes(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("clear animation")
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    key = str(ctx.args["property"]).strip()
    curve = (getattr(node, "animated_properties", {}) or {}).get(key)
    if curve is None or curve.is_empty:
        return ToolResult(ok=True, summary=f"{node.name}.{key} is not animated.")

    frames = sorted(curve.keyframes)
    removed = 0
    for frame in frames:
        if transaction.apply(
            ctx.project,
            RemoveKeyframeCommand(node_id, key, frame),
            action=f"~ Remove keyframe {node.name}.{key} at frame {frame}",
            changed_node_ids=[node_id],
        ):
            removed += 1

    return ToolResult(
        ok=True,
        summary=f"Removed {removed} keyframe(s) from {node.name}.{key}.",
        details=[f"~ Clear animation on {node.name}.{key} ({removed} key(s))"],
        data={"node_id": node_id, "property": key, "frames": frames},
        changed_node_ids=[node_id],
    )


# ======================================================================
# Helpers
# ======================================================================


def _numeric_property_keys(node: Any) -> list[str]:
    """Property keys that can legally be animated."""
    keys: list[str] = []
    for key in sorted(getattr(node, "properties", {}) or {}):
        prop = node.get_property(key)
        if prop is None:
            continue
        value = prop.value
        if isinstance(value, bool) or isinstance(value, Enum):
            continue
        if isinstance(value, (int, float)):
            keys.append(key)
    return keys


def _require_animatable(node: Any, key: str) -> Any:
    """Validate that ``key`` is a real, animatable numeric property."""
    prop = node.get_property(key)
    if prop is None:
        raise ToolError(
            "UNKNOWN_PROPERTY",
            f"'{node.node_type}' has no property '{key}'. Available: "
            f"{short_list(sorted(getattr(node, 'properties', {}) or {}))}",
        )
    value = prop.value
    if isinstance(value, bool) or isinstance(value, Enum) or not isinstance(
        value, (int, float)
    ):
        raise ToolError(
            "PROPERTY_NOT_ANIMATABLE",
            f"'{key}' on {node.node_type} is not a numeric property, so it "
            "cannot be keyed. Animatable properties: "
            f"{short_list(_numeric_property_keys(node))}",
        )
    return prop


def _numeric_value(node: Any, key: str, raw: Any) -> float:
    """Coerce a model-supplied value with the property's own range checks."""
    _require_animatable(node, key)
    coerced = _coerce_property_value(node, key, raw)
    if isinstance(coerced, bool) or isinstance(coerced, Enum) or not isinstance(
        coerced, (int, float)
    ):
        raise ToolError(
            "INVALID_PROPERTY_VALUE",
            f"'{key}' needs a numeric value (received {raw!r}).",
        )
    return float(coerced)


def _keyed_target(ctx: ToolContext) -> tuple[str, Any, str, float]:
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    key = str(ctx.args["property"]).strip()
    value = _numeric_value(node, key, ctx.args["value"])
    return node_id, node, key, value


__all__ = ["register_tools"]
