"""Workflow tools: understand the professional approach, then map it to real nodes.

``workflow.resolve`` is the tool that stops the agent guessing. Before it builds
anything for a non-trivial request it asks what the established way of doing
that work is, and gets back the ordered conceptual stages already mapped onto
node types that actually exist in this build — together with a flag for any
stage Aphelion cannot do.

``graph.auto_layout`` exposes the same layout engine the agent uses
automatically, so a user can ask for "tidy this up" and get a readable graph
without any processing behaviour changing.
"""

from __future__ import annotations

from ai.errors import ToolError
from ai.layout import LayoutMetrics, layout_new_nodes
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.types import Permission, ToolResult
from ai.workflows import match_request, resolve_request
from core.history.commands import MoveNodesCommand


def register_tools(registry: ToolRegistry) -> None:
    """Register the workflow.* and layout tools."""
    registry.register(
        ToolSpec(
            name="workflow.resolve",
            description=(
                "Work out how this request is normally accomplished in "
                "professional editing/compositing tools, then map each conceptual "
                "stage onto real Aphelion node types. Call this BEFORE building a "
                "graph for any non-trivial creative request: screen or wall "
                "replacement, grading, keying, stabilisation, tracked effects, "
                "cleanup, or compositing. Returns the ordered stages with the node "
                "types that implement each, the reason that approach is "
                "appropriate, and any stage Aphelion has no node for. If it "
                "returns no workflow, the request is a direct edit and needs no "
                "workflow research."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "The user's request in their own words.",
                    }
                },
            },
            permission=Permission.READ_PROJECT,
            handler=_resolve_workflow,
            mutates=False,
            category="Workflow",
        )
    )

    registry.register(
        ToolSpec(
            name="graph.auto_layout",
            description=(
                "Lay out nodes so the graph reads left to right in the order data "
                "flows, without changing any processing. Use it after adding "
                "nodes, or when the user asks to tidy, clean up, or organise the "
                "graph. Only the nodes you name are moved."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Nodes to lay out. Defaults to every node.",
                    }
                },
            },
            permission=Permission.EDIT_GRAPH,
            handler=_auto_layout,
            mutates=True,
            category="Graph",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _resolve_workflow(ctx: ToolContext) -> ToolResult:
    request = str(ctx.args.get("request", "") or "").strip()
    if not request:
        request = str(ctx.state.get("objective", "") or "").strip()
    if not request:
        raise ToolError(
            "INVALID_ARGUMENT",
            "Describe the request so the professional workflow can be identified.",
        )

    plan = resolve_request(request)
    if plan is None:
        candidates = [
            {"workflow": candidate.key, "title": candidate.title, "score": score}
            for score, candidate in match_request(request, limit=3)
        ]
        return ToolResult(
            ok=True,
            summary=(
                "No established workflow needed: this is a direct edit. Apply it "
                "with the node/connection tools."
            ),
            data={
                "workflow": None,
                "reason": "The request does not name a workflow-level goal.",
                "near_misses": candidates,
            },
        )

    payload = plan.to_dict()
    ctx.state["workflow"] = {
        "key": plan.recipe.key,
        "title": plan.recipe.title,
        "rationale": plan.recipe.rationale,
        "kind": plan.recipe.kind,
        "unsupported": [match.stage.key for match in plan.unsupported],
        "stage_count": len(plan.matches),
    }

    unsupported = [match.stage.title for match in plan.unsupported]
    detail = [f"✓ Workflow: {plan.recipe.title}"]
    for match in plan.matches:
        if match.supported:
            detail.append(f"  {match.stage.title} → {match.primary}")
        elif not match.stage.optional:
            detail.append(f"  ✕ {match.stage.title} → no Aphelion node")

    return ToolResult(
        ok=True,
        summary=(
            f"{plan.recipe.title}: "
            + " → ".join(
                match.primary or "(unsupported)" for match in plan.matches
            )
        ),
        data=payload,
        details=detail,
        warnings=(
            ["Aphelion has no node for: " + ", ".join(unsupported)]
            if unsupported
            else []
        ),
        technical={"instruction": plan.describe()},
    )


def _auto_layout(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("lay out the graph")
    project = ctx.project
    requested = ctx.args.get("nodes")

    if requested:
        from ai.tools.helpers import resolve_many

        target_ids = [
            node_id for node_id, _node in resolve_many(ctx, [str(n) for n in requested])
        ]
    else:
        target_ids = list(project.nodes)

    if not target_ids:
        raise ToolError("NODE_NOT_FOUND", "There are no nodes to lay out.")

    before: dict[str, tuple[float, float]] = {}
    for node_id in target_ids:
        node = project.nodes.get(node_id)
        if node is not None:
            before[node_id] = (float(node.x), float(node.y))

    after = layout_new_nodes(project, target_ids, metrics=LayoutMetrics())
    if not after:
        return ToolResult(ok=True, summary="Layout is already clean.")

    if not transaction.apply(
        project,
        MoveNodesCommand(before, after),
        action=f"~ Arrange {len(after)} node(s)",
        changed_node_ids=list(after),
    ):
        return ToolResult(ok=True, summary="Layout is already clean.")

    return ToolResult(
        ok=True,
        summary=f"Laid out {len(after)} node(s) left to right.",
        details=[f"~ Arrange {len(after)} node(s)"],
        data={"moved": len(after)},
        changed_node_ids=list(after),
    )


__all__ = ["register_tools"]
