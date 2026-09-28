"""Timeline tools.

Aphelion's timeline is the project frame range plus per-property animation
curves on nodes. Editing is therefore expressed as keyframe commands
(``SetKeyframeCommand`` / ``RemoveKeyframeCommand``) and playhead moves, both
of which are already first-class editor operations. Nothing here pretends the
editor has a clip-bin or edit-decision-list model that it does not have.
"""

from __future__ import annotations

from typing import Any

from ai.errors import ToolError
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_node, short_list
from ai.types import Permission, ToolResult
from core.history.commands import (RemoveKeyframeCommand, SetKeyframeCommand)


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="timeline.inspect",
            description=(
                "Inspect the timeline: frame rate, duration, frame range, "
                "current frame, in/out points, and which node properties are "
                "animated with keyframes."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_inspect,
            category="Timeline",
        )
    )

    registry.register(
        ToolSpec(
            name="timeline.edit",
            description=(
                "Edit the timeline. Supported operations: 'goto_frame' moves the "
                "playhead; 'set_keyframe' and 'remove_keyframe' manage animation "
                "on a node property."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["goto_frame", "set_keyframe", "remove_keyframe"],
                    },
                    "frame": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Frame number for the operation.",
                    },
                    "node": {
                        "type": "string",
                        "description": "Node id or name (keyframe operations).",
                    },
                    "property": {
                        "type": "string",
                        "description": "Numeric property key (keyframe operations).",
                    },
                    "value": {
                        "type": "number",
                        "description": "Keyframe value (set_keyframe only).",
                    },
                },
                "required": ["operation"],
            },
            permission=Permission.EDIT_TIMELINE,
            handler=_edit,
            mutates=True,
            category="Timeline",
        )
    )


def _inspect(ctx: ToolContext) -> ToolResult:
    project = ctx.project
    animated: list[dict[str, Any]] = []
    for node_id, node in sorted(project.nodes.items()):
        for key, curve in node.animated_properties.items():
            if curve.is_empty:
                continue
            frames = sorted(curve.keyframes)
            animated.append(
                {
                    "node_id": node_id,
                    "node": node.name,
                    "property": key,
                    "keyframe_count": len(frames),
                    "first_frame": frames[0],
                    "last_frame": frames[-1],
                }
            )
    in_point, out_point = ctx.host.timeline_range()
    data = {
        "fps": project.fps,
        "width": project.width,
        "height": project.height,
        "duration_seconds": project.duration,
        "frame_count": int(project.max_frame) + 1,
        "max_frame": int(project.max_frame),
        "current_frame": project.current_frame,
        "in_point": in_point,
        "out_point": out_point,
        "animated_properties": animated,
    }
    return ToolResult(
        ok=True,
        summary=(
            f"{data['frame_count']} frames at {data['fps']} fps "
            f"({data['duration_seconds']:g}s); playhead at {data['current_frame']}; "
            f"{len(animated)} animated propert(ies)."
        ),
        data=data,
    )


def _edit(ctx: ToolContext) -> ToolResult:
    operation = str(ctx.args["operation"])
    project = ctx.project

    if operation == "goto_frame":
        if "frame" not in ctx.args:
            raise ToolError("INVALID_ARGUMENT", "'goto_frame' requires 'frame'.")
        target = int(ctx.args["frame"])
        if not 0 <= target <= int(project.max_frame):
            raise ToolError(
                "FRAME_OUT_OF_RANGE",
                f"Frame {target} is outside 0–{int(project.max_frame)}.",
            )
        ctx.host.set_current_frame(target)
        return ToolResult(
            ok=True,
            summary=f"Moved the playhead to frame {target}.",
            details=[f"~ Playhead → frame {target}"],
            data={"current_frame": target},
        )

    if operation in ("set_keyframe", "remove_keyframe"):
        if "node" not in ctx.args or "property" not in ctx.args:
            raise ToolError(
                "INVALID_ARGUMENT",
                f"'{operation}' requires 'node', 'property', and 'frame'.",
            )
        if "frame" not in ctx.args:
            raise ToolError("INVALID_ARGUMENT", f"'{operation}' requires 'frame'.")
        transaction = ctx.require_transaction("edit the timeline")
        node_id, node = resolve_node(ctx, str(ctx.args["node"]))
        key = str(ctx.args["property"])
        prop = node.get_property(key)
        if prop is None:
            raise ToolError(
                "UNKNOWN_PROPERTY",
                f"'{node.node_type}' has no property '{key}'. Available: "
                f"{short_list(sorted(k for k in node.properties if not k.startswith('_input_')))}",
            )
        if not isinstance(prop.value, (int, float)) or isinstance(prop.value, bool):
            raise ToolError(
                "NOT_ANIMATABLE",
                f"{node.node_type}.{key} is not a numeric property and cannot "
                "carry keyframes.",
            )
        frame = int(ctx.args["frame"])
        if not 0 <= frame <= int(project.max_frame):
            raise ToolError(
                "FRAME_OUT_OF_RANGE",
                f"Frame {frame} is outside 0–{int(project.max_frame)}.",
            )

        if operation == "set_keyframe":
            if "value" not in ctx.args:
                raise ToolError("INVALID_ARGUMENT", "'set_keyframe' requires 'value'.")
            value = float(ctx.args["value"])
            low, high = prop.slider_min_value, prop.slider_max_value
            if high > low and not (low <= value <= high):
                raise ToolError(
                    "PROPERTY_OUT_OF_RANGE",
                    f"{key} must be between {low} and {high} (received {value:g}).",
                )
            command: Any = SetKeyframeCommand(node_id, key, frame, value)
            action = f"~ Keyframe {node.name}.{key} = {value:g} at frame {frame}"
        else:
            command = RemoveKeyframeCommand(node_id, key, frame)
            action = f"- Remove keyframe {node.name}.{key} at frame {frame}"

        if not transaction.apply(
            ctx.project, command, action=action, changed_node_ids=[node_id]
        ):
            return ToolResult.failure(
                "COMMAND_REJECTED",
                f"The editor refused to change the keyframe on {key}.",
            )
        return ToolResult(
            ok=True,
            summary=action.replace("~ ", "").replace("- ", ""),
            details=[action],
            data={"node_id": node_id, "property": key, "frame": frame},
            changed_node_ids=[node_id],
        )

    raise ToolError(
        "UNSUPPORTED_OPERATION",
        f"Timeline operation '{operation}' is not supported. Supported: "
        "goto_frame, set_keyframe, remove_keyframe.",
    )
