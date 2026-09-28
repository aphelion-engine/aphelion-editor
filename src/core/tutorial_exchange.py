"""AI-friendly tutorial format built on the graph exchange/renderer APIs."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from core.graph_exchange import GRAPH_VERSION, validate_graph

TUTORIAL_FORMAT = "aphelion-tutorial"
TUTORIAL_VERSION = 1


def read_tutorial(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _apply_operations(graph: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(graph)
    by_id = {node["id"]: node for node in result.setdefault("nodes", [])}
    for operation in operations:
        kind = operation.get("op")
        if kind == "add_node":
            node = dict(operation.get("node", {})); result["nodes"].append(node); by_id[node["id"]] = node
        elif kind == "remove_node":
            node_id = operation.get("id"); result["nodes"] = [node for node in result["nodes"] if node.get("id") != node_id]; by_id.pop(node_id, None)
            result["connections"] = [item for item in result.get("connections", []) if item.get("from", [None])[0] != node_id and item.get("to", [None])[0] != node_id]
        elif kind == "move_node" and operation.get("id") in by_id:
            by_id[operation["id"]]["position"] = operation.get("position", [0, 0])
        elif kind == "set_property" and operation.get("id") in by_id:
            by_id[operation["id"]].setdefault("properties", {})[operation["property"]] = operation.get("value")
        elif kind == "connect":
            result.setdefault("connections", []).append({"from": operation["from"], "to": operation["to"]})
        elif kind == "disconnect":
            result["connections"] = [item for item in result.get("connections", []) if not (item.get("from") == operation.get("from") and item.get("to") == operation.get("to"))]
    return result


def resolve_steps(data: dict[str, Any]) -> list[dict[str, Any]]:
    current = deepcopy(data.get("graph", {"format": "aphelion-graph", "version": GRAPH_VERSION, "nodes": [], "connections": []}))
    steps = []
    for step in data.get("steps", []):
        if isinstance(step.get("graph"), dict):
            current = deepcopy(step["graph"])
        elif isinstance(step.get("operations"), list):
            current = _apply_operations(current, step["operations"])
        steps.append(current)
    return steps


def validate_tutorial(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or data.get("format") != TUTORIAL_FORMAT:
        return [{"code": "INVALID_TUTORIAL_FORMAT", "message": f"Expected format '{TUTORIAL_FORMAT}'."}]
    if data.get("version") != TUTORIAL_VERSION:
        return [{"code": "UNSUPPORTED_TUTORIAL_VERSION", "message": f"Supported tutorial version is {TUTORIAL_VERSION}."}]
    errors = []
    for index, graph in enumerate(resolve_steps(data), 1):
        errors.extend({"step": index, **issue.to_dict()} for issue in validate_graph(graph))
    return errors


def tutorial_markdown(data: dict[str, Any], image_names: list[str]) -> str:
    lines = [f"# {data.get('title', 'Aphelion Tutorial')}", "", str(data.get("description", "")), ""]
    for index, (step, image) in enumerate(zip(data.get("steps", []), image_names), 1):
        lines.extend([f"## Step {index}: {step.get('title', f'Step {index}')}", "", str(step.get("text", "")), "", f"![Step {index}]({image})", ""])
    return "\n".join(lines)
