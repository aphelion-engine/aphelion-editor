"""Vision tools.

Vision is permission-gated and never assumed: these tools check that the user
granted ``ACCESS_VISION`` *and* that the host can actually produce an image. A
provider without vision support never receives them (the engine filters by
capability as well as permission).

Region proposals are deliberately *proposals*. The tool does not guess a
region; it records what the model saw and hands it back as normalized
coordinates plus an editable overlay in the viewport. Applying it is a
separate, explicit ``tracking.set_region`` call, so a wrong guess is one undo
away and always visible to the user first.
"""

from __future__ import annotations

from typing import Any

from ai.errors import ToolError
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_node
from ai.types import Permission, ToolResult


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="graph.snapshot",
            description=(
                "Render the node graph to an image so you can reason about its "
                "layout. Only available with the vision permission and a "
                "vision-capable model."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict the snapshot to these nodes.",
                    }
                },
            },
            permission=Permission.ACCESS_VISION,
            handler=_graph_snapshot,
            category="Vision",
        )
    )

    registry.register(
        ToolSpec(
            name="vision.preview_frame",
            description=(
                "Fetch the frame currently shown in the viewport (or a specific "
                "frame) as an image so you can see the footage. Use this for "
                "requests like 'track the television on the right wall'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "frame": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Frame to fetch; defaults to the current frame.",
                    },
                    "max_width": {
                        "type": "integer",
                        "minimum": 64,
                        "maximum": 2048,
                        "description": "Downscale the image to this width.",
                    },
                },
            },
            permission=Permission.ACCESS_VISION,
            handler=_preview_frame,
            category="Vision",
        )
    )

    registry.register(
        ToolSpec(
            name="vision.propose_region",
            description=(
                "Propose a region you identified in a frame or snapshot, in "
                "normalized coordinates (0.0–1.0). The proposal is shown to the "
                "user as an editable overlay; it changes nothing on its own. "
                "Follow it with tracking.set_region once the user confirms."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "What the region is, e.g. 'floor' or 'wall'.",
                    },
                    "rect": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y, width, height] normalized to the image.",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "How confident you are in the region.",
                    },
                },
                "required": ["label", "rect"],
            },
            permission=Permission.ACCESS_VISION,
            handler=_propose_region,
            category="Vision",
        )
    )


def _ensure_vision(ctx: ToolContext) -> None:
    ctx.require(Permission.ACCESS_VISION, "look at frames or graph images")


def _graph_snapshot(ctx: ToolContext) -> ToolResult:
    _ensure_vision(ctx)
    node_ids = ctx.args.get("nodes")
    ids: list[str] | None = None
    if node_ids:
        ids = [resolve_node(ctx, str(item))[0] for item in node_ids]
    image = ctx.host.render_graph_snapshot(ids)
    if not image:
        return ToolResult.failure(
            "VISION_UNAVAILABLE",
            "This editor session cannot render a graph snapshot.",
        )
    return ToolResult(
        ok=True,
        summary="Rendered a graph snapshot.",
        data={"node_ids": ids or "all"},
        images=[image],
    )


def _preview_frame(ctx: ToolContext) -> ToolResult:
    _ensure_vision(ctx)
    frame = ctx.args.get("frame")
    max_width = ctx.args.get("max_width")
    image = ctx.host.render_preview_frame(
        frame=int(frame) if frame is not None else None,
        max_width=int(max_width) if max_width is not None else 640,
    )
    if not image:
        return ToolResult.failure(
            "VISION_UNAVAILABLE",
            "No preview frame is available yet. Connect a source to the active "
            "Viewer so there is something to look at.",
        )
    return ToolResult(
        ok=True,
        summary="Fetched the preview frame.",
        data={"frame": frame},
        images=[image],
    )


def _propose_region(ctx: ToolContext) -> ToolResult:
    _ensure_vision(ctx)
    rect = [float(value) for value in ctx.args["rect"]]
    if len(rect) != 4:
        raise ToolError(
            "INVALID_ARGUMENT", "'rect' must be [x, y, width, height]."
        )
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        raise ToolError("INVALID_ARGUMENT", "'rect' width and height must be positive.")
    if not all(-1.0 <= value <= 2.0 for value in rect):
        raise ToolError(
            "REGION_OUT_OF_BOUNDS",
            "Normalized coordinates must be within -1.0 to 2.0.",
        )

    proposal: dict[str, Any] = {
        "label": str(ctx.args["label"]),
        "rect": rect,
        "center": [x + width / 2.0, y + height / 2.0],
        "size": [width, height],
        "confidence": float(ctx.args.get("confidence", 0.5)),
    }
    ctx.host.show_region_proposal(proposal)
    return ToolResult(
        ok=True,
        summary=(
            f"Proposed region '{proposal['label']}' at "
            f"x={x:.3f}, y={y:.3f}, w={width:.3f}, h={height:.3f}."
        ),
        details=[f"~ Propose region '{proposal['label']}' (user-editable)"],
        data={"proposal": proposal},
    )
