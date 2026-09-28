"""Headless graph, node-schema, and tutorial CLI services."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph_exchange import (
    GRAPH_FORMAT, graph_schema, project_to_graph, read_graph, validate_graph,
    write_graph,
)
from core.graph_renderer import GraphRenderOptions, save_graph_image
from core.nodes import global_node_registry
from core.nodes.catalog import BUILTIN_NODE_TYPES
from core.tutorial_exchange import read_tutorial, tutorial_markdown, validate_tutorial, resolve_steps
from core.serialization import encode_value


def _ensure_nodes() -> None:
    if not global_node_registry.get_all_nodes():
        for node_class in BUILTIN_NODE_TYPES:
            global_node_registry.register(node_class, node_class.node_category,
                                          node_class.node_type, node_class.node_description,
                                          node_class.node_color)


def node_schema() -> dict[str, Any]:
    _ensure_nodes()
    nodes = {}
    for key, info in sorted(global_node_registry.get_all_nodes().items()):
        instance = info.create_instance()
        nodes[info.name] = {
            "type": info.name, "category": info.category, "description": info.description or instance.node_description,
            "inputs": {name: {"type": port.type_label, "description": port.description, "default": encode_value(port.default),
                               "units": port.units, "coordinate_space": port.coordinate_space}
                       for name, port in instance.inputs.items()},
            "outputs": {name: {"type": port.type_label, "description": port.description, "default": encode_value(port.default),
                               "units": port.units, "coordinate_space": port.coordinate_space}
                        for name, port in instance.outputs.items()},
            "properties": {name: {"type": type(prop.value).__name__ if prop.value is not None else prop.input_type.name,
                                   "default": encode_value(prop.value), "description": prop.description,
                                   "min": prop.slider_min_value, "max": prop.slider_max_value,
                                   "label": prop.label}
                           for name, prop in instance.properties.items()},
        }
    return {"format": "aphelion-node-schema", "version": 1, "nodes": nodes}


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def graph_command(args) -> int:
    if args.action == "validate":
        try: data = read_graph(args.input); issues = validate_graph(data)
        except Exception as exc: issues = [{"code": "INVALID_JSON", "message": str(exc)}]
        payload = {"valid": not issues, "errors": [issue.to_dict() if hasattr(issue, "to_dict") else issue for issue in issues]}
        if args.json: print(json.dumps(payload, indent=2))
        elif issues: print("Graph validation failed:\n" + "\n".join(f"[{item['code']}] {item['message']}" for item in payload["errors"]))
        else: print("✓ Graph is valid")
        return 0 if not issues else 1
    if args.action == "render":
        data = read_graph(args.input); issues = validate_graph(data)
        if issues: print("Graph validation failed", file=__import__("sys").stderr); return 1
        output = args.output or str(Path(args.input).with_suffix(".png"))
        save_graph_image(data, output, GraphRenderOptions(scale=args.scale, background=args.theme,
                         padding=args.padding, watermark=not args.no_watermark,
                         max_width=args.max_width, max_height=args.max_height))
        print(output); return 0
    if args.action == "format":
        data = read_graph(args.input); write_graph(data, args.input if args.write else args.output or "formatted.apgraph"); return 0
    if args.action == "inspect":
        data = read_graph(args.input); print(f"Graph: {data.get('name', 'Untitled')}")
        for index, node in enumerate(data.get("nodes", []), 1): print(f"{index}. {node.get('type')} [{node.get('position', [0, 0])[0]}, {node.get('position', [0, 0])[1]}]")
        print(f"\nConnections: {len(data.get('connections', []))}"); [print(f"{item['from'][0]}.{item['from'][1]} -> {item['to'][0]}.{item['to'][1]}") for item in data.get("connections", [])]; return 0
    if args.action == "schema": print(json.dumps(graph_schema(), indent=2)); return 0
    if args.action == "export":
        from app_io.aph_format import load_aph
        project = load_aph(args.project); write_graph(project_to_graph(project), args.output); return 0
    if args.action == "import":
        from core.graph_exchange import graph_to_project
        from app_io.aph_format import save_aph
        save_aph(args.output, graph_to_project(read_graph(args.input))); print(args.output); return 0
    return 2


def nodes_command(args) -> int:
    schema = node_schema()
    if args.action == "list":
        print("\n".join(sorted(schema["nodes"]))); return 0
    if args.action == "describe":
        node = schema["nodes"].get(args.node)
        if node is None: print(f"Unknown node type: {args.node}", file=__import__("sys").stderr); return 1
        print(json.dumps(node, indent=2) if args.json else f"{args.node}\n\n{node['description']}\n\nInputs:\n" + "\n".join(f"{k}: {v['type']}\n    {v['description']}" for k,v in node['inputs'].items()) + "\n\nOutputs:\n" + "\n".join(f"{k}: {v['type']}\n    {v['description']}" for k,v in node['outputs'].items())); return 0
    if args.action == "export-schema": print(json.dumps(schema, indent=2)); return 0
    return 2


def tutorial_command(args) -> int:
    if args.action == "schema":
        print(json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Aphelion Tutorial",
                          "type": "object", "required": ["format", "version", "steps"],
                          "properties": {"format": {"const": "aphelion-tutorial"}, "version": {"type": "integer"},
                                         "title": {"type": "string"}, "description": {"type": "string"},
                                         "steps": {"type": "array"}}}, indent=2))
        return 0
    data = read_tutorial(args.input); errors = validate_tutorial(data)
    if args.action == "validate":
        if args.json: print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
        elif errors: print("Tutorial validation failed:\n" + "\n".join(f"Step {e.get('step')}: [{e['code']}] {e['message']}" for e in errors))
        else: print("✓ Tutorial is valid")
        return 0 if not errors else 1
    if errors: print("Tutorial validation failed", file=__import__("sys").stderr); return 1
    output = Path(args.output or Path(args.input).stem); output.mkdir(parents=True, exist_ok=True)
    names = []
    for index, graph in enumerate(resolve_steps(data), 1):
        step = data.get("steps", [])[index - 1]
        highlight = tuple((step.get("highlight") or {}).get("nodes", []))
        name = f"step-{index:02d}.png"; save_graph_image(graph, output / name, GraphRenderOptions(scale=args.scale, highlight_ids=highlight)); names.append(name)
    (output / "tutorial.md").write_text(tutorial_markdown(data, names), encoding="utf-8")
    print(output); return 0
