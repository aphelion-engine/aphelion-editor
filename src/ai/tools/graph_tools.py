"""Graph tools: inspect, validate, arrange, and organise into sections.

The arrange/organise path is a real, minimal change — it computes node
positions and applies them through ``MoveNodesCommand`` — so organising a
messy graph is a single undoable action like any other.
"""

from __future__ import annotations

from typing import Any

from ai.errors import ToolError
from ai.graph_model import graph_digest, graph_to_ai, project_summary
from ai.sections import SECTION_ORDER, group_by_section
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_many, resolve_node, short_list
from ai.types import Permission, ToolResult
from ai.validation import validate_project
from core.graph_layout import compute_graph_layout
from core.history.commands import MoveNodesCommand

#: Horizontal distance between section columns.
SECTION_COLUMN_WIDTH_PX: float = 480.0
#: Vertical pack spacing between nodes inside one section.
SECTION_ROW_GAP_PX: float = 140.0
#: Origin for AI-arranged sections, chosen to sit right of typical content.
SECTION_ORIGIN_X: float = 120.0
SECTION_ORIGIN_Y: float = 80.0


def register_tools(registry: ToolRegistry) -> None:
    """Register every graph.* / group.* tool."""

    registry.register(
        ToolSpec(
            name="graph.list",
            description=(
                "Return the AI-readable graph document: every node with its "
                "type, name, and position, plus every connection and any "
                "defined sections. This is the same representation the .apgraph "
                "exporter produces."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include_properties": {
                        "type": "boolean",
                        "description": "Include property values (default false keeps it small).",
                    }
                },
            },
            permission=Permission.READ_PROJECT,
            handler=_list,
            category="Graph",
        )
    )

    registry.register(
        ToolSpec(
            name="graph.inspect",
            description=(
                "Inspect the current graph in depth: per-node property values, "
                "the full connection list, section membership, and validation "
                "issues. Use this to explain or repair an existing graph."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_inspect,
            category="Graph",
        )
    )

    registry.register(
        ToolSpec(
            name="graph.validate",
            description=(
                "Validate the graph and return structured issues: broken "
                "references, unknown ports, incompatible port types, missing "
                "required inputs, out-of-range properties, and duplicate names. "
                "Call this after any edit."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "errors_only": {
                        "type": "boolean",
                        "description": "Hide informational warnings.",
                    }
                },
            },
            permission=Permission.READ_PROJECT,
            handler=_validate,
            category="Graph",
        )
    )

    registry.register(
        ToolSpec(
            name="graph.organize",
            description=(
                "Auto-arrange nodes. Use sections=true to lay the graph out as "
                "labelled INPUT / TRACKING / EFFECTS / COMPOSITING / OUTPUT "
                "columns; this respects existing work by only moving positions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "boolean",
                        "description": "Arrange into labelled processing-stage columns.",
                    },
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict the arrangement to these nodes.",
                    },
                },
            },
            permission=Permission.EDIT_GRAPH,
            handler=_organize,
            mutates=True,
            category="Graph",
        )
    )

    registry.register(
        ToolSpec(
            name="group.create",
            description=(
                "Create a named section containing the given nodes, arranging "
                "them into their own column. Aphelion has no persistent group "
                "object; a section is a labelled, spatially arranged set of "
                "nodes and is the supported equivalent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Section label."},
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Member node ids or names.",
                    },
                },
                "required": ["name"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_group_create,
            mutates=True,
            category="Graph",
        )
    )

    registry.register(
        ToolSpec(
            name="group.add_nodes",
            description="Add nodes to an existing section and re-arrange it.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Existing section label."},
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Node ids or names to add.",
                    },
                },
                "required": ["name", "nodes"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_group_add,
            mutates=True,
            category="Graph",
        )
    )

    registry.register(
        ToolSpec(
            name="group.rename",
            description="Rename a section.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Current section label."},
                    "new_name": {"type": "string", "description": "New section label."},
                },
                "required": ["name", "new_name"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_group_rename,
            mutates=True,
            category="Graph",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _sections_payload(ctx: ToolContext) -> list[dict[str, Any]]:
    return [dict(section) for section in ctx.host.graph_sections()]


def _list(ctx: ToolContext) -> ToolResult:
    document = graph_to_ai(
        ctx.project,
        include_properties=bool(ctx.args.get("include_properties", False)),
    )
    document["groups"] = _sections_payload(ctx)
    document["summary"] = project_summary(ctx.project)
    return ToolResult(
        ok=True,
        summary=f"{len(document['nodes'])} node(s), "
                f"{len(document['connections'])} connection(s).",
        data=document,
    )


def _inspect(ctx: ToolContext) -> ToolResult:
    digest = graph_digest(ctx.project)
    report = validate_project(ctx.project)
    digest["summary"] = project_summary(ctx.project)
    digest["sections"] = _sections_payload(ctx)
    digest["validation"] = report.to_dict()
    # Keep the payload bounded: the model can ask for details per node.
    if len(digest["nodes"]) > 60:
        digest["nodes"] = digest["nodes"][:60]
        digest["nodes_truncated"] = True
    return ToolResult(
        ok=True,
        summary=f"Graph has {len(ctx.project.nodes)} node(s); {report.summary_line()}",
        data=digest,
    )


def _validate(ctx: ToolContext) -> ToolResult:
    report = validate_project(ctx.project)
    errors_only = bool(ctx.args.get("errors_only", False))
    payload = report.to_dict(include_warnings=not errors_only)
    payload["validation_error_count"] = len(report.errors)
    payload["validation_warning_count"] = len(report.warnings)
    return ToolResult(
        ok=report.ok,
        summary=report.summary_line(),
        data=payload,
        details=[
            f"✓ Validation: {report.summary_line()}" if report.ok
            else f"! Validation: {report.summary_line()}"
        ],
        error_code="" if report.ok else "GRAPH_INVALID",
        error="" if report.ok else report.summary_line(),
    )


def _organize(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("organize the graph")
    project = ctx.project
    requested = ctx.args.get("nodes")
    if requested:
        target_ids = {node_id for node_id, _ in resolve_many(ctx, [str(n) for n in requested])}
    else:
        target_ids = set(project.nodes)

    if not target_ids:
        raise ToolError("NODE_NOT_FOUND", "There are no nodes to arrange.")

    before: dict[str, tuple[float, float]] = {
        node_id: (float(project.nodes[node_id].x), float(project.nodes[node_id].y))
        for node_id in target_ids
    }

    if bool(ctx.args.get("sections", False)):
        after = _section_positions(project, target_ids)
    else:
        sizes = {
            node_id: (int(project.nodes[node_id].width), int(project.nodes[node_id].height))
            for node_id in target_ids
        }
        connections = [
            connection
            for connection in project.connections
            if connection.output_node_id in target_ids
            and connection.input_node_id in target_ids
        ]
        after = compute_graph_layout(
            {node_id: project.nodes[node_id] for node_id in target_ids},
            connections,
            sizes=sizes,
        )

    if not transaction.apply(
        project,
        MoveNodesCommand(before, after),
        action=f"~ Arrange {len(after)} node(s)",
        changed_node_ids=list(after),
    ):
        return ToolResult(ok=True, summary="Graph is already arranged.")

    label = "sections" if ctx.args.get("sections") else "data flow"
    return ToolResult(
        ok=True,
        summary=f"Arranged {len(after)} node(s) by {label}.",
        details=[f"~ Arrange {len(after)} node(s) by {label}"],
        data={"moved": len(after), "positions": {k: list(v) for k, v in after.items()}},
        changed_node_ids=list(after),
    )


def _group_create(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("create a section")
    name = str(ctx.args["name"]).strip().upper()
    if not name:
        raise ToolError("INVALID_ARGUMENT", "A section name is required.")
    sections = _sections_payload(ctx)
    if any(str(section["name"]).upper() == name for section in sections):
        raise ToolError("SECTION_EXISTS", f"A section named '{name}' already exists.")

    member_ids: list[str] = []
    if ctx.args.get("nodes"):
        member_ids = [
            node_id
            for node_id, _ in resolve_many(ctx, [str(n) for n in ctx.args["nodes"]])
        ]

    sections.append({"name": name, "node_ids": member_ids})
    ctx.host.set_graph_sections(sections)

    moved = _arrange_sections(ctx, transaction)
    actions = [f"+ Create section {name} ({len(member_ids)} node(s))"]
    actions.extend(moved)
    return ToolResult(
        ok=True,
        summary=f"Created section {name} with {len(member_ids)} node(s).",
        details=actions,
        data={"sections": sections, "moved": len(moved)},
        changed_node_ids=member_ids,
    )


def _group_add(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("add nodes to a section")
    name = str(ctx.args["name"]).strip()
    sections = _sections_payload(ctx)
    section = _find_section(sections, name)
    if section is None:
        raise ToolError(
            "SECTION_NOT_FOUND",
            f"No section named '{name}'. Existing: "
            f"{short_list([str(s['name']) for s in sections])}",
        )
    added = [
        node_id
        for node_id, _ in resolve_many(ctx, [str(n) for n in ctx.args["nodes"]])
    ]
    existing = list(section.get("node_ids", []))
    for node_id in added:
        if node_id not in existing:
            existing.append(node_id)
    section["node_ids"] = existing
    ctx.host.set_graph_sections(sections)

    moved = _arrange_sections(ctx, transaction)
    return ToolResult(
        ok=True,
        summary=f"Added {len(added)} node(s) to {section['name']}.",
        details=[f"+ Add {len(added)} node(s) to {section['name']}", *moved],
        data={"sections": sections},
        changed_node_ids=added,
    )


def _group_rename(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("rename a section")
    sections = _sections_payload(ctx)
    section = _find_section(sections, str(ctx.args["name"]))
    if section is None:
        raise ToolError("SECTION_NOT_FOUND", f"No section named '{ctx.args['name']}'.")
    new_name = str(ctx.args["new_name"]).strip().upper()
    if not new_name:
        raise ToolError("INVALID_ARGUMENT", "The new section name is required.")
    old_name = str(section["name"])
    section["name"] = new_name
    ctx.host.set_graph_sections(sections)
    moved = _arrange_sections(ctx, transaction)
    return ToolResult(
        ok=True,
        summary=f"Renamed section {old_name} to {new_name}.",
        details=[f"~ Rename section {old_name} → {new_name}", *moved],
        data={"sections": sections},
    )


# ======================================================================
# Arrangement
# ======================================================================


def _arrange_sections(ctx: ToolContext, transaction: Any) -> list[str]:
    """Re-arrange every sectioned node and record it in ``transaction``."""
    project = ctx.project
    positions = _section_positions(project, set(project.nodes))
    before: dict[str, tuple[float, float]] = {}
    after: dict[str, tuple[float, float]] = {}
    for node_id, target in positions.items():
        node = project.nodes.get(node_id)
        if node is None:
            continue
        current = (float(node.x), float(node.y))
        if current == target:
            continue
        before[node_id] = current
        after[node_id] = target
    if not after:
        return []
    if not transaction.apply(project, MoveNodesCommand(before, after)):
        return []
    return [f"~ Arrange {len(after)} section node(s)"]


def _section_positions(
    project: Any,
    node_ids: set[str],
) -> dict[str, tuple[float, float]]:
    """Return section-band positions for the requested nodes.

    Nodes in a defined section are placed in that section's column. Nodes with
    no section membership fall back to their automatic stage, so an
    arrange-with-sections call organises the whole graph coherently.
    """
    sections = [
        {
            "name": str(section.get("name", "")),
            "node_ids": [str(n) for n in section.get("node_ids", [])],
        }
        for section in getattr(project, "_ai_sections", [])
    ]

    order: list[str] = list(SECTION_ORDER)
    assigned: dict[str, str] = {}
    for section in sections:
        if section["name"] not in order:
            order.append(section["name"])
        for node_id in section["node_ids"]:
            assigned[node_id] = section["name"]

    automatic = group_by_section(
        {node_id: project.nodes[node_id] for node_id in node_ids if node_id in project.nodes}
    )
    for section_name, ids in automatic.items():
        for node_id in ids:
            assigned.setdefault(node_id, section_name)

    layout = compute_graph_layout(
        {node_id: project.nodes[node_id] for node_id in node_ids if node_id in project.nodes},
        [
            connection
            for connection in project.connections
            if connection.output_node_id in node_ids
            and connection.input_node_id in node_ids
        ],
        sizes={
            node_id: (int(project.nodes[node_id].width), int(project.nodes[node_id].height))
            for node_id in node_ids
            if node_id in project.nodes
        },
    )

    columns: dict[str, list[str]] = {}
    for node_id, section_name in assigned.items():
        columns.setdefault(section_name, []).append(node_id)

    positions: dict[str, tuple[float, float]] = {}
    for column_index, section_name in enumerate(order):
        members = columns.get(section_name)
        if not members:
            continue
        members.sort(key=lambda node_id: (layout.get(node_id, (0.0, 0.0))[1], node_id))
        x = SECTION_ORIGIN_X + column_index * SECTION_COLUMN_WIDTH_PX
        y = SECTION_ORIGIN_Y
        for node_id in members:
            positions[node_id] = (x, y)
            node = project.nodes.get(node_id)
            height = float(getattr(node, "height", 100) or 100)
            y += max(SECTION_ROW_GAP_PX, height + 40.0)
    return positions


def _find_section(sections: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = name.strip().lower()
    for section in sections:
        if str(section.get("name", "")).strip().lower() == target:
            return section
    return None


def _node_name(project: Any, node_id: str) -> str:
    node = project.nodes.get(node_id)
    return node.name if node is not None else node_id
