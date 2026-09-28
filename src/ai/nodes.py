"""Always-on node awareness.

The assistant must know *every* node Aphelion has before it decides how to
build anything. Relying on a tool call for that is fragile: a model that does
not know a node exists cannot ask about it. So the whole registry vocabulary —
every node type, grouped by category — is cheap enough to place in the system
prompt on every run, and it is derived from the live registry rather than a
hand-maintained list, so it can never go stale or invent a node.

Ports and properties are heavier, so they are injected only for the node types
that the current request actually touches (plus whatever the model asks for
with ``node.describe_type``).

This works with source access switched off: it reads registry metadata only.
"""

from __future__ import annotations

from typing import Any

#: Rough character ceiling for the whole awareness block.
DEFAULT_MAX_CHARS: int = 7000
#: How many focused node types get full port/property detail.
DEFAULT_FOCUS: int = 12


def _catalog(catalog: Any | None) -> Any:
    if catalog is not None:
        return catalog
    from ai.source.nodes import node_catalog

    return node_catalog()


def category_lines(*, catalog: Any | None = None) -> list[str]:
    """One line per category: ``- Tracking (22): A, B, C``."""
    entries = _catalog(catalog).entries()
    grouped: dict[str, list[str]] = {}
    for entry in entries.values():
        grouped.setdefault(entry.category or "Uncategorised", []).append(entry.type)
    return [
        f"- {category} ({len(types)}): {', '.join(sorted(types))}"
        for category, types in sorted(grouped.items())
    ]


def _port_summary(ports: list[dict[str, Any]]) -> str:
    names = [str(port.get("name", "")) for port in ports if port.get("name")]
    if not names:
        return "none"
    return ", ".join(names[:8]) + ("…" if len(names) > 8 else "")


def describe_entry(entry: Any) -> str:
    """A compact one-line contract for one node type."""
    properties = [
        f"{prop.get('key')}({prop.get('type', '')})"
        for prop in entry.properties
        if prop.get("key")
    ]
    line = (
        f"- {entry.type} [{entry.category}]: {entry.description or 'no description'}\n"
        f"    inputs: {_port_summary(entry.inputs)} | outputs: {_port_summary(entry.outputs)}\n"
        f"    properties: {', '.join(properties[:14]) or 'none'}"
    )
    return line


def focused_lines(query: str, *, catalog: Any | None = None, limit: int = DEFAULT_FOCUS) -> list[str]:
    """Full contracts for the node types most relevant to ``query``."""
    if not (query or "").strip():
        return []
    hits = _catalog(catalog).search(query, limit=limit)
    return [describe_entry(entry) for entry in hits]


def node_awareness_prompt(
    *,
    query: str = "",
    catalog: Any | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    focus: int = DEFAULT_FOCUS,
) -> str:
    """The node-knowledge block injected into the system prompt.

    Always includes the complete node vocabulary; adds port/property detail for
    the node types nearest to ``query`` when the budget allows.
    """
    live = _catalog(catalog)
    entries = live.entries()
    categories = sorted({entry.category for entry in entries.values()})

    header = (
        f"Aphelion has {len(entries)} registered node types across "
        f"{len(categories)} categories. This list is complete and authoritative: "
        "if a type is not listed here it does not exist in this build. Use "
        "node.describe_type for exact ports, ranges and enum options before "
        "creating or configuring a node."
    )
    body = "\n".join(category_lines(catalog=live))
    block = f"{header}\n{body}"

    remaining = max_chars - len(block)
    if remaining > 400:
        detail = focused_lines(query, catalog=live, limit=focus)
        if detail:
            detail_block = (
                "\n\n## Node contracts relevant to this request\n"
                + "\n".join(detail)
            )
            if len(detail_block) > remaining:
                detail_block = detail_block[:remaining].rsplit("\n", 1)[0] + "\n(truncated)"
            block += detail_block
    return block


def node_index(*, catalog: Any | None = None) -> dict[str, str]:
    """``{type_name: category}`` for every registered node."""
    return {
        entry.type: entry.category
        for entry in _catalog(catalog).entries().values()
    }


def node_count(*, catalog: Any | None = None) -> int:
    return len(_catalog(catalog).entries())


__all__ = [
    "DEFAULT_FOCUS",
    "DEFAULT_MAX_CHARS",
    "category_lines",
    "describe_entry",
    "focused_lines",
    "node_awareness_prompt",
    "node_count",
    "node_index",
]
