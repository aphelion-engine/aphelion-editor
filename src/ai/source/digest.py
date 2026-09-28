"""The architecture digest: stable, cheap, high-level context.

A digest is a few hundred characters that tell the model what Aphelion *is*
(graph engine, node registry, tracking, rendering, media, audio, project
serialization, plugin SDK) plus the live shape of the registry. It is included
in every system prompt in place of dumping any repository content, and details
are retrieved on demand afterwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.source.index import SourceIndex
from ai.source.nodes import node_catalog

#: Human labels for the source areas that make up the engine. Matching is by
#: path substring, so it works for both ``src/core/...`` and ``core/...``.
_AREAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("graph engine", ("graph", "nodes/base", "node_graph")),
    ("node registry & catalog", ("nodes/registry", "nodes/catalog")),
    ("node implementations", ("core/nodes/",)),
    ("tracking subsystem", ("tracking",)),
    ("rendering & display", ("render", "viewport", "widgets/")),
    ("media decoding", ("media", "app_io")),
    ("audio", ("audio",)),
    ("project model & serialization", ("project", "serialization")),
    ("undo/redo history", ("history",)),
    ("plugins / SDK", ("plugins", "aphelion_sdk")),
    ("preferences", ("preferences",)),
    ("roto & masking", ("roto",)),
)


def architecture_digest(index: SourceIndex | None = None) -> dict[str, Any]:
    """Return the compact digest of Aphelion's architecture.

    Always available: the registry half needs no source checkout, so a packaged
    build still gets an accurate node vocabulary. The source half is added only
    when an index has been built.
    """
    catalog = node_catalog(root=index.root if index is not None else None)
    stats = catalog.stats()
    categories: dict[str, int] = {}
    for entry in catalog.entries().values():
        categories[entry.category] = categories.get(entry.category, 0) + 1

    digest: dict[str, Any] = {
        "application": "Aphelion",
        "summary": (
            "A node-graph video editor: media flows through typed node ports, "
            "the graph is edited as commands on a project model, and the UI "
            "updates from project observers. Tracking, effects, compositing, "
            "timeline/keyframes, audio, and a plugin SDK are all first-class."
        ),
        "registry": {
            "node_type_count": stats["node_count"],
            "categories": categories,
            "unresolved_types": stats["unresolved"][:10],
        },
        "principles": [
            "The live node registry is the authoritative source of node "
            "availability; source code only explains behaviour.",
            "Edits go through the editor's command system so undo always works.",
            "Ports are typed; connect only when types are compatible.",
        ],
    }

    if index is not None and index.available:
        digest["source"] = _source_half(index)
    return digest


def _source_half(index: SourceIndex) -> dict[str, Any]:
    """Summarise the indexed tree by concern, not by file list."""
    files = index.files()
    areas: dict[str, int] = {}
    for _label, needles in _AREAS:
        areas[_label] = sum(
            1
            for entry in files
            if any(needle in entry.path.lower() for needle in needles)
        )
    origins: dict[str, int] = {}
    for entry in files:
        origins[entry.origin] = origins.get(entry.origin, 0) + 1
    return {
        "root": str(index.root),
        "file_count": len(files),
        "symbol_count": sum(len(entry.symbols) for entry in files),
        "areas": {label: count for label, count in areas.items() if count},
        "origins": origins,
        "note": (
            "Area counts come from the file index. Read specific files with "
            "source.read_file / source.search rather than assuming behaviour."
        ),
    }


def digest_text(digest: dict[str, Any] | None = None) -> str:
    """Render a digest as compact text for a system prompt."""
    import json

    return json.dumps(digest or architecture_digest(), ensure_ascii=False, default=str)


__all__ = ["architecture_digest", "digest_text"]
