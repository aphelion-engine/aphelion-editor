"""Read-only source intelligence for the Aphelion agent.

The assistant can understand Aphelion deeply without ever receiving the
repository wholesale:

    source tree -> index -> symbol/documentation index -> retrieval -> model

Modules are imported lazily by their callers, so a user who never enables
source access never pays for this package at all. Nothing in here writes to the
source tree, executes code, or makes a network request; the only file it may
write is its own index cache.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PathSandbox",
    "SourceBudget",
    "SourceContext",
    "SourceIndex",
    "SourceLimits",
    "SourceRetriever",
    "architecture_digest",
    "build_source_context",
    "detect_source_root",
    "node_catalog",
]


def __getattr__(name: str) -> Any:
    """Resolve public names from their modules on first use."""
    if name == "PathSandbox":
        from ai.source.security import PathSandbox

        return PathSandbox
    if name in {"SourceIndex"}:
        from ai.source.index import SourceIndex

        return SourceIndex
    if name in {"SourceBudget", "SourceLimits", "SourceRetriever"}:
        from ai.source import retrieval

        return getattr(retrieval, name)
    if name == "architecture_digest":
        from ai.source.digest import architecture_digest

        return architecture_digest
    if name == "node_catalog":
        from ai.source.nodes import node_catalog

        return node_catalog
    if name in {"SourceContext", "build_source_context", "detect_source_root"}:
        from ai.source import factory

        return getattr(factory, name)
    raise AttributeError(f"module 'ai.source' has no attribute {name!r}")
