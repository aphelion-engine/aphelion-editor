"""Node tools: registry discovery, lifecycle, layout, and properties.

These are the tools that make "build me a tracked floor grid" real. Node
creation goes through :class:`~core.history.commands.AddNodeCommand`, deletion
through ``RemoveNodesCommand``, movement through ``MoveNodesCommand``, and
property edits through ``SetPropertyCommand`` — the same commands the editor's
own UI pushes, so undo, dirty marking, and observers all behave identically.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ai.errors import ToolError
from ai.graph_model import (describe_node_instance, describe_node_type,
                            list_node_types, resolve_type)
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.tools.helpers import resolve_many, resolve_node, short_list, suggest
from ai.types import Permission, ToolResult
from core.history.commands import (AddNodeCommand, MoveNodesCommand,
                                   RemoveNodesCommand, RenameNodeCommand,
                                   SetPropertyCommand)
from core.nodes.base import NodePropertyInputType


def register_tools(registry: ToolRegistry) -> None:
    """Register every node.* tool."""

    registry.register(
        ToolSpec(
            name="node.list_types",
            description=(
                "List the node types Aphelion can actually create, optionally "
                "filtered by category or a search phrase. Always use this "
                "instead of guessing a type name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Restrict to one registry category.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Case-insensitive text matched against type, category, and description.",
                    },
                },
            },
            permission=Permission.READ_PROJECT,
            handler=_list_types,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.describe_type",
            description=(
                "Return the full contract of one node type: category, "
                "description, every input and output port with its documentation "
                "and type, and every property with defaults, ranges, and enum "
                "options. Call this before creating or configuring a type you "
                "have not used in this conversation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Registered node type name, e.g. 'Floor Tracker'.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category when a name is ambiguous.",
                    },
                },
                "required": ["type"],
            },
            permission=Permission.READ_PROJECT,
            handler=_describe_type,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.list",
            description="List the nodes in the current graph with their ids, types, names, and positions.",
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_list_nodes,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.inspect",
            description=(
                "Inspect one node in depth: current property values, animated "
                "properties, its port contract, and every connection attached to "
                "it. Accepts a node id, a node name, or 'this'/'selected' for "
                "the current selection."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {
                        "type": "string",
                        "description": "Node id, name, or 'selected'.",
                    }
                },
                "required": ["node"],
            },
            permission=Permission.READ_PROJECT,
            handler=_inspect,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.create",
            description=(
                "Create one node of a registered type. Omit position to let "
                "Aphelion place it clear of existing nodes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Registered node type name.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category for ambiguous names.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional display name for the new node.",
                    },
                    "position": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y] graph position in pixels.",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Optional property values applied at creation time.",
                        "additionalProperties": True,
                    },
                },
                "required": ["type"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_create,
            mutates=True,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.delete",
            description=(
                "Delete one or more nodes and their connections. Destructive: "
                "always confirm the target list in your reply, and expect the "
                "user to approve before it is applied."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Node ids or names to delete.",
                    }
                },
                "required": ["nodes"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_delete,
            mutates=True,
            destructive=True,
            standalone=True,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.move",
            description=(
                "Move nodes in the graph. Supply either an absolute position "
                "(single node) or a delta applied to all listed nodes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Node ids or names to move.",
                    },
                    "position": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Absolute [x, y] for a single node.",
                    },
                    "delta": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Relative [dx, dy] applied to every listed node.",
                    },
                },
                "required": ["nodes"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_move,
            mutates=True,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.rename",
            description="Rename a node.",
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id or name."},
                    "name": {"type": "string", "description": "New display name."},
                },
                "required": ["node", "name"],
            },
            permission=Permission.EDIT_GRAPH,
            handler=_rename,
            mutates=True,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.get_property",
            description="Read one property value from a node.",
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id or name."},
                    "property": {"type": "string", "description": "Property key."},
                },
                "required": ["node", "property"],
            },
            permission=Permission.READ_PROJECT,
            handler=_get_property,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.set_property",
            description=(
                "Set one property on a node. Enum properties accept the option "
                "name (for example 'Accurate'). Numeric properties accept only "
                "values inside their documented range. Call node.describe_type "
                "first when unsure of the key, range, or options."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id or name."},
                    "property": {"type": "string", "description": "Property key."},
                    "value": {
                        "description": "New value (number, boolean, text, or enum option name).",
                    },
                },
                "required": ["node", "property", "value"],
            },
            permission=Permission.EDIT_PROPERTIES,
            handler=_set_property,
            mutates=True,
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.list_inputs",
            description="List the input ports of a node, with type and documentation.",
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id or name."}
                },
                "required": ["node"],
            },
            permission=Permission.READ_PROJECT,
            handler=_list_ports_factory(True),
            category="Node",
        )
    )

    registry.register(
        ToolSpec(
            name="node.list_outputs",
            description="List the output ports of a node, with type and documentation.",
            parameters={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node id or name."}
                },
                "required": ["node"],
            },
            permission=Permission.READ_PROJECT,
            handler=_list_ports_factory(False),
            category="Node",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _list_types(ctx: ToolContext) -> ToolResult:
    rows = list_node_types(
        category=ctx.args.get("category"),
        query=ctx.args.get("query"),
    )
    return ToolResult(
        ok=True,
        summary=f"{len(rows)} node type(s) available.",
        data={"types": rows},
    )


def _describe_type(ctx: ToolContext) -> ToolResult:
    description = describe_node_type(
        str(ctx.args["type"]),
        category=ctx.args.get("category"),
    )
    if description is None:
        candidates = [row["type"] for row in list_node_types(limit=10_000)]
        raise ToolError(
            "UNKNOWN_NODE_TYPE",
            f"'{ctx.args['type']}' is not a registered node type. "
            + (
                f"Close matches: {', '.join(suggest(str(ctx.args['type']), candidates))}. "
                if suggest(str(ctx.args["type"]), candidates)
                else ""
            )
            + "This capability does not exist in Aphelion; do not invent it.",
        )
    payload = description.to_dict()
    return ToolResult(
        ok=True,
        summary=f"{payload['type']} ({payload['category']}): "
                f"{len(payload['inputs'])} in, {len(payload['outputs'])} out, "
                f"{len(payload['properties'])} properties.",
        data=payload,
    )


def _list_nodes(ctx: ToolContext) -> ToolResult:
    rows = [
        {
            "id": node_id,
            "type": node.node_type,
            "category": node.node_category,
            "name": node.name,
            "position": [float(node.x), float(node.y)],
        }
        for node_id, node in sorted(ctx.project.nodes.items())
    ]
    return ToolResult(ok=True, summary=f"{len(rows)} node(s).", data={"nodes": rows})


def _inspect(ctx: ToolContext) -> ToolResult:
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    detail = describe_node_instance(node_id, node)
    type_contract = describe_node_type(node.node_type, category=node.node_category)
    detail["contract"] = type_contract.to_dict() if type_contract else None

    project = ctx.project
    detail["connections"] = {
        "inputs": [
            {
                "slot": connection.input_slot,
                "from": connection.output_node_id,
                "from_name": _node_name(project, connection.output_node_id),
                "from_slot": connection.output_slot,
            }
            for connection in sorted(
                (c for c in project.connections if c.input_node_id == node_id),
                key=lambda c: c.input_slot,
            )
        ],
        "outputs": [
            {
                "slot": connection.output_slot,
                "to": connection.input_node_id,
                "to_name": _node_name(project, connection.input_node_id),
                "to_slot": connection.input_slot,
            }
            for connection in sorted(
                (c for c in project.connections if c.output_node_id == node_id),
                key=lambda c: c.output_slot,
            )
        ],
    }
    return ToolResult(
        ok=True,
        summary=f"{node.name} ({node.node_type})",
        data=detail,
    )


def _create(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("create a node")
    type_name = str(ctx.args["type"])
    category = ctx.args.get("category")
    info = resolve_type(type_name, category)
    if info is None:
        candidates = [row["type"] for row in list_node_types(limit=10_000)]
        raise ToolError(
            "UNKNOWN_NODE_TYPE",
            f"Cannot create '{type_name}': no such node type. "
            + (
                f"Close matches: {', '.join(suggest(type_name, candidates))}. "
                if suggest(type_name, candidates)
                else ""
            )
            + "Use node.list_types to see what exists, and tell the user if "
            "Aphelion has no node for what they asked for.",
        )

    try:
        node = info.create_instance()
    except Exception as exc:  # noqa: BLE001 - a plugin type may fail to build
        raise ToolError(
            "NODE_CONSTRUCTION_FAILED",
            f"'{type_name}' could not be instantiated: {exc}",
        ) from exc

    position = ctx.args.get("position")
    if position is not None:
        node.x = float(position[0])
        node.y = float(position[1])
    else:
        x, y = ctx.host.next_free_position(info.category)
        node.x, node.y = float(x), float(y)

    if ctx.args.get("name"):
        node.name = str(ctx.args["name"])

    command = AddNodeCommand(node)
    if not transaction.apply(
        ctx.project,
        command,
        action=f"+ Add {node.node_type} '{node.name}'",
    ):
        return ToolResult.failure(
            "COMMAND_REJECTED", f"The editor refused to add {node.node_type}."
        )
    new_id = command.node_id
    if new_id is None:
        return ToolResult.failure("COMMAND_REJECTED", "Node was not registered.")

    warnings: list[str] = []
    properties = ctx.args.get("properties") or {}
    if isinstance(properties, dict):
        for key, raw in properties.items():
            try:
                member = _coerce_property_value(node, key, raw)
            except ToolError as exc:
                warnings.append(str(exc))
                continue
            transaction.apply(
                ctx.project,
                SetPropertyCommand(new_id, key, member),
                action=f"~ {node.name}.{key} = {_display(member)}",
            )

    return ToolResult(
        ok=True,
        summary=f"Created {node.node_type} '{node.name}'",
        details=[f"+ Add {node.node_type} '{node.name}'"],
        data={
            "node_id": new_id,
            "type": node.node_type,
            "category": node.node_category,
            "name": node.name,
            "position": [float(node.x), float(node.y)],
            "inputs": list(node.inputs),
            "outputs": list(node.outputs),
        },
        changed_node_ids=[new_id],
        warnings=warnings,
    )


def _delete(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("delete nodes")
    resolved = resolve_many(ctx, [str(item) for item in ctx.args["nodes"]])
    if not resolved:
        raise ToolError("NODE_NOT_FOUND", "None of the listed nodes exist.")
    ids = [node_id for node_id, _ in resolved]
    names = [f"{node.name} ({node_id})" for node_id, node in resolved]
    if not transaction.apply(
        ctx.project,
        RemoveNodesCommand(ids),
        action=f"- Delete {short_list(names)}",
        changed_node_ids=ids,
    ):
        return ToolResult.failure("COMMAND_REJECTED", "The editor refused the deletion.")
    return ToolResult(
        ok=True,
        summary=f"Deleted {len(ids)} node(s).",
        details=[f"- Delete {short_list(names)}"],
        data={"deleted": ids},
        changed_node_ids=ids,
    )


def _move(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("move nodes")
    resolved = resolve_many(ctx, [str(item) for item in ctx.args["nodes"]])
    if not resolved:
        raise ToolError("NODE_NOT_FOUND", "None of the listed nodes exist.")

    position = ctx.args.get("position")
    delta = ctx.args.get("delta")
    if position is None and delta is None:
        raise ToolError(
            "INVALID_ARGUMENT", "Provide either 'position' or 'delta'."
        )
    if position is not None and len(resolved) != 1:
        raise ToolError(
            "INVALID_ARGUMENT",
            "An absolute 'position' needs exactly one node; use 'delta' for several.",
        )

    before: dict[str, tuple[float, float]] = {}
    after: dict[str, tuple[float, float]] = {}
    for node_id, node in resolved:
        before[node_id] = (float(node.x), float(node.y))
        if position is not None:
            target = (float(position[0]), float(position[1]))
        else:
            target = (float(node.x) + float(delta[0]), float(node.y) + float(delta[1]))
        after[node_id] = target

    if not transaction.apply(
        ctx.project,
        MoveNodesCommand(before, after),
        action=f"~ Move {short_list([node.name for _, node in resolved])}",
        changed_node_ids=[node_id for node_id, _ in resolved],
    ):
        return ToolResult.failure("COMMAND_REJECTED", "Nothing moved.")
    return ToolResult(
        ok=True,
        summary=f"Moved {len(resolved)} node(s).",
        details=[f"~ Move {short_list([node.name for _, node in resolved])}"],
        data={"positions": {node_id: list(pos) for node_id, pos in after.items()}},
        changed_node_ids=[node_id for node_id, _ in resolved],
    )


def _rename(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("rename a node")
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    new_name = str(ctx.args["name"]).strip()
    if not new_name:
        raise ToolError("INVALID_ARGUMENT", "The new name cannot be empty.")
    if new_name == node.name:
        return ToolResult(ok=True, summary=f"'{new_name}' is already the name.")
    old_name = node.name
    if not transaction.apply(
        ctx.project,
        RenameNodeCommand(node_id, new_name),
        action=f"~ Rename '{old_name}' → '{new_name}'",
        changed_node_ids=[node_id],
    ):
        return ToolResult.failure("COMMAND_REJECTED", "The rename was refused.")
    return ToolResult(
        ok=True,
        summary=f"Renamed '{old_name}' to '{new_name}'.",
        details=[f"~ Rename '{old_name}' → '{new_name}'"],
        data={"node_id": node_id, "name": new_name},
        changed_node_ids=[node_id],
    )


def _get_property(ctx: ToolContext) -> ToolResult:
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    key = str(ctx.args["property"])
    prop = node.get_property(key)
    if prop is None:
        raise ToolError(
            "UNKNOWN_PROPERTY",
            f"'{node.node_type}' has no property '{key}'. "
            f"Available: {short_list(sorted(node.properties))}",
        )
    return ToolResult(
        ok=True,
        summary=f"{node.name}.{key} = {_display(prop.value)}",
        data={
            "node_id": node_id,
            "property": key,
            "value": _display(prop.value),
            "type": prop.input_type.name,
        },
    )


def _set_property(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("change a property")
    node_id, node = resolve_node(ctx, str(ctx.args["node"]))
    key = str(ctx.args["property"])
    prop = node.get_property(key)
    if prop is None:
        raise ToolError(
            "UNKNOWN_PROPERTY",
            f"'{node.node_type}' has no property '{key}'. "
            f"Available: {short_list(sorted(node.properties))}",
        )

    new_value = _coerce_property_value(node, key, ctx.args["value"])
    old_value = prop.value
    if _display(old_value) == _display(new_value):
        return ToolResult(
            ok=True,
            summary=f"{node.name}.{key} is already {_display(new_value)}.",
        )

    if not transaction.apply(
        ctx.project,
        SetPropertyCommand(node_id, key, new_value, old_value=old_value),
        action=f"~ Set {node.name}.{key} → {_display(new_value)}",
        changed_node_ids=[node_id],
    ):
        return ToolResult.failure(
            "COMMAND_REJECTED", f"The editor refused to set {key}."
        )
    return ToolResult(
        ok=True,
        summary=f"Set {node.name}.{key} to {_display(new_value)}",
        details=[f"~ Set {node.name}.{key} → {_display(new_value)}"],
        data={
            "node_id": node_id,
            "property": key,
            "old_value": _display(old_value),
            "value": _display(new_value),
        },
        changed_node_ids=[node_id],
    )


def _list_ports_factory(inputs: bool) -> Any:
    def handler(ctx: ToolContext) -> ToolResult:
        node_id, node = resolve_node(ctx, str(ctx.args["node"]))
        ports = node.inputs if inputs else node.outputs
        rows = [
            {
                "name": port.name,
                "type": port.socket_type.name,
                "type_label": port.type_label,
                "description": port.description,
                "default": port.default,
                "units": port.units,
                "coordinate_space": port.coordinate_space,
            }
            for port in ports.values()
        ]
        direction = "input" if inputs else "output"
        return ToolResult(
            ok=True,
            summary=f"{node.name} has {len(rows)} {direction} port(s).",
            data={"node_id": node_id, "direction": direction, "ports": rows},
        )

    return handler


# ======================================================================
# Property value coercion
# ======================================================================


def _coerce_property_value(node: Any, key: str, raw: Any) -> Any:
    """Convert a model-supplied value into the property's real Python type."""
    prop = node.get_property(key)
    if prop is None:
        raise ToolError("UNKNOWN_PROPERTY", f"{node.node_type} has no property {key}.")

    current = prop.value
    input_type = prop.input_type

    if isinstance(current, Enum):
        return _coerce_enum_value(node.node_type, key, current, raw)

    if input_type == NodePropertyInputType.Checkbox:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        if isinstance(raw, (int, float)) and raw in (0, 1):
            return bool(raw)
        raise ToolError(
            "INVALID_PROPERTY_VALUE",
            f"{key} expects true or false (received {raw!r}).",
        )

    if input_type in (NodePropertyInputType.Number, NodePropertyInputType.Slider):
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise ToolError(
                "INVALID_PROPERTY_VALUE", f"{key} expects a number (received {raw!r})."
            )
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ToolError(
                "INVALID_PROPERTY_VALUE",
                f"{key} expects a number (received {raw!r}).",
            ) from exc
        low, high = prop.slider_min_value, prop.slider_max_value
        if high > low and not (low <= number <= high):
            raise ToolError(
                "PROPERTY_OUT_OF_RANGE",
                f"{key} must be between {low} and {high} (received {number:g}).",
            )
        if isinstance(current, int) and not isinstance(current, bool):
            return int(round(number))
        return number

    if input_type == NodePropertyInputType.Color:
        if (
            isinstance(raw, (list, tuple))
            and len(raw) == 3
            and all(isinstance(channel, (int, float)) for channel in raw)
        ):
            return tuple(int(max(0, min(255, channel))) for channel in raw)
        raise ToolError(
            "INVALID_PROPERTY_VALUE",
            f"{key} expects three channel values [r, g, b] (received {raw!r}).",
        )

    if isinstance(current, str):
        if isinstance(raw, str):
            return raw
        return str(raw)

    if isinstance(current, bool):
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() == "true"
        return bool(raw)

    # Anything else (custom widgets, lists, dicts) is passed through and the
    # property setter decides. This keeps obscure plugin properties usable
    # without inventing validation we cannot ground in the registry.
    return raw


