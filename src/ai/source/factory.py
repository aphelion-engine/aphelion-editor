"""Assembling the source subsystem from settings.

One function builds everything a run needs (index, retriever, sharing policy)
from the user's settings plus the locality of the *selected provider*. The
index is never built during editor startup: construction here only creates the
sandbox and tries to load the cache, and the tree is walked on the first
``source.*`` tool call.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ai.source.digest import architecture_digest
from ai.source.index import SourceIndex
from ai.source.limits import SourceBudget, SourceLimits
from ai.source.retrieval import SourceRetriever, default_cache_path
from ai.source.security import SECURITY_LOG, SourceSecurityLog
from ai.types import CloudSourceSharing, SourceAccess

#: Directories that identify an Aphelion checkout.
_CHECKOUT_MARKERS: tuple[tuple[str, ...], ...] = (
    ("src", "core", "nodes"),
    ("src", "core", "project.py"),
)

#: Core source areas an "core source only" access level may read.
CORE_PREFIXES: tuple[str, ...] = ("src/core", "src/ai", "src/ui", "src/app_io",
                                  "src/config", "src/effects", "src/utils",
                                  "src/plugins", "src/aphelion_sdk")


def detect_source_root() -> Path | None:
    """Find the repository root of a development checkout, if there is one.

    Walks up from this file, so a source checkout of the editor is found
    without the user configuring anything. A packaged build simply finds
    nothing, and source reads stay unavailable.
    """
    override = os.environ.get("APHELION_SOURCE_ROOT", "").strip()
    if override and Path(override).is_dir():
        return Path(override).resolve()
    start = Path(__file__).resolve()
    for parent in list(start.parents)[:8]:
        for marker in _CHECKOUT_MARKERS:
            if (parent.joinpath(*marker)).exists():
                return parent
    return None


@dataclass
class SourceContext:
    """Everything the ``source.*`` tools need for one agent run."""

    access: SourceAccess
    limits: SourceLimits
    retriever: SourceRetriever | None = None
    reason: str = ""
    cache_path: Path | None = None
    #: Set once the index has been built/refreshed for this run.
    _prepared: bool = field(default=False, repr=False)

    @property
    def enabled(self) -> bool:
        return self.retriever is not None

    def prepare(self) -> None:
        """Build or incrementally refresh the index, then persist it.

        Called on the first source tool call of a run. ``refresh`` only
        re-extracts files whose size or modification time changed, so the cost
        after the first time is a directory walk, not a re-parse.
        """
        if self.retriever is None or self._prepared:
            return
        self._prepared = True
        index = self.retriever.index
        if not index.available:
            return
        try:
            if index.built:
                index.refresh()
            else:
                index.build()
        except Exception:  # noqa: BLE001 - indexing must never fail a tool call
            return
        if self.cache_path is not None:
            index.save(self.cache_path)

    def digest(self) -> dict[str, Any]:
        """Registry-first architecture digest (always cheap)."""
        index = self.retriever.index if self.retriever is not None else None
        if index is not None and index.built:
            return architecture_digest(index)
        return architecture_digest(None)

    def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "access": self.access.value,
            "access_label": self.access.label,
            "enabled": self.enabled,
            "reason": self.reason,
        }
        if self.retriever is not None:
            payload["retriever"] = self.retriever.status()
        return payload


def build_source_context(
    settings: Any,
    *,
    provider_is_local: bool,
    consent: Callable[[], bool] | None = None,
    security_log: SourceSecurityLog | None = None,
    cache_path: Path | None = None,
    index_factory: Callable[[Path], SourceIndex] | None = None,
) -> SourceContext:
    """Build the source context described by ``settings``.

    Returns a disabled context (with a human-readable ``reason``) rather than
    raising, so an agent run never fails because source access is off or the
    checkout is missing.
    """
    access: SourceAccess = getattr(settings, "source_access", SourceAccess.OFF)
    limits: SourceLimits = getattr(settings, "source_limits", None) or SourceLimits()
    if access is SourceAccess.OFF:
        return SourceContext(
            access=access,
            limits=limits,
            reason=(
                "Source access is off. The live node registry and node "
                "documentation are still available."
            ),
        )

    configured = str(getattr(settings, "source_root", "") or "").strip()
    root = Path(configured).expanduser().resolve() if configured else detect_source_root()
    if root is None or not root.is_dir():
        return SourceContext(
            access=access,
            limits=limits,
            reason=(
                "No Aphelion source checkout was found. Set a source root in "
                "Preferences → AI to read implementation source; node metadata "
                "from the live registry remains available."
            ),
        )

    cache = cache_path or default_cache_path()
    index = _load_or_create_index(root, cache, index_factory)
    sharing: CloudSourceSharing = getattr(
        settings, "cloud_source_sharing", CloudSourceSharing.NEVER
    )
    retriever = SourceRetriever(
        index,
        access=access,
        provider_is_local=bool(provider_is_local),
        sharing=sharing,
        consent=consent,
        limits=limits,
        budget=SourceBudget(limits),
        security_log=security_log or SECURITY_LOG,
    )
    return SourceContext(
        access=access,
        limits=limits,
        retriever=retriever,
        cache_path=cache,
    )


def _load_or_create_index(
    root: Path,
    cache: Path,
    index_factory: Callable[[Path], SourceIndex] | None,
) -> SourceIndex:
    """Reuse the in-memory index for ``root``, else its cache, else build."""
    if index_factory is not None:
        return index_factory(root)
    return shared_index(root, cache)


#: Built contexts are per-run, but the parsed index for an unchanged root is
#: worth keeping between runs, so a conversation does not re-walk the tree.
_INDEX_CACHE: dict[str, SourceIndex] = {}
_INDEX_LOCK = threading.Lock()


def shared_index(root: Path, cache: Path) -> SourceIndex:
    """Return a process-wide index for ``root``, reused across runs."""
    key = f"{os.path.normcase(str(root))}|{os.path.normcase(str(cache))}"
    with _INDEX_LOCK:
        existing = _INDEX_CACHE.get(key)
        if existing is not None:
            return existing
        index = SourceIndex.load(cache, root=root) or SourceIndex(
            root, core_prefixes=CORE_PREFIXES
        )
        _INDEX_CACHE[key] = index
        return index


def reset_shared_indexes() -> None:
    """Drop cached indexes (used by tests and after a checkout move)."""
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


__all__ = [
    "CORE_PREFIXES",
    "SourceContext",
    "build_source_context",
    "detect_source_root",
    "reset_shared_indexes",
    "shared_index",
]
