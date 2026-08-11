"""Concrete undoable commands for graph and property edits."""

from __future__ import annotations

from typing import Any

from config.constants import NODE_CHAIN_GAP_PX
from core.events import Connection
from core.history.command import Command
from core.history.snapshots import NodeSnapshot, connections_touching
from core.nodes import Node
from core.project import Project


class CompositeCommand(Command):
    """Run multiple commands as one undo step."""

    def __init__(self, commands: list[Command], label: str) -> None:
        self._commands = commands
        self._label = label

    def execute(self, project: Project) -> bool:
        applied: list[Command] = []
        for command in self._commands:
            if not command.execute(project):
                for done in reversed(applied):
                    done.undo(project)
                return False
            applied.append(command)
        return True

    def undo(self, project: Project) -> None:
        for command in reversed(self._commands):
            command.undo(project)

    def description(self) -> str:
        return self._label


class AddNodeCommand(Command):
    """Add a node (keeps a stable id after the first execute)."""

    def __init__(self, node: Node, *, node_id: str | None = None) -> None:
        self._node = node
        self._node_id = node_id
        self._snapshot: NodeSnapshot | None = None

    @property
    def node_id(self) -> str | None:
        return self._node_id

    def execute(self, project: Project) -> bool:
        if self._snapshot is not None:
            restored = self._snapshot.create_node()
            if restored is None:
                return False
            project.add_node(restored, node_id=self._snapshot.node_id)
            self._node_id = self._snapshot.node_id
            return True

        node_id = project.add_node(self._node, node_id=self._node_id)
        self._node_id = node_id
        self._snapshot = NodeSnapshot.from_node(node_id, project.nodes[node_id])
        return True

    def undo(self, project: Project) -> None:
        if self._node_id is not None:
            project.remove_node(self._node_id)

    def description(self) -> str:
        name = self._node.node_type if self._snapshot is None else self._snapshot.node_type
        return f"Add {name}"


class RemoveNodesCommand(Command):
    """Remove one or more nodes and restore them (with wires) on undo."""

    def __init__(self, node_ids: list[str]) -> None:
        self._node_ids = list(dict.fromkeys(node_ids))
        self._snapshots: list[NodeSnapshot] = []
        self._connections: list[Connection] = []

    def execute(self, project: Project) -> bool:
        if not self._node_ids:
            return False
        if not self._snapshots:
            id_set = set(self._node_ids)
            self._connections = connections_touching(project.connections, id_set)
            for node_id in self._node_ids:
                node = project.nodes.get(node_id)
                if node is None:
                    continue
                self._snapshots.append(NodeSnapshot.from_node(node_id, node))
        if not self._snapshots:
            return False
        for node_id in list(self._node_ids):
            project.remove_node(node_id)
        return True

    def undo(self, project: Project) -> None:
        for snap in self._snapshots:
            node = snap.create_node()
            if node is None:
                continue
            project.add_node(node, node_id=snap.node_id)
        for conn in self._connections:
            project.connect_nodes(
                conn.output_node_id,
                conn.output_slot,
                conn.input_node_id,
                conn.input_slot,
            )

    def description(self) -> str:
        count = len(self._node_ids)
        if count == 1:
            return "Delete Node"
        return f"Delete {count} Nodes"


class ConnectCommand(Command):
    """Create a connection, restoring any replaced input link on undo."""

    def __init__(
        self,
        output_node_id: str,
        output_slot: str,
        input_node_id: str,
        input_slot: str,
    ) -> None:
        self._output_node_id = output_node_id
        self._output_slot = output_slot
        self._input_node_id = input_node_id
        self._input_slot = input_slot
        self._connection = Connection(
            output_node_id,
            output_slot,
            input_node_id,
            input_slot,
        )
        self._replaced: Connection | None = None

    def execute(self, project: Project) -> bool:
        self._replaced = None
        for existing in project.connections:
            if (
                existing.input_node_id == self._input_node_id
                and existing.input_slot == self._input_slot
            ):
                self._replaced = existing
                break
        return project.connect_nodes(
            self._output_node_id,
            self._output_slot,
            self._input_node_id,
            self._input_slot,
        )

    def undo(self, project: Project) -> None:
        project.disconnect_nodes(self._connection)
        if self._replaced is not None:
            project.connect_nodes(
                self._replaced.output_node_id,
                self._replaced.output_slot,
                self._replaced.input_node_id,
                self._replaced.input_slot,
            )

    def description(self) -> str:
        return "Connect Nodes"


