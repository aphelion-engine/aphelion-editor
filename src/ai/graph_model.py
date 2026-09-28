"""AI-readable project representation built on the editor's own serialization.

Nothing here invents a second source of truth. The graph document produced by
:func:`graph_to_ai` *is* the ``.apgraph`` exchange document from
:mod:`core.graph_exchange` (restricted to the requested nodes), and node
schemas are read straight from the live registry and the port documentation
that already powers the GUI tooltips.

That sharing is what keeps the assistant honest: it cannot describe a port,
property, or node type that the editor itself does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.graph_exchange import ensure_registry, project_to_graph
from core.nodes.base import NodePropertyInputType
from core.nodes.registry import global_node_registry


def registry_types() -> dict[str, list[Any]]:
    """Return every registered type keyed by ``node_type`` name.

    A handful of built-in types share a display name across categories, so the
    value is always a list.
    """
    ensure_registry()
    index: dict[str, list[Any]] = {}
    for info in global_node_registry.get_all_nodes().values():
        index.setdefault(info.name, []).append(info)
    for infos in index.values():
        infos.sort(key=lambda item: item.category)
    return index


def resolve_type(name: str, category: str | None = None) -> Any | None:
    """Resolve a type name (optionally within one category) to a NodeInfo."""
    ensure_registry()
    index = registry_types()
    candidates = index.get(name)
    if not candidates:
        # Case-insensitive fallback keeps the model usable when it types
        # ``floortracker`` instead of ``Floor Tracker``.
        lowered = name.strip().lower()
        for type_name, infos in index.items():
            if type_name.lower() == lowered:
                candidates = infos
                break
    if not candidates:
        return None
    if category:
        for info in candidates:
            if info.category == category:
                return info
        return None
    return candidates[0]


def list_node_types(
    *,
    category: str | None = None,
    query: str | None = None,
    limit: int = 400,
) -> list[dict[str, Any]]:
    """List registered node types, optionally filtered by category/text."""
    ensure_registry()
    needle = (query or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for info in global_node_registry.get_all_nodes().values():
        if category and info.category != category:
            continue
        if needle and needle not in (
            f"{info.name} {info.category} {info.description}".lower()
        ):
            continue
        rows.append(
            {
                "type": info.name,
                "category": info.category,
                "description": info.description,
            }
        )
    rows.sort(key=lambda row: (row["category"], row["type"]))
    return rows[:limit]


def categories() -> list[str]:
    ensure_registry()
    return sorted(global_node_registry.get_categories())


def _property_options(prop: Any) -> list[dict[str, Any]]:
    """Return enum choices for a property, if it has any."""
    value = prop.value
    if isinstance(value, Enum):
        options: list[dict[str, Any]] = []
        for member in type(value):
            entry = {"value": member.name}
            label = getattr(member, "value", member.name)
            if isinstance(label, str):
                entry["label"] = label
            options.append(entry)
        return options
    return []


def describe_property(key: str, prop: Any) -> dict[str, Any]:
    """Describe one node property for the model."""
    payload: dict[str, Any] = {
        "key": key,
        "label": prop.label or key.replace("_", " ").title(),
        "type": prop.input_type.name,
        "group": prop.group,
    }
    if prop.description:
        payload["description"] = prop.description
    if prop.suffix:
        payload["units"] = prop.suffix.strip()
    default = prop.value
    if isinstance(default, Enum):
        payload["default"] = default.name
    elif isinstance(default, tuple):
        payload["default"] = list(default)
    else:
        try:
            payload["default"] = default
        except Exception:  # noqa: BLE001 - exotic custom widgets
            payload["default"] = None
    if prop.input_type in (
        NodePropertyInputType.Number,
        NodePropertyInputType.Slider,
    ) and prop.slider_max_value > prop.slider_min_value:
        payload["minimum"] = prop.slider_min_value
        payload["maximum"] = prop.slider_max_value
    if prop.input_type == NodePropertyInputType.Slider:
        payload["integer"] = isinstance(prop.value, int) and not isinstance(
            prop.value, bool
        )
    options = _property_options(prop)
    if options:
        payload["options"] = options
    return payload


def _describe_port(port: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": port.name,
        "type": port.socket_type.name,
        "type_label": port.type_label,
    }
    if port.description:
        payload["description"] = port.description
    if port.default is not None:
        payload["default"] = port.default
    if port.units:
        payload["units"] = port.units
    if port.coordinate_space:
        payload["coordinate_space"] = port.coordinate_space
    return payload


@dataclass(frozen=True)
class NodeTypeDescription:
    """Full contract for one registered node type."""

    type: str
    category: str
    description: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    properties: list[dict[str, Any]]
    preview_cost: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "category": self.category,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "properties": self.properties,
            "preview_cost": self.preview_cost,
        }


def describe_node_type(
    name: str,
    *,
    category: str | None = None,
    include_property_details: bool = True,
) -> NodeTypeDescription | None:
    """Return the full contract for a registered node type.

    This is the single call that prevents hallucinated nodes, ports, and
    properties. Its data comes from the live node instance the registry would
    build, so it is exactly what the editor would create.
    """
    info = resolve_type(name, category)
    if info is None:
        return None
    try:
        instance = info.create_instance()
    except Exception:  # noqa: BLE001 - a broken plugin must not kill the call
        return None

    properties = [
        describe_property(key, prop)
        for key, prop in sorted(
            instance.properties.items(), key=lambda item: item[1].priority
        )
        if not key.startswith("_input_")
    ]
    if not include_property_details:
        properties = [{"key": entry["key"]} for entry in properties]

    return NodeTypeDescription(
        type=instance.node_type,
        category=instance.node_category,
        description=instance.node_description or info.description,
        inputs=[_describe_port(port) for port in instance.inputs.values()],
        outputs=[_describe_port(port) for port in instance.outputs.values()],
        properties=properties,
        preview_cost=int(getattr(instance.preview_cost, "value", 1)),
    )


def describe_node_instance(node_id: str, node: Any) -> dict[str, Any]:
    """Describe one live node, including current property values."""
    properties: dict[str, Any] = {}
    for key, prop in node.properties.items():
        if key.startswith("_input_"):
            continue
        value = prop.value
        if isinstance(value, Enum):
            properties[key] = value.name
        elif isinstance(value, tuple):
            properties[key] = list(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            properties[key] = value
        else:
            properties[key] = str(value)
    return {
        "id": node_id,
        "type": node.node_type,
        "category": node.node_category,
        "name": node.name,
        "position": [float(node.x), float(node.y)],
        "inputs": list(node.inputs),
        "outputs": list(node.outputs),
        "properties": properties,
        "animated_properties": sorted(node.animated_properties),
    }


def graph_to_ai(
    project: Any,
    *,
    node_ids: set[str] | None = None,
    include_properties: bool = True,
    name: str | None = None,
) -> dict[str, Any]:
    """Return the AI-readable graph document for ``project``.

    Delegates to the ``.apgraph`` serializer so the assistant and the CLI,
    graph renderer, and tutorial exporter all speak the same shape.
    """
    document = project_to_graph(project, node_ids=node_ids, name=name)
    if not include_properties:
        for node in document.get("nodes", ()):
            node.pop("properties", None)
            node.pop("animated_properties", None)
    return document


def project_summary(project: Any) -> dict[str, Any]:
    """Return a compact, always-cheap project overview."""
    nodes: dict[str, Any] = getattr(project, "nodes", {}) or {}
    by_category: dict[str, int] = {}
    for node in nodes.values():
        by_category[node.node_category] = by_category.get(node.node_category, 0) + 1

    active = getattr(project, "active_viewer", None)
    viewer = nodes.get(active) if active else None
    media: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        path = node.get_property("file_path")
        if path is None or not getattr(path, "value", None):
            continue
        media.append(
            {
                "node_id": node_id,
                "node": node.name,
                # Filenames are gated behind ACCESS_MEDIA; callers that lack
                # the permission replace this with the node name only.
                "file": str(path.value),
            }
        )

    return {
        "name": project.name,
        "file_path": getattr(project, "file_path", None),
        "fps": project.fps,
        "width": project.width,
        "height": project.height,
        "duration": project.duration,
        "frame_count": int(project.max_frame) + 1,
        "current_frame": project.current_frame,
        "node_count": len(nodes),
        "connection_count": len(project.connections),
        "nodes_by_category": by_category,
        "active_viewer": active,
        "active_viewer_name": viewer.name if viewer is not None else None,
        "media": media,
    }


def graph_digest(project: Any) -> dict[str, Any]:
    """Return a compact adjacency digest for 'explain this graph' prompts."""
    nodes: dict[str, Any] = getattr(project, "nodes", {}) or {}
    outgoing: dict[str, list[dict[str, str]]] = {}
    incoming: dict[str, list[dict[str, str]]] = {}
    for connection in project.connections:
        outgoing.setdefault(connection.output_node_id, []).append(
            {
                "slot": connection.output_slot,
                "to": connection.input_node_id,
                "to_slot": connection.input_slot,
            }
        )
        incoming.setdefault(connection.input_node_id, []).append(
            {
                "slot": connection.input_slot,
                "from": connection.output_node_id,
                "from_slot": connection.output_slot,
            }
        )
    return {
        "nodes": [
            describe_node_instance(node_id, node)
            for node_id, node in sorted(nodes.items())
        ],
        "edges": [
            {
                "from": connection.output_node_id,
                "from_port": connection.output_slot,
                "to": connection.input_node_id,
                "to_port": connection.input_slot,
            }
            for connection in sorted(
                project.connections,
                key=lambda item: (
                    item.output_node_id,
                    item.output_slot,
                    item.input_node_id,
                    item.input_slot,
                ),
            )
        ],
    }


__all__ = [
    "NodeTypeDescription",
    "categories",
    "describe_node_instance",
    "describe_node_type",
    "describe_property",
    "graph_digest",
    "graph_to_ai",
    "list_node_types",
    "project_summary",
    "registry_types",
    "resolve_type",
]
