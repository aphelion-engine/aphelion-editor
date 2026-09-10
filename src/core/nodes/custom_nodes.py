"""Reusable custom (subgraph) nodes.

A *custom node* is a single chip on the canvas that wraps a small graph of
other nodes. It behaves like a function:

* It exposes an adjustable set of input and output ports.
* Evaluating it evaluates the embedded graph and returns one value per
  declared output.
* Its subgraph definition can be saved to disk and reused in any project.
* Instances embed their own definition, so a project stays portable even on
  a machine that has never seen the original definition.

The embedded graph is built around two invisible terminal node types:

``Subgraph Input``
    One declared input port. Its ``provided_value`` is filled from the
    parent graph before the subgraph is evaluated.

``Subgraph Output``
    One declared output port. Evaluating it returns whatever is wired into
    its ``value`` input socket.

Both terminal types use a single socket named ``value``. The port name and
socket type live on the terminal node itself (``node.name`` and
``socket_type``), which keeps port renaming instant and purely cosmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from core.nodes.base import Node, NodeSocketType
from core.nodes.registry import global_node_registry

#: Category shown in the Add Node menu for saved custom node definitions.
CUSTOM_NODE_CATEGORY: str = "Custom"

#: Single socket name used by both terminal node types.
PORT_SLOT: str = "value"

#: Node types reserved for subgraph terminals (never registered in the menu).
SUBGRAPH_INPUT_TYPE: str = "Subgraph Input"
SUBGRAPH_OUTPUT_TYPE: str = "Subgraph Output"

#: Node type key for a custom node uses the definition name, so definitions
#: are uniquely identified by name.
DEFAULT_CUSTOM_COLOR: tuple[int, int, int] = (150, 116, 196)

#: Socket types offered for custom node ports. ``Node``/``Any`` are
#: node-reference sockets and are intentionally excluded.
PORT_SOCKET_TYPES: tuple[NodeSocketType, ...] = (
    NodeSocketType.Frame,
    NodeSocketType.Mask,
    NodeSocketType.Number,
    NodeSocketType.Color,
    NodeSocketType.Audio,
)


# ============================================================================
# Definition model
# ============================================================================


@dataclass
class CustomPort:
    """One exposed input or output port of a custom node."""

    name: str
    socket_type: NodeSocketType
    terminal_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "socket_type": self.socket_type.name,
            "terminal_id": self.terminal_id,
        }

    @classmethod
    def from_dict(cls, data: Any) -> CustomPort | None:
        if not isinstance(data, dict):
            return None
        name = str(data.get("name", "")).strip()
        terminal_id = str(data.get("terminal_id", "")).strip()
        if not name or not terminal_id:
            return None
        return cls(
            name=name,
            socket_type=_socket_type_from_name(
                str(data.get("socket_type", ""))
            ),
            terminal_id=terminal_id,
        )


@dataclass
class CustomNodeDefinition:
    """Serializable description of a reusable custom node."""

    name: str
    description: str = ""
    color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR
    inputs: list[CustomPort] = field(default_factory=list)
    outputs: list[CustomPort] = field(default_factory=list)
    #: node id -> serialized node document (same shape as ``Project`` nodes).
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: serialized connection documents.
    connections: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "color": [int(self.color[0]), int(self.color[1]), int(self.color[2])],
            "inputs": [port.to_dict() for port in self.inputs],
            "outputs": [port.to_dict() for port in self.outputs],
            "nodes": {
                str(node_id): dict(blob)
                for node_id, blob in self.nodes.items()
                if isinstance(blob, dict)
            },
            "connections": [
                dict(blob)
                for blob in self.connections
                if isinstance(blob, dict)
            ],
        }

    @classmethod
    def from_dict(cls, data: Any) -> CustomNodeDefinition:
        if not isinstance(data, dict):
            return cls(name="Custom Node")
        raw_color = data.get("color")
        color = DEFAULT_CUSTOM_COLOR
        if isinstance(raw_color, (list, tuple)) and len(raw_color) >= 3:
            try:
                color = (
                    int(raw_color[0]),
                    int(raw_color[1]),
                    int(raw_color[2]),
                )
            except (TypeError, ValueError):
                color = DEFAULT_CUSTOM_COLOR
        raw_nodes = data.get("nodes")
        nodes: dict[str, dict[str, Any]] = {}
        if isinstance(raw_nodes, dict):
            for node_id, blob in raw_nodes.items():
                if isinstance(blob, dict):
                    nodes[str(node_id)] = dict(blob)
        raw_conns = data.get("connections")
        connections: list[dict[str, Any]] = []
        if isinstance(raw_conns, list):
            for blob in raw_conns:
                if isinstance(blob, dict):
                    connections.append(dict(blob))

        inputs: list[CustomPort] = []
        outputs: list[CustomPort] = []
        for raw_port in data.get("inputs", []) or []:
            port = CustomPort.from_dict(raw_port)
            if port is not None:
                inputs.append(port)
        for raw_port in data.get("outputs", []) or []:
            port = CustomPort.from_dict(raw_port)
            if port is not None:
                outputs.append(port)

        return cls(
            name=str(data.get("name", "")).strip() or "Custom Node",
            description=str(data.get("description", "")),
            color=color,
            inputs=inputs,
            outputs=outputs,
            nodes=nodes,
            connections=connections,
        )

    def copy(self) -> CustomNodeDefinition:
        """Return a deep-ish copy safe to mutate independently."""
        return CustomNodeDefinition.from_dict(self.to_dict())

    def is_empty(self) -> bool:
        return not self.nodes


# ============================================================================
# Terminal nodes
# ============================================================================


class _TerminalNode(Node):
    """Shared behavior for the two subgraph boundary node types."""

    node_category: str = CUSTOM_NODE_CATEGORY
    node_color: tuple[int, int, int] = (96, 150, 132)

    def __init__(
        self,
        name: str | None = None,
        socket_type: NodeSocketType = NodeSocketType.Frame,
    ) -> None:
        self.socket_type: NodeSocketType = _coerce_socket_type(socket_type)
        super().__init__(name)

    def set_socket_type(self, socket_type: NodeSocketType) -> None:
        """Change the port's socket type and rebuild its socket."""
        self.socket_type = _coerce_socket_type(socket_type)
        self.rebuild_sockets()

    def rebuild_sockets(self) -> None:
        """Re-create sockets; subclasses implement the actual layout."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        # Base ``Node.to_dict`` does not persist sockets, so the port type is
        # stored explicitly for definition round-trips.
        data["socket_type"] = self.socket_type.name
        return data


class SubgraphInputNode(_TerminalNode):
    """Declared input port of a custom node (source inside the subgraph)."""

    node_type: str = SUBGRAPH_INPUT_TYPE
    node_description: str = "Exposed input port of a custom node"
    node_color: tuple[int, int, int] = (96, 150, 132)

    def __init__(
        self,
        name: str | None = None,
        socket_type: NodeSocketType = NodeSocketType.Frame,
    ) -> None:
        self.provided_value: Any = None
        super().__init__(name, socket_type)

    def rebuild_sockets(self) -> None:
        self.outputs.clear()
        self.add_output(PORT_SLOT, self.socket_type)

    def _setup_sockets(self) -> None:
        self.add_output(PORT_SLOT, self.socket_type)

    def evaluate(self, frame_num: int) -> Any:
        del frame_num
        return self.provided_value


class SubgraphOutputNode(_TerminalNode):
    """Declared output port of a custom node (sink inside the subgraph)."""

    node_type: str = SUBGRAPH_OUTPUT_TYPE
    node_description: str = "Exposed output port of a custom node"
    node_color: tuple[int, int, int] = (150, 116, 196)

    def rebuild_sockets(self) -> None:
        self.inputs.clear()
        self.add_input(PORT_SLOT, self.socket_type)

    def _setup_sockets(self) -> None:
        self.add_input(PORT_SLOT, self.socket_type)

    def evaluate(self, frame_num: int) -> Any:
        del frame_num
        return self.get_input_value(PORT_SLOT)


TERMINAL_NODE_TYPES: frozenset[str] = frozenset(
    {SUBGRAPH_INPUT_TYPE, SUBGRAPH_OUTPUT_TYPE}
)


def is_terminal_node(node: Node) -> bool:
    return node.node_type in TERMINAL_NODE_TYPES


# ============================================================================
# Custom node
# ============================================================================


class CustomNode(Node):
    """A chip that evaluates an embedded subgraph.

    Concrete usable types are produced by :func:`make_custom_node_class`,
    which binds a :class:`CustomNodeDefinition` template.
    """

    node_category: str = CUSTOM_NODE_CATEGORY
    node_color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR
    node_description: str = "Reusable custom node built from a group of nodes"

    #: Definition bound by :func:`make_custom_node_class`. Instances copy it.
    definition_template: ClassVar[CustomNodeDefinition | None] = None

    def __init__(self, name: str | None = None) -> None:
        template = type(self).definition_template
        if template is not None:
            self.definition: CustomNodeDefinition = template.copy()
        else:
            self.definition = CustomNodeDefinition(name=type(self).node_type)
        self._subgraph: Any = None
        super().__init__(name)

    # -- sockets -----------------------------------------------------------

    def _setup_sockets(self) -> None:
        for port in self.definition.inputs:
            self.add_input(port.name, port.socket_type)
        for port in self.definition.outputs:
            self.add_output(port.name, port.socket_type)

    def rebuild_sockets(self) -> None:
        """Re-create ports from the current definition."""
        self.inputs.clear()
        self.outputs.clear()
        self._setup_sockets()

    def set_definition(self, definition: CustomNodeDefinition) -> None:
        """Replace the embedded definition and drop the cached subgraph."""
        self.definition = definition.copy()
        self.rebuild_sockets()
        self._subgraph = None

    @property
    def definition_name(self) -> str:
        return self.definition.name

    # -- evaluation --------------------------------------------------------

    def evaluate(self, frame_num: int) -> dict[str, Any]:
        subgraph = self._ensure_subgraph()
        if subgraph is None:
            return {}

        self._sync_subgraph_context(subgraph)

        # Feed parent values into the subgraph input terminals. Invalidating
        # each terminal clears its downstream cache so stale results from a
        # previous evaluation of the same frame are never reused.
        for port in self.definition.inputs:
            terminal = subgraph.nodes.get(port.terminal_id)
            if terminal is None:
                continue
            terminal.provided_value = self.get_input_value(port.name)
            subgraph.invalidate_cache(port.terminal_id)

        outputs: dict[str, Any] = {}
        for port in self.definition.outputs:
            if port.terminal_id not in subgraph.nodes:
                outputs[port.name] = None
                continue
            outputs[port.name] = subgraph.evaluate_node(
                port.terminal_id,
                frame_num,
                PORT_SLOT,
            )
        return outputs

    def _sync_subgraph_context(self, subgraph: Any) -> None:
        """Mirror the parent evaluation context onto the embedded graph."""
        subgraph.width = max(1, int(self._eval_width))
        subgraph.height = max(1, int(self._eval_height))
        subgraph.fps = float(self._project_fps) if self._project_fps > 0 else 1.0
        subgraph._timeline_frame_count = max(1, int(self._project_max_frame) + 1)
        subgraph.set_preview_width_override(max(0, int(self._preview_max_width)))
        subgraph.set_export_mode(False)

    def _ensure_subgraph(self) -> Any:
        """Build (and cache) the embedded ``Project`` for the definition."""
        if self._subgraph is not None:
            return self._subgraph

        from core.project import Project

        project = Project(self.definition.name)
        for node_id, blob in self.definition.nodes.items():
            node = build_node_from_blob(blob)
            if node is None:
                continue
            project.add_node(node, node_id=str(node_id))
        for conn in self.definition.connections:
            project.connect_nodes(
                str(conn.get("output_node_id", "")),
                str(conn.get("output_slot", PORT_SLOT)),
                str(conn.get("input_node_id", "")),
                str(conn.get("input_slot", PORT_SLOT)),
            )
        self._subgraph = project
        return project

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["custom_definition"] = self.definition.to_dict()
        return data

    def apply_document(self, data: dict[str, Any]) -> None:
        super().apply_document(data)
        blob = data.get("custom_definition")
        if isinstance(blob, dict):
            self.definition = CustomNodeDefinition.from_dict(blob)
            self.rebuild_sockets()
            self._subgraph = None

    def snapshot_data(self) -> dict[str, Any]:
        return {"custom_definition": self.definition.to_dict()}

    def restore_snapshot_data(self, data: dict[str, Any]) -> None:
        blob = data.get("custom_definition")
        if isinstance(blob, dict):
            self.definition = CustomNodeDefinition.from_dict(blob)
            self.rebuild_sockets()
            self._subgraph = None


# ============================================================================
# Factories / helpers
# ============================================================================


def make_custom_node_class(
    definition: CustomNodeDefinition,
) -> type[CustomNode]:
    """Create a registry-friendly ``CustomNode`` subclass for ``definition``."""
    name = definition.name

    class _DynamicCustomNode(CustomNode):
        node_type = name
        node_category = CUSTOM_NODE_CATEGORY
        node_description = (
            definition.description
            or f"Reusable custom node: {name}"
        )
        node_color = (
            int(definition.color[0]),
            int(definition.color[1]),
            int(definition.color[2]),
        )
        definition_template = definition

    _DynamicCustomNode.__name__ = f"CustomNode_{_identifier(name)}"
    _DynamicCustomNode.__qualname__ = _DynamicCustomNode.__name__
    return _DynamicCustomNode


def create_custom_node_from_document(
    blob: dict[str, Any],
) -> CustomNode | None:
    """Build a custom node from a serialized project-node document.

    Used by ``Project.from_dict`` so projects remain loadable when the
    definition is not present in the local store.
    """
    raw = blob.get("custom_definition")
    if not isinstance(raw, dict):
        return None
    definition = CustomNodeDefinition.from_dict(raw)
    return make_custom_node_class(definition)()


def build_node_from_blob(blob: Any) -> Node | None:
    """Reconstruct an inner subgraph node from its serialized document."""
    if not isinstance(blob, dict):
        return None
    node_type = str(blob.get("node_type", ""))
    if not node_type:
        return None

    if node_type == SUBGRAPH_INPUT_TYPE:
        node: Node = SubgraphInputNode(socket_type=_socket_type_from_blob(blob))
    elif node_type == SUBGRAPH_OUTPUT_TYPE:
        node = SubgraphOutputNode(socket_type=_socket_type_from_blob(blob))
    else:
        node = global_node_registry.create_node(
            node_type,
            category=str(blob.get("node_category", "")) or None,
        )
        if node is None:
            return None

    node.apply_document(blob)
    return node


def definition_from_project(
    project: Any,
    name: str,
    *,
    description: str = "",
    color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR,
) -> CustomNodeDefinition:
    """Snapshot a live project into a custom node definition.

    Terminal nodes inside ``project`` become the exposed ports.
    """
    nodes: dict[str, dict[str, Any]] = {
        str(node_id): node.to_dict()
        for node_id, node in project.nodes.items()
    }
    connections: list[dict[str, Any]] = [
        {
            "output_node_id": conn.output_node_id,
            "output_slot": conn.output_slot,
            "input_node_id": conn.input_node_id,
            "input_slot": conn.input_slot,
        }
        for conn in project.connections
    ]

    ordered = sorted(
        project.nodes.items(),
        key=lambda item: (float(item[1].y), float(item[1].x), item[0]),
    )
    inputs: list[CustomPort] = []
    outputs: list[CustomPort] = []
    for node_id, node in ordered:
        if node.node_type == SUBGRAPH_INPUT_TYPE:
            socket = node.outputs.get(PORT_SLOT)
            inputs.append(
                CustomPort(
                    name=node.name,
                    socket_type=(
                        socket.socket_type if socket is not None else NodeSocketType.Frame
                    ),
                    terminal_id=str(node_id),
                )
            )
        elif node.node_type == SUBGRAPH_OUTPUT_TYPE:
            socket = node.inputs.get(PORT_SLOT)
            outputs.append(
                CustomPort(
                    name=node.name,
                    socket_type=(
                        socket.socket_type if socket is not None else NodeSocketType.Frame
                    ),
                    terminal_id=str(node_id),
                )
            )

    return CustomNodeDefinition(
        name=name,
        description=description,
        color=color,
        inputs=inputs,
        outputs=outputs,
        nodes=nodes,
        connections=connections,
    )


def sanitize_port_name(name: str, fallback: str = "Port") -> str:
    """Return a readable, socket-safe port name."""
    cleaned = "".join(
        ch if (ch.isalnum() or ch in " _-.") else " " for ch in str(name)
    )
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or fallback


def unique_port_name(base: str, taken: set[str]) -> str:
    """Return ``base`` (or ``base 2``, ``base 3``…) not present in ``taken``."""
    candidate = base
    index = 2
    while candidate in taken:
        candidate = f"{base} {index}"
        index += 1
    return candidate


def _socket_type_from_blob(blob: dict[str, Any]) -> NodeSocketType:
    explicit = _socket_type_from_name(str(blob.get("socket_type", "")))
    return _coerce_socket_type(explicit)


def _socket_type_from_name(name: str) -> NodeSocketType:
    if name:
        try:
            return NodeSocketType[name]
        except KeyError:
            pass
    return NodeSocketType.Frame


def _coerce_socket_type(value: Any) -> NodeSocketType:
    if isinstance(value, NodeSocketType):
        return value
    if isinstance(value, str):
        return _socket_type_from_name(value)
    try:
        return NodeSocketType(value)
    except (TypeError, ValueError):
        return NodeSocketType.Frame


def _identifier(name: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(name))
    if not safe or safe[0].isdigit():
        safe = f"n_{safe}"
    return safe


__all__ = [
    "CUSTOM_NODE_CATEGORY",
    "PORT_SLOT",
    "PORT_SOCKET_TYPES",
    "SUBGRAPH_INPUT_TYPE",
    "SUBGRAPH_OUTPUT_TYPE",
    "TERMINAL_NODE_TYPES",
    "CustomNode",
    "CustomNodeDefinition",
    "CustomPort",
    "SubgraphInputNode",
    "SubgraphOutputNode",
    "build_node_from_blob",
    "create_custom_node_from_document",
    "definition_from_project",
    "is_terminal_node",
    "make_custom_node_class",
    "sanitize_port_name",
    "unique_port_name",
]
