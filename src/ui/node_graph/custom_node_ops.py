"""Custom node graph operations: collapse a selection, expand an instance.

These helpers follow the graph view invariant that every project mutation
goes through ``HistoryStack.push(...)`` so the whole collapse/expand is a
single undo step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from core.custom_node_store import global_custom_node_store
from core.events import Connection
from core.history import (AddNodeCommand, CompositeCommand, ConnectCommand,
                          RemoveNodesCommand)
from core.nodes import Node, global_node_registry
from core.nodes.base import NodeSocketType
from core.nodes.custom_nodes import (CUSTOM_NODE_CATEGORY,
                                     DEFAULT_CUSTOM_COLOR, PORT_SLOT,
                                     TERMINAL_NODE_TYPES, CustomNode,
                                     CustomNodeDefinition, CustomPort,
                                     SubgraphInputNode, SubgraphOutputNode,
                                     build_node_from_blob, is_terminal_node,
                                     sanitize_port_name, unique_port_name)

if TYPE_CHECKING:
    from ui.node_graph.view import NodeGraphView


@dataclass
class CustomNodeWiring:
    """External connections the collapsed chip must reproduce.

    ``inputs`` entries are ``(port_name, upstream_node_id, upstream_slot)``.
    ``outputs`` entries are ``(port_name, destination_node_id, destination_slot)``.
    """

    inputs: list[tuple[str, str, str]] = field(default_factory=list)
    outputs: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class CustomNodeBuild:
    definition: CustomNodeDefinition
    wiring: CustomNodeWiring


# ============================================================================
# Definition building
# ============================================================================


def build_custom_node_definition(
    project: object,
    node_ids: list[str],
    *,
    name: str,
    description: str = "",
    color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR,
) -> CustomNodeBuild | None:
    """Derive a custom node definition + external wiring from a selection.

    Parameters:
        project: Live ``Project``.
        node_ids: Ids of the nodes being collapsed.
        name: Definition (and hence node type) name.
        description: Tooltip text.
        color: Header RGB.

    Returns:
        A :class:`CustomNodeBuild`, or ``None`` when the selection has no
        collapsible nodes.
    """
    nodes = project.nodes  # type: ignore[attr-defined]
    connections = project.connections  # type: ignore[attr-defined]

    ordered_ids: list[str] = []
    for node_id in node_ids:
        if node_id in nodes and node_id not in ordered_ids:
            ordered_ids.append(node_id)
    # Terminals belong to definitions, never to a collapsed selection, and a
    # Viewer is a screen endpoint rather than a processing step.
    internal = {
        node_id
        for node_id in ordered_ids
        if is_collapsible(nodes[node_id])
    }
    internal_ids = [node_id for node_id in ordered_ids if node_id in internal]
    if not internal_ids:
        return None

    # --- group boundary crossings ----------------------------------------
    input_groups: dict[tuple[str, str], Connection] = {}
    output_groups: dict[tuple[str, str], list[Connection]] = {}
    for conn in connections:
        out_inside = conn.output_node_id in internal
        in_inside = conn.input_node_id in internal
        if in_inside and not out_inside:
            input_groups.setdefault(
                (conn.input_node_id, conn.input_slot),
                conn,
            )
        elif out_inside and not in_inside:
            output_groups.setdefault(
                (conn.output_node_id, conn.output_slot),
                [],
            ).append(conn)

    # --- terminal placement ----------------------------------------------
    xs = [float(nodes[node_id].x) for node_id in internal_ids]
    ys = [float(nodes[node_id].y) for node_id in internal_ids]
    widths = [float(nodes[node_id].width) for node_id in internal_ids]
    left_x = min(xs) - 320.0 if xs else 0.0
    right_x = (max(
        xs[index] + widths[index] for index in range(len(internal_ids))
    ) + 140.0) if xs else 0.0
    top_y = min(ys) if ys else 0.0

    node_blobs: dict[str, dict] = {
        node_id: nodes[node_id].to_dict() for node_id in internal_ids
    }
    used_ids = set(node_blobs)
    used_in_names: set[str] = set()
    used_out_names: set[str] = set()

    input_ports: list[CustomPort] = []
    output_ports: list[CustomPort] = []
    wiring = CustomNodeWiring()
    new_connections: list[dict[str, str]] = []

    def _make_terminal_id(prefix: str) -> str:
        index = 1
        while f"{prefix}_{index}" in used_ids:
            index += 1
        terminal_id = f"{prefix}_{index}"
        used_ids.add(terminal_id)
        return terminal_id

    # --- input ports ------------------------------------------------------
    for index, ((inner_node_id, inner_slot), conn) in enumerate(
        input_groups.items()
    ):
        consumer = nodes[inner_node_id]
        socket = consumer.inputs.get(inner_slot)
        socket_type = (
            socket.socket_type if socket is not None else NodeSocketType.Frame
        )
        base = _port_label(consumer.name, inner_slot)
        port_name = unique_port_name(sanitize_port_name(base, "Input"), used_in_names)
        used_in_names.add(port_name)

        terminal_id = _make_terminal_id("custom_in")
        terminal = SubgraphInputNode(port_name, socket_type)
        terminal.x = left_x
        terminal.y = top_y + index * 90.0
        node_blobs[terminal_id] = terminal.to_dict()

        input_ports.append(CustomPort(port_name, socket_type, terminal_id))
        wiring.inputs.append((port_name, conn.output_node_id, conn.output_slot))
        new_connections.append(
            {
                "output_node_id": terminal_id,
                "output_slot": PORT_SLOT,
                "input_node_id": inner_node_id,
                "input_slot": inner_slot,
            }
        )

    # --- output ports -----------------------------------------------------
    for index, ((inner_node_id, output_slot), conns) in enumerate(
        output_groups.items()
    ):
        producer = nodes[inner_node_id]
        socket = producer.outputs.get(output_slot)
        socket_type = (
            socket.socket_type if socket is not None else NodeSocketType.Frame
        )
        base = _port_label(producer.name, output_slot)
        port_name = unique_port_name(sanitize_port_name(base, "Output"), used_out_names)
        used_out_names.add(port_name)

        terminal_id = _make_terminal_id("custom_out")
        terminal = SubgraphOutputNode(port_name, socket_type)
        terminal.x = right_x
        terminal.y = top_y + index * 90.0
        node_blobs[terminal_id] = terminal.to_dict()

        output_ports.append(CustomPort(port_name, socket_type, terminal_id))
        for conn in conns:
            wiring.outputs.append((port_name, conn.input_node_id, conn.input_slot))
        new_connections.append(
            {
                "output_node_id": inner_node_id,
                "output_slot": output_slot,
                "input_node_id": terminal_id,
                "input_slot": PORT_SLOT,
            }
        )

    # --- internal wires ---------------------------------------------------
    for conn in connections:
        if conn.output_node_id in internal and conn.input_node_id in internal:
            new_connections.append(
                {
                    "output_node_id": conn.output_node_id,
                    "output_slot": conn.output_slot,
                    "input_node_id": conn.input_node_id,
                    "input_slot": conn.input_slot,
                }
            )

    definition = CustomNodeDefinition(
        name=name.strip() or "Custom Node",
        description=description,
        color=color,
        inputs=input_ports,
        outputs=output_ports,
        nodes=node_blobs,
        connections=new_connections,
    )
    return CustomNodeBuild(definition=definition, wiring=wiring)


def is_collapsible(node: Node) -> bool:
    """Return whether ``node`` may be folded into a custom node."""
    return not is_terminal_node(node) and node.node_type != "Viewer"


def _port_label(node_name: str, slot: str) -> str:
    """Return a friendly port base name for an inner socket."""
    if slot in ("frame", "value", ""):
        return node_name
    return f"{node_name} {slot}"


# ============================================================================
# Collapse
# ============================================================================


def collapse_to_custom_node(
    view: NodeGraphView,
    node_ids: list[str],
    *,
    name: str,
    description: str = "",
    color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR,
) -> str | None:
    """Replace the selected nodes with a reusable custom node.

    The definition is saved to the global custom node library so it appears
    in the ``Custom`` category for every project.

    Returns:
        The new custom node's id, or ``None`` on failure.
    """
    project = view.project
    build = build_custom_node_definition(
        project,
        node_ids,
        name=name,
        description=description,
        color=color,
    )
    if build is None:
        return None

    definition = build.definition
    global_custom_node_store.upsert(definition)

    node = global_node_registry.create_node(
        definition.name,
        category=CUSTOM_NODE_CATEGORY,
    )
    if node is None:
        return None

    _place_at_selection(view, node, node_ids)

    custom_id = _unique_node_id(project, "custom")
    commands: list[object] = [
        AddNodeCommand(node, node_id=custom_id),
        RemoveNodesCommand(list(
            node_id
            for node_id in node_ids
            if node_id in project.nodes and is_collapsible(project.nodes[node_id])
        )),
    ]
    for port_name, upstream_id, upstream_slot in build.wiring.inputs:
        commands.append(
            ConnectCommand(upstream_id, upstream_slot, custom_id, port_name)
        )
    for port_name, dest_id, dest_slot in build.wiring.outputs:
        commands.append(
            ConnectCommand(custom_id, port_name, dest_id, dest_slot)
        )

    if not view.history.push(
        CompositeCommand(commands, f"Create Custom Node '{definition.name}'")  # type: ignore[arg-type]
    ):
        return None

    view.scene.clearSelection()
    item = view.node_items.get(custom_id)
    if item is not None:
        item.setSelected(True)
    return custom_id


def _place_at_selection(
    view: NodeGraphView,
    node: Node,
    node_ids: list[str],
) -> None:
    """Position ``node`` at the centre of the collapsed selection."""
    project = view.project
    ids = [node_id for node_id in node_ids if node_id in project.nodes]
    if not ids:
        center = view.view_center_scene_pos()
        node.x, node.y = center.x(), center.y()
        return
    xs = [float(project.nodes[node_id].x) for node_id in ids]
    ys = [float(project.nodes[node_id].y) for node_id in ids]
    node.x = sum(xs) / len(xs)
    node.y = sum(ys) / len(ys)


# ============================================================================
# Expand
# ============================================================================


def expand_custom_node(view: NodeGraphView, node_id: str) -> bool:
    """Dissolve a custom node instance into its underlying nodes.

    The definition itself is left untouched, so saved custom nodes keep
    working. Use this to tweak a one-off instance in place.
    """
    project = view.project
    node = project.nodes.get(node_id)
    if not isinstance(node, CustomNode):
        return False

    definition = node.definition
    id_map: dict[str, str] = {}
    add_commands: list[AddNodeCommand] = []

    inner_positions = [
        (inner_id, blob)
        for inner_id, blob in definition.nodes.items()
        if str(blob.get("node_type", "")) not in TERMINAL_NODE_TYPES
    ]
    if not inner_positions:
        return False

    base_x = min(float(blob.get("x", 0.0)) for _, blob in inner_positions)
    base_y = min(float(blob.get("y", 0.0)) for _, blob in inner_positions)
    offset_x = float(node.x) - base_x
    offset_y = float(node.y) - base_y

    for inner_id, blob in inner_positions:
        inner_node = build_node_from_blob(blob)
        if inner_node is None:
            continue
        inner_node.x = float(blob.get("x", 0.0)) + offset_x
        inner_node.y = float(blob.get("y", 0.0)) + offset_y
        new_id = _unique_node_id(project, "node")
        id_map[inner_id] = new_id
        add_commands.append(AddNodeCommand(inner_node, node_id=new_id))

    if not add_commands:
        return False

    input_port_by_terminal = {
        port.terminal_id: port for port in definition.inputs
    }
    output_port_by_terminal = {
        port.terminal_id: port for port in definition.outputs
    }
    external_inputs = {
        conn.input_slot: conn
        for conn in project.connections
        if conn.input_node_id == node_id
    }
    external_outputs: dict[str, list[Connection]] = {}
    for conn in project.connections:
        if conn.output_node_id == node_id:
            external_outputs.setdefault(conn.output_slot, []).append(conn)

    connect_commands: list[ConnectCommand] = []
    for blob in definition.connections:
        out_id = str(blob.get("output_node_id", ""))
        in_id = str(blob.get("input_node_id", ""))
        out_slot = str(blob.get("output_slot", PORT_SLOT))
        in_slot = str(blob.get("input_slot", PORT_SLOT))

        out_terminal = input_port_by_terminal.get(out_id)
        in_terminal = output_port_by_terminal.get(in_id)

        if out_terminal is not None:
            # input port terminal -> inner consumer
            upstream = external_inputs.get(out_terminal.name)
            target = id_map.get(in_id)
            if upstream is None or target is None:
                continue
            connect_commands.append(
                ConnectCommand(
                    upstream.output_node_id,
                    upstream.output_slot,
                    target,
                    in_slot,
                )
            )
        elif in_terminal is not None:
            # inner producer -> output port terminal
            source = id_map.get(out_id)
            if source is None:
                continue
            for dest in external_outputs.get(in_terminal.name, []):
                connect_commands.append(
                    ConnectCommand(
                        source,
                        out_slot,
                        dest.input_node_id,
                        dest.input_slot,
                    )
                )
        else:
            source = id_map.get(out_id)
            target = id_map.get(in_id)
            if source is None or target is None:
                continue
            connect_commands.append(
                ConnectCommand(source, out_slot, target, in_slot)
            )

    commands: list[object] = [
        *add_commands,
        RemoveNodesCommand([node_id]),
        *connect_commands,
    ]
    if not view.history.push(
        CompositeCommand(commands, f"Expand Custom Node '{node.name}'")  # type: ignore[arg-type]
    ):
        return False

    view.scene.clearSelection()
    for new_id in id_map.values():
        item = view.node_items.get(new_id)
        if item is not None:
            item.setSelected(True)
    return True


# ============================================================================
# Helpers
# ============================================================================


def _unique_node_id(project: object, prefix: str) -> str:
    nodes = project.nodes  # type: ignore[attr-defined]
    while True:
        candidate = f"{prefix}_{uuid4().hex[:12]}"
        if candidate not in nodes:
            return candidate


def definition_name_available(name: str) -> bool:
    """Return whether a definition name is free in the global library."""
    return not global_custom_node_store.has(name.strip())


def apply_definition_to_project(
    view: NodeGraphView,
    definition: CustomNodeDefinition,
    *,
    previous_name: str | None = None,
) -> int:
    """Push an edited definition onto matching instances in the live project.

    Instance ``node_type`` is updated too, so saved projects resolve the new
    registered type directly. Connections that referenced removed ports are
    dropped.

    Returns:
        Number of instances updated.
    """
    project = view.project
    names = {definition.name}
    if previous_name:
        names.add(previous_name)

    updated = 0
    for node_id, node in list(project.nodes.items()):
        if not isinstance(node, CustomNode):
            continue
        if node.definition_name not in names:
            continue

        node.set_definition(definition)
        node.node_type = definition.name

        # Drop wires that point at ports the new definition no longer has.
        for conn in list(project.connections):
            if conn.output_node_id == node_id and conn.output_slot not in node.outputs:
                project.disconnect_nodes(conn)
            elif conn.input_node_id == node_id and conn.input_slot not in node.inputs:
                project.disconnect_nodes(conn)

        project.invalidate_cache(node_id)
        item = view.node_items.get(node_id)
        if item is not None:
            item.relayout_from_content()
            view.refresh_connections_for_node(node_id)
            item.update()
        updated += 1
    return updated


__all__ = [
    "CustomNodeBuild",
    "CustomNodeWiring",
    "apply_definition_to_project",
    "build_custom_node_definition",
    "collapse_to_custom_node",
    "definition_name_available",
    "expand_custom_node",
    "is_collapsible",
]
