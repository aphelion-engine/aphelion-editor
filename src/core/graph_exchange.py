"""Versioned, human-readable graph exchange format and registry validation."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import difflib
import json
from pathlib import Path
from typing import Any

from core.nodes import global_node_registry
from core.nodes.catalog import BUILTIN_NODE_TYPES
from core.nodes.property_link import sockets_compatible
from core.project import Project

GRAPH_FORMAT = "aphelion-graph"
GRAPH_VERSION = 1


@dataclass(frozen=True)
class GraphIssue:
    code: str
    message: str
    path: str = ""
    node: str | None = None
    port: str | None = None
    suggestions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"suggestions": list(self.suggestions)}


def ensure_registry() -> None:
    if not global_node_registry.get_all_nodes():
        for node_class in BUILTIN_NODE_TYPES:
            global_node_registry.register(node_class, node_class.node_category,
                                          node_class.node_type, node_class.node_description,
                                          node_class.node_color)


def project_to_graph(project: Project, *, node_ids: set[str] | None = None,
                     name: str | None = None) -> dict[str, Any]:
    selected = node_ids if node_ids is not None else set(project.nodes)
    nodes = []
    for node_id in sorted(selected):
        node = project.nodes.get(node_id)
        if node is None:
            continue
        data = node.to_dict()
        nodes.append({"id": node_id, "type": data["node_type"],
                      "category": data.get("node_category", node.node_category),
                      "name": data.get("name", node.name),
                      "position": [float(data.get("x", node.x)), float(data.get("y", node.y))],
                      "inputs": list(node.inputs), "outputs": list(node.outputs),
                      "color": list(node.node_color),
                      "properties": data.get("properties", {}),
                      "animated_properties": data.get("animated_properties", {})})
    connections = []
    for connection in sorted(project.connections, key=lambda item: (
            item.output_node_id, item.output_slot, item.input_node_id, item.input_slot)):
        if connection.output_node_id in selected and connection.input_node_id in selected:
            connections.append({"from": [connection.output_node_id, connection.output_slot],
                                "to": [connection.input_node_id, connection.input_slot]})
    return {"format": GRAPH_FORMAT, "version": GRAPH_VERSION,
            "name": name or project.name, "nodes": nodes, "connections": connections,
            "groups": [], "annotations": []}


def write_graph(data: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def read_graph(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _suggest(value: str, candidates: list[str]) -> tuple[str, ...]:
    return tuple(difflib.get_close_matches(value, candidates, n=3, cutoff=.55))


def validate_graph(data: Any) -> list[GraphIssue]:
    ensure_registry()
    issues: list[GraphIssue] = []
    if not isinstance(data, dict):
        return [GraphIssue("INVALID_DOCUMENT", "Graph document must be a JSON object.")]
    if data.get("format") != GRAPH_FORMAT:
        issues.append(GraphIssue("INVALID_FORMAT", f"Expected format '{GRAPH_FORMAT}'.", "format"))
    version = data.get("version")
    if not isinstance(version, int) or version < 1 or version > GRAPH_VERSION:
        issues.append(GraphIssue("UNSUPPORTED_VERSION", f"Supported graph version is {GRAPH_VERSION}.", "version"))
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return issues + [GraphIssue("INVALID_NODES", "'nodes' must be an array.", "nodes")]
    ids: set[str] = set()
    instances: dict[str, Any] = {}
    for index, item in enumerate(nodes):
        path = f"nodes[{index}]"
        if not isinstance(item, dict):
            issues.append(GraphIssue("INVALID_NODE", "Node entry must be an object.", path)); continue
        node_id = item.get("id")
        if not isinstance(node_id, str) or not node_id:
            issues.append(GraphIssue("INVALID_NODE_ID", "Node id must be a non-empty string.", path + ".id")); continue
        if node_id in ids:
            issues.append(GraphIssue("DUPLICATE_NODE_ID", f"Node id '{node_id}' is duplicated.", path + ".id", node_id=node_id))
        ids.add(node_id)
        node_type = str(item.get("type", ""))
        category = item.get("category")
        info = global_node_registry.create_node(node_type, category if isinstance(category, str) else None)
        if info is None:
            candidates = [entry.name for entry in global_node_registry.get_all_nodes().values()]
            issues.append(GraphIssue("UNKNOWN_NODE_TYPE", f"Unknown node type '{node_type}'.", path + ".type",
                                     node=node_id, suggestions=_suggest(node_type, candidates)))
            continue
        instances[node_id] = info
        position = item.get("position", [item.get("x", 0), item.get("y", 0)])
        if not isinstance(position, list) or len(position) != 2 or not all(isinstance(value, (int, float)) for value in position):
            issues.append(GraphIssue("INVALID_POSITION", "Position must contain two numbers.", path + ".position", node=node_id))
        properties = item.get("properties", {})
        if not isinstance(properties, dict):
            issues.append(GraphIssue("INVALID_PROPERTIES", "Properties must be an object.", path + ".properties", node=node_id)); continue
        for key, value in properties.items():
            prop = info.properties.get(key)
            if prop is None:
                issues.append(GraphIssue("UNKNOWN_PROPERTY", f"Unknown property '{key}'.", path + f".properties.{key}", node=node_id,
                                         suggestions=_suggest(key, list(info.properties))))
                continue
            expected = type(prop.value)
            if isinstance(value, dict) and "__enum__" in value:
                # Project/node serialization deliberately uses tagged enum
                # values; decode_properties will restore the live enum.
                continue
            if prop.value is not None and not isinstance(value, expected):
                issues.append(GraphIssue("INVALID_PROPERTY_TYPE", f"Property '{key}' expects {expected.__name__} but received {type(value).__name__}.",
                                         path + f".properties.{key}", node=node_id))
            if isinstance(value, (int, float)) and prop.slider_min_value != prop.slider_max_value:
                if not prop.slider_min_value <= value <= prop.slider_max_value:
                    issues.append(GraphIssue("PROPERTY_OUT_OF_RANGE", f"Property '{key}' is outside its supported range.",
                                             path + f".properties.{key}", node=node_id))
    connections = data.get("connections", [])
    if not isinstance(connections, list):
        issues.append(GraphIssue("INVALID_CONNECTIONS", "'connections' must be an array.", "connections")); return issues
    for index, item in enumerate(connections):
        path = f"connections[{index}]"
        source, target = (item.get("from"), item.get("to")) if isinstance(item, dict) else (None, None)
        if not (isinstance(source, list) and len(source) == 2 and isinstance(target, list) and len(target) == 2):
            issues.append(GraphIssue("INVALID_CONNECTION", "Connection endpoints must be [node_id, port].", path)); continue
        source_id, source_port = source; target_id, target_port = target
        source_node, target_node = instances.get(source_id), instances.get(target_id)
        if source_node is None or target_node is None:
            issues.append(GraphIssue("MISSING_NODE", "Connection references a missing or invalid node.", path)); continue
        output = source_node.outputs.get(source_port); input_port = target_node.inputs.get(target_port)
        if output is None:
            issues.append(GraphIssue("UNKNOWN_OUTPUT", f"Node '{source_id}' has no output named '{source_port}'. Available outputs: {', '.join(source_node.outputs)}.",
                                     path, source_id, source_port, _suggest(source_port, list(source_node.outputs))))
        if input_port is None:
            issues.append(GraphIssue("UNKNOWN_INPUT", f"Node '{target_id}' has no input named '{target_port}'. Available inputs: {', '.join(target_node.inputs)}.",
                                     path, target_id, target_port, _suggest(target_port, list(target_node.inputs))))
        if output is not None and input_port is not None and not sockets_compatible(output.socket_type, input_port.socket_type):
            issues.append(GraphIssue("INVALID_CONNECTION_TYPE", f"Cannot connect {source_id}.{source_port} ({output.type_label}) to {target_id}.{target_port} ({input_port.type_label}).",
                                     path, target_id, target_port))
    return issues


def graph_to_project(data: dict[str, Any]) -> Project:
    issues = validate_graph(data)
    if issues:
        raise ValueError("\n".join(issue.message for issue in issues))
    ensure_registry()
    project = Project(str(data.get("name", "Untitled Graph")))
    for item in data["nodes"]:
        node = global_node_registry.create_node(item["type"], item.get("category"))
        if node is None:
            raise ValueError(f"Unknown node type: {item['type']}")
        document = {"node_type": node.node_type, "node_category": node.node_category,
                    "name": item.get("name", node.name), "x": item["position"][0],
                    "y": item["position"][1], "properties": item.get("properties", {}),
                    "animated_properties": item.get("animated_properties", {})}
        node.apply_document(document)
        project.add_node(node, str(item["id"]))
    for item in data["connections"]:
        source, target = item["from"], item["to"]
        if not project.connect_nodes(source[0], source[1], target[0], target[1]):
            raise ValueError(f"Could not connect {source} to {target}")
    return project


def graph_schema() -> dict[str, Any]:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Aphelion Graph", "type": "object", "required": ["format", "version", "nodes", "connections"],
            "properties": {"format": {"const": GRAPH_FORMAT}, "version": {"type": "integer"},
                           "name": {"type": "string"}, "nodes": {"type": "array"},
                           "connections": {"type": "array"}, "groups": {"type": "array"}, "annotations": {"type": "array"}}}