def _coerce_enum_value(node_type: str, key: str, current: Enum, raw: Any) -> Enum:
    """Map a name, label, or numeric value onto an enum member."""
    enum_type = type(current)
    options = [member.name for member in enum_type]

    if isinstance(raw, str):
        text = raw.strip()
        for member in enum_type:
            if member.name.lower() == text.lower():
                return member
        for member in enum_type:
            label = getattr(member, "value", None)
            if isinstance(label, str) and label.lower() == text.lower():
                return member
        raise ToolError(
            "INVALID_PROPERTY_VALUE",
            f"{node_type}.{key} options are: {', '.join(options)} (received {raw!r}).",
        )

    if isinstance(raw, bool):
        raise ToolError(
            "INVALID_PROPERTY_VALUE",
            f"{node_type}.{key} expects one of: {', '.join(options)}.",
        )

    if isinstance(raw, (int, float)):
        for member in enum_type:
            if getattr(member, "value", None) == raw:
                return member
        try:
            return enum_type(int(raw))
        except (ValueError, TypeError) as exc:
            raise ToolError(
                "INVALID_PROPERTY_VALUE",
                f"{node_type}.{key} options are: {', '.join(options)} (received {raw!r}).",
            ) from exc

    raise ToolError(
        "INVALID_PROPERTY_VALUE",
        f"{node_type}.{key} expects one of: {', '.join(options)} (received {raw!r}).",
    )


def _display(value: Any) -> Any:
    """Render a value as JSON-safe, user-facing data."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _node_name(project: Any, node_id: str) -> str:
    node = project.nodes.get(node_id)
    return node.name if node is not None else node_id
