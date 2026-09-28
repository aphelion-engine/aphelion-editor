"""Selection tools.

Selection is how the user says "this": the assistant reads it, and can move
the selection/focus so the user can see what it is talking about. Selection
is view state, never document state, so these tools mutate nothing.
"""

from __future__ import annotations

from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_many
from ai.types import Permission, ToolResult


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="selection.get",
            description=(
                "Return the nodes currently selected in the graph. Use this to "
                "resolve 'this node' / 'the tracker I selected' before acting."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_get,
            category="Selection",
        )
    )

    registry.register(
        ToolSpec(
            name="selection.select",
            description=(
                "Select the given nodes in the graph and (optionally) frame "
                "them in the view, so the user can see what you are referring "
                "to. This does not change the project."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Node ids or names to select.",
                    },
                    "focus": {
                        "type": "boolean",
                        "description": "Zoom the graph to frame the selection.",
                    },
                },
                "required": ["nodes"],
            },
            permission=Permission.READ_PROJECT,
            handler=_select,
            mutates=False,
            category="Selection",
        )
    )

    registry.register(
        ToolSpec(
            name="selection.clear",
            description="Clear the graph selection.",
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_clear,
            mutates=False,
            category="Selection",
        )
    )


def _get(ctx: ToolContext) -> ToolResult:
    project = ctx.project
    rows = []
    for node_id in ctx.host.selected_node_ids():
        node = project.nodes.get(node_id)
        if node is None:
            continue
        rows.append(
            {
                "id": node_id,
                "type": node.node_type,
                "category": node.node_category,
                "name": node.name,
                "position": [float(node.x), float(node.y)],
            }
        )
    return ToolResult(
        ok=True,
        summary=f"{len(rows)} node(s) selected." if rows else "Nothing is selected.",
        data={"selected": rows},
    )


def _select(ctx: ToolContext) -> ToolResult:
    resolved = resolve_many(ctx, [str(item) for item in ctx.args["nodes"]])
    if not resolved:
        return ToolResult.failure("NODE_NOT_FOUND", "None of the listed nodes exist.")
    ids = [node_id for node_id, _ in resolved]
    ctx.host.select_nodes(ids, focus=bool(ctx.args.get("focus", False)))
    return ToolResult(
        ok=True,
        summary=f"Selected {len(ids)} node(s).",
        data={"selected": ids},
    )


def _clear(ctx: ToolContext) -> ToolResult:
    ctx.host.select_nodes([], focus=False)
    return ToolResult(ok=True, summary="Selection cleared.", data={"selected": []})
