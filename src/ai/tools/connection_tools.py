"""Connection tools.

Port compatibility is checked *before* a command is created so a bad wire
comes back as the structured error the spec asks for::

    {"error": "INCOMPATIBLE_PORT_TYPES",
     "source": "FloorTracker.confidence",
     "target": "VideoInput.frame"}

which the model can read and correct without guessing.
"""

from __future__ import annotations

from typing import Any

from ai.errors import ToolError
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_node, short_list
from ai.types import Permission, ToolResult
from core.history.commands import ConnectCommand, DisconnectCommand
from core.nodes.property_link import sockets_compatible


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="connection.create",
            description=(
                "Connect an output port to an input port. The input must accept "
                "the output's type; incompatible wires are rejected with a "
                "structured error. Connecting to an occupied input replaces the "
                "existing wire (undoable)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "from_node": {"type": "string", "description": "Source node id or name."},
                    "from_port": {"type": "string", "description": "Source output port name."},
                    "to_node": {"type": "string", "description": "Target node id or name."},
                    "to_port": {"type": "string", "description": "Target input port name."},
                },
                "required": ["from_node", "from_port", "to_node", "to_port"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_create,
            mutates=True,
            category="Connection",
        )
    )

    registry.register(
        ToolSpec(
            name="connection.delete",
            description=(
                "Remove a connection. Identify it by source and target, or by "
                "target node and input port alone."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "from_node": {"type": "string", "description": "Source node id or name."},
                    "from_port": {"type": "string", "description": "Source output port name."},
                    "to_node": {"type": "string", "description": "Target node id or name."},
                    "to_port": {"type": "string", "description": "Target input port name."},
                },
                "required": ["to_node", "to_port"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_delete,
            mutates=True,
            category="Connection",
        )
    )

    registry.register(
        ToolSpec(
            name="connection.list",
            description="List every connection in the graph.",
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_list,
            category="Connection",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _create(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("connect nodes")
    source_id, source = resolve_node(ctx, str(ctx.args["from_node"]))
    target_id, target = resolve_node(ctx, str(ctx.args["to_node"]))
    source_port = str(ctx.args["from_port"])
    target_port = str(ctx.args["to_port"])

    output = source.outputs.get(source_port)
    if output is None:
        raise ToolError(
            "UNKNOWN_OUTPUT",
            f"{source.name} ({source.node_type}) has no output "
            f"'{source_port}'. Available: {short_list(list(source.outputs))}",
        )
    input_port = target.inputs.get(target_port)
    if input_port is None:
        raise ToolError(
            "UNKNOWN_INPUT",
            f"{target.name} ({target.node_type}) has no input "
            f"'{target_port}'. Available: {short_list(list(target.inputs))}",
        )

    if not sockets_compatible(output.socket_type, input_port.socket_type):
        raise ToolError(
            "INCOMPATIBLE_PORT_TYPES",
            f"{source.node_type}.{source_port} ({output.type_label}) cannot "
            f"connect to {target.node_type}.{target_port} "
            f"({input_port.type_label}).",
        )

    if source_id == target_id:
        raise ToolError("SELF_CONNECTION", "A node cannot be connected to itself.")

    if ctx.project._would_create_cycle(source_id, target_id):
        raise ToolError(
            "CYCLE_NOT_ALLOWED",
            f"Connecting {source.name} → {target.name} would create a cycle. "
            "Aphelion evaluates the graph acyclically; restructure instead.",
        )

    replaced = None
    for connection in ctx.project.connections:
        if (
            connection.input_node_id == target_id
            and connection.input_slot == target_port
        ):
            replaced = connection
            break

    applied = transaction.apply(
        ctx.project,
        ConnectCommand(source_id, source_port, target_id, target_port),
        action=f"+ Connect {source.name}.{source_port} → {target.name}.{target_port}",
        changed_node_ids=[source_id, target_id],
    )
    if not applied:
        return ToolResult.failure(
            "COMMAND_REJECTED",
            f"The editor refused to connect {source.name}.{source_port} to "
            f"{target.name}.{target_port}.",
            technical={
                "error": "CONNECTION_REJECTED",
                "source": f"{source.node_type}.{source_port}",
                "target": f"{target.node_type}.{target_port}",
            },
        )

    warnings: list[str] = []
    if replaced is not None:
        previous_name = _node_name(ctx.project, replaced.output_node_id)
        warnings.append(
            f"Replaced existing wire from {previous_name}.{replaced.output_slot}."
        )
    return ToolResult(
        ok=True,
        summary=f"Connected {source.name}.{source_port} → {target.name}.{target_port}",
        details=[
            f"+ Connect {source.name}.{source_port} → {target.name}.{target_port}"
        ],
        data={
            "from_node": source_id,
            "from_port": source_port,
            "to_node": target_id,
            "to_port": target_port,
        },
        changed_node_ids=[source_id, target_id],
        warnings=warnings,
    )


def _delete(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("disconnect nodes")
    target_id, target = resolve_node(ctx, str(ctx.args["to_node"]))
    target_port = str(ctx.args["to_port"])

    candidates = [
        connection
        for connection in ctx.project.connections
        if connection.input_node_id == target_id
        and connection.input_slot == target_port
    ]
    if ctx.args.get("from_node"):
        source_id, _ = resolve_node(ctx, str(ctx.args["from_node"]))
        source_port = ctx.args.get("from_port")
        candidates = [
            connection
            for connection in candidates
            if connection.output_node_id == source_id
            and (source_port is None or connection.output_slot == source_port)
        ]

    if not candidates:
        return ToolResult.failure(
            "CONNECTION_NOT_FOUND",
            f"{target.name}.{target_port} has no matching connection.",
        )

    removed: list[str] = []
    for connection in candidates:
        source_name = _node_name(ctx.project, connection.output_node_id)
        if transaction.apply(
            ctx.project,
            DisconnectCommand(connection),
            action=f"- Disconnect {source_name}.{connection.output_slot} → "
                   f"{target.name}.{target_port}",
            changed_node_ids=[connection.output_node_id, target_id],
        ):
            removed.append(
                f"{connection.output_node_id}.{connection.output_slot}"
            )
    if not removed:
        return ToolResult.failure("COMMAND_REJECTED", "Nothing was disconnected.")
    return ToolResult(
        ok=True,
        summary=f"Removed {len(removed)} connection(s).",
        details=[f"- Disconnect {name}" for name in removed],
        data={"removed": removed},
        changed_node_ids=[target_id],
    )


def _list(ctx: ToolContext) -> ToolResult:
    rows = [
        {
            "from_node": connection.output_node_id,
            "from_name": _node_name(ctx.project, connection.output_node_id),
            "from_port": connection.output_slot,
            "to_node": connection.input_node_id,
            "to_name": _node_name(ctx.project, connection.input_node_id),
            "to_port": connection.input_slot,
        }
        for connection in sorted(
            ctx.project.connections,
            key=lambda item: (
                item.output_node_id,
                item.output_slot,
                item.input_node_id,
                item.input_slot,
            ),
        )
    ]
    return ToolResult(
        ok=True,
        summary=f"{len(rows)} connection(s).",
        data={"connections": rows},
    )


def _node_name(project: Any, node_id: str) -> str:
    node = project.nodes.get(node_id)
    return node.name if node is not None else node_id
