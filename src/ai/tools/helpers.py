"""Shared helpers for tool handlers.

The most important one is :func:`resolve_node`: it lets the model refer to a
node by id, by exact name, by case-insensitive name, or by the pronoun
``"this"``/``"selected"`` meaning the current graph selection. That is what
makes "make this tracker more accurate" work without the user pasting an id.
"""

from __future__ import annotations

import difflib
from typing import Any

from ai.errors import ToolError

#: Words the model can use to mean "the node(s) the user has selected".
SELECTION_ALIASES: frozenset[str] = frozenset(
    {"this", "these", "it", "that", "selected", "selection", "@selection", "current"}
)


def suggest(value: str, candidates: list[str]) -> list[str]:
    """Return close matches for a mistyped name."""
    return difflib.get_close_matches(value, candidates, n=3, cutoff=0.5)


def resolve_node(ctx: Any, reference: str) -> tuple[str, Any]:
    """Resolve a node reference to ``(node_id, node)``.

    Raises:
        ToolError: with ``NODE_NOT_FOUND`` or ``NO_SELECTION`` and helpful
            suggestions when the reference cannot be resolved.
    """
    project = ctx.project
    text = str(reference or "").strip()
    if not text:
        raise ToolError("INVALID_ARGUMENT", "A node id or name is required.")

    if text.lower() in SELECTION_ALIASES:
        selected = ctx.host.selected_node_ids()
        if not selected:
            raise ToolError(
                "NO_SELECTION",
                "Nothing is selected in the graph, so 'this' is ambiguous. "
                "Pass an explicit node id or name.",
            )
        node_id = selected[0]
        node = project.nodes.get(node_id)
        if node is None:
            raise ToolError("NODE_NOT_FOUND", f"Selected node '{node_id}' is gone.")
        return node_id, node

    if text in project.nodes:
        return text, project.nodes[text]

    lowered = text.lower()
    exact = [node_id for node_id, node in project.nodes.items() if node.name == text]
    if len(exact) == 1:
        return exact[0], project.nodes[exact[0]]
    if len(exact) > 1:
        raise ToolError(
            "AMBIGUOUS_NODE",
            f"{len(exact)} nodes are named '{text}': {', '.join(exact)}. "
            "Use a node id instead.",
        )

    ci = [
        node_id
        for node_id, node in project.nodes.items()
        if node.name.lower() == lowered
    ]
    if len(ci) == 1:
        return ci[0], project.nodes[ci[0]]

    partial = [
        node_id
        for node_id, node in project.nodes.items()
        if lowered in node.name.lower()
    ]
    if len(partial) == 1:
        return partial[0], project.nodes[partial[0]]

    names = [node.name for node in project.nodes.values()]
    raise ToolError(
        "NODE_NOT_FOUND",
        f"No node matches '{text}'."
        + (f" Did you mean: {', '.join(suggest(text, names))}?" if names else ""),
    )


def resolve_many(ctx: Any, references: list[str]) -> list[tuple[str, Any]]:
    """Resolve a list of references, preserving order and dropping duplicates."""
    resolved: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for reference in references:
        node_id, node = resolve_node(ctx, str(reference))
        if node_id in seen:
            continue
        seen.add(node_id)
        resolved.append((node_id, node))
    return resolved


def find_output(node: Any, name: str) -> Any | None:
    return node.outputs.get(name)


def find_input(node: Any, name: str) -> Any | None:
    return node.inputs.get(name)


def position_list(x: Any, y: Any) -> list[float]:
    return [float(x), float(y)]


def short_list(values: list[str], limit: int = 12) -> str:
    """Format a name list, eliding the middle when it is long."""
    if len(values) <= limit:
        return ", ".join(values)
    head = ", ".join(values[: limit - 3])
    return f"{head}, … (+{len(values) - (limit - 3)} more)"
