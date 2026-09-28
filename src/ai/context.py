"""Project context for the agent.

The whole project is never dumped into a prompt. A small, structured block is
built from sources the user has permitted, and anything larger is fetched on
demand through a tool call. That keeps token use bounded on projects with
hundreds of nodes and keeps the model focused on what the user asked about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ai.graph_model import describe_node_type, project_summary
from ai.permissions import PermissionPolicy
from ai.types import Permission
from ai.validation import validate_project

#: Hard cap on the default context block, in characters (~half a token each).
DEFAULT_BLOCK_CHARS: int = 4000


@dataclass
class ContextRequest:
    """Which context sources a caller wants included."""

    summary: bool = True
    selection: bool = True
    graph_overview: bool = True
    validation: bool = True
    timeline: bool = False
    node_ids: list[str] = field(default_factory=list)
    max_chars: int = DEFAULT_BLOCK_CHARS


class ProjectContextProvider:
    """Builds compact context blocks from the live project."""

    def __init__(self, host: Any, permissions: PermissionPolicy) -> None:
        self.host = host
        self.permissions = permissions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, request: ContextRequest | None = None) -> str:
        """Return a formatted context block for the system prompt."""
        request = request or ContextRequest()
        payload: dict[str, Any] = {}
        project = self.host.project

        if request.summary:
            summary = project_summary(project)
            if not self.permissions.allows(Permission.ACCESS_MEDIA):
                summary["media"] = [
                    {"node_id": entry["node_id"], "node": entry["node"]}
                    for entry in summary.get("media", [])
                ]
                summary["media_filenames_withheld"] = True
            payload["project"] = summary

        if request.selection:
            selection = self.selection_block()
            if selection:
                payload["selection"] = selection

        if request.graph_overview:
            payload["graph"] = self.graph_overview(project)

        if request.validation:
            report = validate_project(project)
            payload["validation"] = {
                "ok": report.ok,
                "errors": [issue.to_dict() for issue in report.errors][:8],
                "warnings": [issue.to_dict() for issue in report.warnings][:5],
            }

        if request.timeline:
            in_point, out_point = self.host.timeline_range()
            payload["timeline"] = {
                "current_frame": project.current_frame,
                "max_frame": int(project.max_frame),
                "in_point": in_point,
                "out_point": out_point,
            }

        if request.node_ids:
            nodes = project.nodes
            payload["mentioned_nodes"] = [
                {
                    "id": node_id,
                    "type": nodes[node_id].node_type,
                    "name": nodes[node_id].name,
                }
                for node_id in request.node_ids
                if node_id in nodes
            ]

        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > request.max_chars:
            payload = _trim(payload, request.max_chars)
            text = json.dumps(payload, ensure_ascii=False, default=str)
        return text

    def selection_block(self) -> list[dict[str, Any]]:
        """Describe the current selection (what "this" means right now)."""
        project = self.host.project
        rows: list[dict[str, Any]] = []
        for node_id in self.host.selected_node_ids():
            node = project.nodes.get(node_id)
            if node is None:
                continue
            entry = {
                "id": node_id,
                "type": node.node_type,
                "name": node.name,
            }
            if node.name and any(
                len(connection.input_node_id) and connection.input_node_id == node_id
                for connection in project.connections
            ):
                entry["has_inputs_connected"] = True
            contract = describe_node_type(node.node_type, category=node.node_category)
            if contract is not None:
                entry["section"] = contract.category
            rows.append(entry)
        return rows

    def graph_overview(self, project: Any) -> dict[str, Any]:
        """Return a tiny, always-cheap graph sketch.

        Full adjacency lives behind the ``graph.inspect`` tool; this is just
        enough for the model to know what kind of composition it is looking at.
        """
        by_category: dict[str, list[str]] = {}
        for node_id, node in project.nodes.items():
            by_category.setdefault(node.node_category, []).append(node.name)
        viewer = (
            project.nodes.get(project.active_viewer)
            if project.active_viewer
            else None
        )
        return {
            "node_count": len(project.nodes),
            "connection_count": len(project.connections),
            "categories": {
                category: names[:6]
                for category, names in sorted(by_category.items())
            },
            "active_viewer": (
                {"id": project.active_viewer, "name": viewer.name}
                if viewer is not None
                else None
            ),
            "note": (
                "Call graph.inspect for connections and property values, "
                "node.inspect for one node."
            ),
        }

    def registry_hint(self) -> str:
        """A short reminder of how to discover capabilities."""
        return (
            "Use node.list_types / node.describe_type to discover real node "
            "types, ports, and properties before creating or configuring."
        )


def _trim(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Drop the least essential parts until the payload fits the budget."""
    trimmed = dict(payload)
    graph = trimmed.get("graph")
    if isinstance(graph, dict):
        categories = graph.get("categories")
        if isinstance(categories, dict):
            graph["categories"] = dict(list(categories.items())[:8])
    validation = trimmed.get("validation")
    if isinstance(validation, dict):
        validation["warnings"] = validation.get("warnings", [])[:2]
        validation["errors"] = validation.get("errors", [])[:4]

    text = json.dumps(trimmed, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return trimmed

    trimmed.pop("validation", None)
    trimmed.pop("timeline", None)
    trimmed.pop("mentioned_nodes", None)
    text = json.dumps(trimmed, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return trimmed

    trimmed.pop("graph", None)
    return trimmed


__all__ = ["ContextRequest", "ProjectContextProvider"]