class DisconnectCommand(Command):
    """Remove a connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def execute(self, project: Project) -> bool:
        return project.disconnect_nodes(self._connection)

    def undo(self, project: Project) -> None:
        project.connect_nodes(
            self._connection.output_node_id,
            self._connection.output_slot,
            self._connection.input_node_id,
            self._connection.input_slot,
        )

    def description(self) -> str:
        return "Disconnect"


class SetPropertyCommand(Command):
    """Change a single node property (coalesces rapid successive edits)."""

    def __init__(
        self,
        node_id: str,
        prop_name: str,
        new_value: Any,
        *,
        old_value: Any | None = None,
    ) -> None:
        self._node_id = node_id
        self._prop_name = prop_name
        self._new_value = new_value
        self._old_value = old_value

    def execute(self, project: Project) -> bool:
        node = project.nodes.get(self._node_id)
        if node is None:
            return False
        prop = node.get_property(self._prop_name)
        if prop is None:
            return False
        if self._old_value is None:
            self._old_value = prop.value
        return project.set_node_property(
            self._node_id,
            self._prop_name,
            self._new_value,
        )

    def undo(self, project: Project) -> None:
        project.set_node_property(
            self._node_id,
            self._prop_name,
            self._old_value,
        )

    def description(self) -> str:
        nice = self._prop_name.replace("_", " ").title()
        return f"Change {nice}"

    def merge_with(self, previous: Command) -> bool:
        if not isinstance(previous, SetPropertyCommand):
            return False
        if (
            previous._node_id != self._node_id
            or previous._prop_name != self._prop_name
        ):
            return False
        # Keep the earliest old_value; advance to the latest new_value.
        self._old_value = previous._old_value
        previous._new_value = self._new_value
        return True


class MoveNodesCommand(Command):
    """Move one or more nodes between position maps."""

    def __init__(
        self,
        before: dict[str, tuple[float, float]],
        after: dict[str, tuple[float, float]],
    ) -> None:
        self._before = dict(before)
        self._after = dict(after)

    def execute(self, project: Project) -> bool:
        if not self._after or self._before == self._after:
            return False
        project.set_node_positions(self._after)
        return True

    def undo(self, project: Project) -> None:
        project.set_node_positions(self._before)

    def description(self) -> str:
        count = len(self._after)
        if count == 1:
            return "Move Node"
        return f"Move {count} Nodes"

    def merge_with(self, previous: Command) -> bool:
        if not isinstance(previous, MoveNodesCommand):
            return False
        if set(previous._after.keys()) != set(self._after.keys()):
            return False
        # Chain moves: keep original before, use latest after.
        self._before = previous._before
        previous._after = self._after
        return True


class PasteNodesCommand(Command):
    """Paste node snapshots (and internal wires) at an origin point."""

    def __init__(
        self,
        snapshots: list[NodeSnapshot],
        connections: list[Connection],
        origin: tuple[float, float],
    ) -> None:
        self._template_snapshots = list(snapshots)
        self._template_connections = list(connections)
        self._origin_x = float(origin[0])
        self._origin_y = float(origin[1])
        self._created: list[NodeSnapshot] = []
        self._created_connections: list[Connection] = []

    @property
    def created_ids(self) -> list[str]:
        return [snap.node_id for snap in self._created]

    def execute(self, project: Project) -> bool:
        if self._created:
            for snap in self._created:
                node = snap.create_node()
                if node is None:
                    return False
                project.add_node(node, node_id=snap.node_id)
            for conn in self._created_connections:
                project.connect_nodes(
                    conn.output_node_id,
                    conn.output_slot,
                    conn.input_node_id,
                    conn.input_slot,
                )
            return True

        if not self._template_snapshots:
            return False

        id_map: dict[str, str] = {}
        created: list[NodeSnapshot] = []
        for snap in self._template_snapshots:
            node = snap.create_node()
            if node is None:
                continue
            node.x = snap.x + self._origin_x
            node.y = snap.y + self._origin_y
            new_id = project.add_node(node)
            id_map[snap.node_id] = new_id
            created.append(NodeSnapshot.from_node(new_id, project.nodes[new_id]))

        if not created:
            return False

        created_connections: list[Connection] = []
        for conn in self._template_connections:
            out_id = id_map.get(conn.output_node_id)
            in_id = id_map.get(conn.input_node_id)
            if out_id is None or in_id is None:
                continue
            if project.connect_nodes(
                out_id,
                conn.output_slot,
                in_id,
                conn.input_slot,
            ):
                created_connections.append(
                    Connection(out_id, conn.output_slot, in_id, conn.input_slot)
                )

        self._created = created
        self._created_connections = created_connections
        return True

    def undo(self, project: Project) -> None:
        for snap in self._created:
            project.remove_node(snap.node_id)

    def description(self) -> str:
        count = len(self._created) or len(self._template_snapshots)
        if count == 1:
            return "Paste Node"
        return f"Paste {count} Nodes"


class InsertAfterCommand(Command):
    """Insert a node after ``source_id``, splicing into its outgoing chain."""

    def __init__(self, source_id: str, node: Node) -> None:
        self._source_id = source_id
        self._node = node
        self._new_id: str | None = None
        self._snapshot: NodeSnapshot | None = None
        self._source_out: str = ""
        self._new_in: str = ""
        self._new_out: str = ""
        self._downstream: list[Connection] = []

    @property
    def node_id(self) -> str | None:
        return self._new_id

    def execute(self, project: Project) -> bool:
        source = project.nodes.get(self._source_id)
        if source is None:
            return False

        if self._snapshot is None:
            pairing = resolve_insert_sockets(source, self._node)
            if pairing is None:
                return False
            self._source_out, self._new_in, self._new_out = pairing
            self._downstream = [
                conn
                for conn in project.connections
                if (
                    conn.output_node_id == self._source_id
                    and conn.output_slot == self._source_out
                )
            ]
            self._node.x = float(source.x) + NODE_CHAIN_GAP_PX
            self._node.y = float(source.y)
            new_id = project.add_node(self._node)
            self._new_id = new_id
            self._snapshot = NodeSnapshot.from_node(new_id, project.nodes[new_id])
        else:
            restored = self._snapshot.create_node()
            if restored is None:
                return False
            project.add_node(restored, node_id=self._snapshot.node_id)
            self._new_id = self._snapshot.node_id

        if self._new_id is None:
            return False

        # Passthrough: splice into the chain. Sink: branch without breaking wires.
        if self._new_out:
            for conn in self._downstream:
                project.disconnect_nodes(conn)

        if not project.connect_nodes(
            self._source_id,
            self._source_out,
            self._new_id,
            self._new_in,
        ):
            return False

        if self._new_out:
            for conn in self._downstream:
                project.connect_nodes(
                    self._new_id,
                    self._new_out,
                    conn.input_node_id,
                    conn.input_slot,
                )
        return True

    def undo(self, project: Project) -> None:
        if self._new_id is None:
            return
        project.remove_node(self._new_id)
        if self._new_out:
            for conn in self._downstream:
                project.connect_nodes(
                    conn.output_node_id,
                    conn.output_slot,
                    conn.input_node_id,
                    conn.input_slot,
                )

    def description(self) -> str:
        name = (
            self._node.node_type
            if self._snapshot is None
            else self._snapshot.node_type
        )
        return f"Insert {name}"


def resolve_insert_sockets(
    source: Node,
    inserted: Node,
) -> tuple[str, str, str] | None:
    """Pick ``(source_out, inserted_in, inserted_out)`` for a chain insert.

    ``inserted_out`` may be empty when the inserted node is a sink (no output).
    Returns ``None`` when source and inserted share no compatible link.
    """
    if not source.outputs or not inserted.inputs:
        return None

    for out_name, out_sock in source.outputs.items():
        for in_name, in_sock in inserted.inputs.items():
            if out_sock.socket_type != in_sock.socket_type:
                continue
            inserted_out = ""
            for cand_name, cand_sock in inserted.outputs.items():
                if cand_sock.socket_type == out_sock.socket_type:
                    inserted_out = cand_name
                    break
            return out_name, in_name, inserted_out
    return None
