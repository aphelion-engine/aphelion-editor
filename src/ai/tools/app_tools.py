"""Capability discovery.

The assistant should be able to ask what this build and this session can
actually do, instead of guessing and then pretending. This tool answers from
live state: the node registry, the tool registry, the granted permissions, the
host's own features, and the animation model the engine really implements.

It also reports what is *not* available, which matters more than the positive
list: a capability that does not exist must be refused, not improvised.
"""

from __future__ import annotations

from typing import Any

from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.types import Permission, ToolResult


def register_tools(registry: ToolRegistry) -> None:
    """Register app.list_capabilities."""
    registry.register(
        ToolSpec(
            name="app.list_capabilities",
            description=(
                "Report what this Aphelion build and session can actually do: "
                "node categories and count, the tools available right now "
                "grouped by area, granted permissions, animation support, host "
                "features such as frame rendering, and capabilities that are "
                "NOT available. Call it when unsure whether a feature exists "
                "instead of inventing one."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.NONE,
            handler=_list_capabilities,
            mutates=False,
            category="Application",
        )
    )


def _list_capabilities(ctx: ToolContext) -> ToolResult:
    registry = ctx.state.get("registry")

    tools: list[dict[str, Any]] = []
    if registry is not None:
        for spec in registry.tools():
            tools.append(
                {
                    "name": spec.name,
                    "category": spec.category,
                    "mutates": bool(spec.mutates),
                    "destructive": bool(spec.destructive),
                    "requires": spec.permission.name,
                }
            )
    by_category: dict[str, list[str]] = {}
    for entry in tools:
        by_category.setdefault(entry["category"], []).append(entry["name"])

    nodes = _node_overview()

    host_features = {
        "render_preview_frame": hasattr(ctx.host, "render_preview_frame"),
        "render_graph_snapshot": hasattr(ctx.host, "render_graph_snapshot"),
        "move_playhead": hasattr(ctx.host, "set_current_frame"),
        "timeline_range": hasattr(ctx.host, "timeline_range"),
        "highlight_nodes": hasattr(ctx.host, "highlight_nodes"),
        "region_proposal_ui": hasattr(ctx.host, "show_region_proposal"),
        "select_nodes": hasattr(ctx.host, "select_nodes"),
        "notify": hasattr(ctx.host, "notify"),
    }

    permissions = sorted(
        permission.name
        for permission in Permission
        if permission is not Permission.NONE and ctx.permissions.allows(permission)
    )

    return ToolResult(
        ok=True,
        summary=(
            f"{len(tools)} tool(s) across {len(by_category)} area(s); "
            f"{nodes['node_type_count']} node type(s) in "
            f"{len(nodes['categories'])} categories."
        ),
        data={
            "nodes": nodes,
            "tools": {
                "count": len(tools),
                "by_category": {k: sorted(v) for k, v in sorted(by_category.items())},
                "mutating": sorted(e["name"] for e in tools if e["mutates"]),
            },
            "permissions": permissions,
            "animation": {
                "keyframed_properties": True,
                "interpolation": "linear",
                "holds_outside_keyed_range": True,
                "bezier_or_ease_curves": False,
                "note": (
                    "Aphelion animates numeric properties with linear curves. "
                    "There is no bezier/ease editor, so ease requests are "
                    "approximated with extra linear keys and must be described "
                    "as such."
                ),
            },
            "host": {
                "features": host_features,
                "note": (
                    "These report which methods this host implements. A render can "
                    "still return no image in a headless session, so check for the "
                    "returned image rather than assuming one."
                ),
            },
            "not_available": _unavailable(host_features),
        },
    )


def _node_overview() -> dict[str, Any]:
    """Node registry overview, or an honest empty report."""
    try:
        from ai.source.nodes import node_catalog

        entries = node_catalog().entries()
    except Exception:  # noqa: BLE001 - registry trouble must not fail the tool
        return {"node_type_count": 0, "categories": [], "by_category": {}, "error": True}
    by_category: dict[str, list[str]] = {}
    for entry in entries.values():
        by_category.setdefault(entry.category or "Uncategorised", []).append(entry.type)
    return {
        "node_type_count": len(entries),
        "categories": sorted(by_category),
        "by_category": {k: sorted(v) for k, v in sorted(by_category.items())},
    }


def _unavailable(host_features: dict[str, bool]) -> list[str]:
    """Capabilities this build does not have. Never invent these."""
    missing: list[str] = []
    if not host_features.get("render_preview_frame"):
        missing.append("viewing rendered frames (no preview renderer on this host)")
    if not host_features.get("region_proposal_ui"):
        missing.append("visual region confirmation in the viewer")
    missing.extend(
        [
            "arbitrary Python or shell execution",
            "writing to the application source tree",
            "running a tracker as a one-shot background job (tracking is "
            "evaluated by the tracking nodes themselves)",
            "bezier/ease keyframe interpolation",
            "fetching live web pages",
        ]
    )
    return missing


__all__ = ["register_tools"]
