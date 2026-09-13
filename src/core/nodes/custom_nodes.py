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

from core.nodes.base import (ColorRgb, Node, NodeProperty,
                             NodePropertyInputType, NodeSocket, NodeSocketType)
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

#: Property kinds that can be exposed as an adjustable custom parameter.
CUSTOM_PROPERTY_TYPES: tuple[NodePropertyInputType, ...] = (
    NodePropertyInputType.Slider,
    NodePropertyInputType.Number,
    NodePropertyInputType.Checkbox,
    NodePropertyInputType.Text,
    NodePropertyInputType.Color,
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
class CustomProperty:
    """An adjustable parameter exposed by a custom node.

    A custom property is a normal node property on the custom node instance
    whose value is pushed onto a chosen property of an *inner* node whenever
    the custom node is evaluated. That makes the parameter actually drive the
    embedded graph.
    """

    name: str
    label: str = ""
    input_type: NodePropertyInputType = NodePropertyInputType.Slider
    default: Any = 0.0
    min_value: float = 0.0
    max_value: float = 1.0
    group: str = "Parameters"
    description: str = ""
    suffix: str = ""
    #: Inner node whose property this parameter drives.
    target_node_id: str = ""
    #: Property key on that inner node.
    target_key: str = ""

    @property
    def display_label(self) -> str:
        return self.label or self.name.replace("_", " ").title()

    def to_dict(self) -> dict[str, Any]:
        from core.serialization import encode_value

        return {
            "name": self.name,
            "label": self.label,
            "input_type": self.input_type.name,
            "default": encode_value(self.default),
            "min_value": float(self.min_value),
            "max_value": float(self.max_value),
            "group": self.group,
            "description": self.description,
            "suffix": self.suffix,
            "target_node_id": self.target_node_id,
            "target_key": self.target_key,
        }

    @classmethod
    def from_dict(cls, data: Any) -> CustomProperty | None:
        if not isinstance(data, dict):
            return None
        name = str(data.get("name", "")).strip()
        if not name:
            return None

        from core.serialization import decode_value

        try:
            input_type = NodePropertyInputType[
                str(data.get("input_type", "Slider"))
            ]
        except KeyError:
            input_type = NodePropertyInputType.Slider

        default = decode_value(data.get("default"))
        if input_type == NodePropertyInputType.Color:
            default = _coerce_rgb(default)
        elif input_type == NodePropertyInputType.Checkbox:
            default = bool(default)
        elif input_type in (
            NodePropertyInputType.Slider,
            NodePropertyInputType.Number,
        ):
            try:
                default = float(default)
            except (TypeError, ValueError):
                default = 0.0
        elif input_type == NodePropertyInputType.Text:
            default = "" if default is None else str(default)

        def _float(key: str, fallback: float) -> float:
            try:
                return float(data.get(key, fallback))
            except (TypeError, ValueError):
                return fallback

        return cls(
            name=name,
            label=str(data.get("label", "")),
            input_type=input_type,
            default=default,
            min_value=_float("min_value", 0.0),
            max_value=_float("max_value", 1.0),
            group=str(data.get("group", "")) or "Parameters",
            description=str(data.get("description", "")),
            suffix=str(data.get("suffix", "")),
            target_node_id=str(data.get("target_node_id", "")),
            target_key=str(data.get("target_key", "")),
        )

    def copy(self) -> CustomProperty:
        restored = CustomProperty.from_dict(self.to_dict())
        assert restored is not None
        return restored


@dataclass
class CustomNodeDefinition:
    """Serializable description of a reusable custom node."""

    name: str
    description: str = ""
    color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR
    inputs: list[CustomPort] = field(default_factory=list)
    outputs: list[CustomPort] = field(default_factory=list)
    properties: list[CustomProperty] = field(default_factory=list)
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
            "properties": [prop.to_dict() for prop in self.properties],
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

        properties: list[CustomProperty] = []
        for raw_prop in data.get("properties", []) or []:
            prop = CustomProperty.from_dict(raw_prop)
            if prop is not None:
                properties.append(prop)

        return cls(
            name=str(data.get("name", "")).strip() or "Custom Node",
            description=str(data.get("description", "")),
            color=color,
            inputs=inputs,
            outputs=outputs,
            properties=properties,
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

    # -- sockets / properties ---------------------------------------------

    def _setup_sockets(self) -> None:
        for port in self.definition.inputs:
            self.add_input(port.name, port.socket_type)
        for port in self.definition.outputs:
            self.add_output(port.name, port.socket_type)
        self._setup_custom_properties()

    def _setup_custom_properties(self) -> None:
        """Rebuild exposed parameters from the definition.

        Existing values for unchanged parameter names are preserved so a live
        definition refresh (edit) does not reset the user's settings.
        """
        existing = {key: prop.value for key, prop in self.properties.items()}
        self.properties.clear()
        for index, spec in enumerate(self.definition.properties):
            prop = build_node_property(spec, priority=index)
            if spec.name in existing:
                prop.value = existing[spec.name]
            self.properties[spec.name] = prop

    def rebuild_sockets(self) -> None:
        """Re-create ports and parameters from the current definition."""
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

    def custom_value(self, name: str, fallback: Any = None) -> Any:
        """Return the current value of an exposed parameter."""
        prop = self.properties.get(name)
        if prop is None:
            spec = next(
                (item for item in self.definition.properties if item.name == name),
                None,
            )
            return fallback if spec is None else spec.default
        value = prop.value
        curve = self.animated_properties.get(name)
        if (
            curve is not None
            and not curve.is_empty
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return curve.value_at(self._current_frame_num)
        return value

    def embedded_project(self) -> Any:
        """Return the (cached) ``Project`` holding this node's inner graph."""
        return self._ensure_subgraph()

    def _apply_custom_properties(self, subgraph: Any) -> None:
        """Push exposed parameter values onto the inner nodes they drive."""
        for spec in self.definition.properties:
            if not spec.target_node_id or not spec.target_key:
                continue
            target = subgraph.nodes.get(spec.target_node_id)
            if target is None:
                continue
            inner_prop = target.properties.get(spec.target_key)
            if inner_prop is None:
                continue
            inner_prop.value = self.custom_value(spec.name, spec.default)
            subgraph.invalidate_cache(spec.target_node_id)

    # -- evaluation --------------------------------------------------------

    def evaluate(self, frame_num: int) -> dict[str, Any]:
        subgraph = self._ensure_subgraph()
        if subgraph is None:
            return {}

        self._sync_subgraph_context(subgraph)

        # Push exposed parameter values onto the inner nodes they drive.
        self._apply_custom_properties(subgraph)

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
        # Apply the embedded definition first so its ports and parameters
        # exist before base property restoration resolves saved values.
        blob = data.get("custom_definition")
        if isinstance(blob, dict):
            self.definition = CustomNodeDefinition.from_dict(blob)
            self.rebuild_sockets()
            self._subgraph = None
        super().apply_document(data)

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
    properties: list[CustomProperty] | None = None,
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
        properties=list(properties or []),
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


# ============================================================================
# Custom parameter helpers
# ============================================================================


def sanitize_property_key(name: str, fallback: str = "parameter") -> str:
    """Return a snake_case property key derived from a display name."""
    cleaned: list[str] = []
    for ch in str(name).strip().lower():
        if ch.isalnum():
            cleaned.append(ch)
        elif cleaned and cleaned[-1] != "_":
            cleaned.append("_")
    key = "".join(cleaned).strip("_")
    if not key or key[0].isdigit():
        key = f"{fallback}_{key}" if key else fallback
    return key


def unique_property_key(base: str, taken: set[str]) -> str:
    """Return ``base`` (or ``base_2``, ``base_3``…) not present in ``taken``."""
    candidate = base
    index = 2
    while candidate in taken:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def bindable_property_targets(node: Node) -> list[tuple[str, NodeProperty]]:
    """Return property keys on ``node`` that can back a custom parameter."""
    items: list[tuple[str, NodeProperty]] = []
    for key, prop in node.properties.items():
        if key.startswith("_input_"):
            continue
        if prop.input_type in CUSTOM_PROPERTY_TYPES:
            items.append((key, prop))
    items.sort(key=lambda item: (item[1].priority, item[1].label or item[0]))
    return items


def custom_property_from_target(
    node: Node,
    node_id: str,
    key: str,
    *,
    name: str = "",
) -> CustomProperty | None:
    """Derive a custom parameter spec from an inner node's property."""
    prop = node.properties.get(key)
    if prop is None or prop.input_type not in CUSTOM_PROPERTY_TYPES:
        return None

    label = prop.label or key.replace("_", " ").title()
    fallback_key = sanitize_property_key(key, "parameter")
    return CustomProperty(
        name=name or fallback_key,
        label=label,
        input_type=prop.input_type,
        default=prop.value,
        min_value=float(prop.slider_min_value),
        max_value=float(prop.slider_max_value),
        group=prop.group or "Parameters",
        description=prop.description,
        suffix=prop.suffix,
        target_node_id=str(node_id),
        target_key=key,
    )


def build_node_property(spec: CustomProperty, *, priority: int) -> NodeProperty:
    """Create the runtime ``NodeProperty`` for an exposed parameter."""
    common: dict[str, Any] = {
        "priority": priority,
        "group": spec.group or "Parameters",
        "label": spec.display_label,
        "description": spec.description
        or f"Adjustable parameter: {spec.display_label}",
        "suffix": spec.suffix,
    }

    if spec.input_type == NodePropertyInputType.Checkbox:
        return NodeProperty(
            input_type=NodePropertyInputType.Checkbox,
            value=bool(spec.default),
            **common,
        )
    if spec.input_type == NodePropertyInputType.Text:
        return NodeProperty(
            input_type=NodePropertyInputType.Text,
            value="" if spec.default is None else str(spec.default),
            **common,
        )
    if spec.input_type == NodePropertyInputType.Color:
        return NodeProperty(
            input_type=NodePropertyInputType.Color,
            value=_coerce_rgb(spec.default),
            **common,
        )

    input_type = (
        NodePropertyInputType.Number
        if spec.input_type == NodePropertyInputType.Number
        else NodePropertyInputType.Slider
    )
    try:
        value = float(spec.default)
    except (TypeError, ValueError):
        value = 0.0
    return NodeProperty(
        input_type=input_type,
        value=value,
        slider_min_value=float(spec.min_value),
        slider_max_value=float(spec.max_value),
        **common,
    )


def format_property_value(spec: CustomProperty) -> str:
    """Return a compact editable text form of a parameter default."""
    if spec.input_type == NodePropertyInputType.Color:
        rgb = _coerce_rgb(spec.default)
        return f"{rgb[0]}, {rgb[1]}, {rgb[2]}"
    if spec.input_type == NodePropertyInputType.Checkbox:
        return "true" if spec.default else "false"
    if spec.input_type in (
        NodePropertyInputType.Slider,
        NodePropertyInputType.Number,
    ):
        try:
            return f"{float(spec.default):g}"
        except (TypeError, ValueError):
            return "0"
    return "" if spec.default is None else str(spec.default)


def parse_property_value(spec: CustomProperty, text: str) -> Any:
    """Parse an edited default value back into the parameter's value type."""
    raw = str(text).strip()
    if spec.input_type == NodePropertyInputType.Checkbox:
        return raw.lower() in {"1", "true", "yes", "on"}
    if spec.input_type == NodePropertyInputType.Color:
        parts = [piece for piece in raw.replace(
            ";", ",").split(",") if piece.strip()]
        if len(parts) < 3:
            return _coerce_rgb(spec.default)
        channels: list[int] = []
        for piece in parts[:3]:
            try:
                channels.append(max(0, min(255, int(float(piece.strip())))))
            except ValueError:
                channels.append(128)
        return (channels[0], channels[1], channels[2])
    if spec.input_type in (
        NodePropertyInputType.Slider,
        NodePropertyInputType.Number,
    ):
        try:
            return float(raw)
        except ValueError:
            try:
                return float(spec.default)
            except (TypeError, ValueError):
                return 0.0
    return raw


def _coerce_rgb(value: Any) -> ColorRgb:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (
                max(0, min(255, int(value[0]))),
                max(0, min(255, int(value[1]))),
                max(0, min(255, int(value[2]))),
            )
        except (TypeError, ValueError):
            pass
    return (128, 128, 128)


__all__ = [
    "CUSTOM_NODE_CATEGORY",
    "CUSTOM_PROPERTY_TYPES",
    "PORT_SLOT",
    "PORT_SOCKET_TYPES",
    "SUBGRAPH_INPUT_TYPE",
    "SUBGRAPH_OUTPUT_TYPE",
    "TERMINAL_NODE_TYPES",
    "CustomNode",
    "CustomNodeDefinition",
    "CustomPort",
    "CustomProperty",
    "SubgraphInputNode",
    "SubgraphOutputNode",
    "bindable_property_targets",
    "build_node_from_blob",
    "build_node_property",
    "create_custom_node_from_document",
    "custom_property_from_target",
    "definition_from_project",
    "format_property_value",
    "is_terminal_node",
    "make_custom_node_class",
    "parse_property_value",
    "port_input_socket",
    "rename_in_definition",
    "sanitize_port_name",
    "sanitize_property_key",
    "unique_port_name",
    "unique_property_key",
    "with_ports",
]
