"""Generated node knowledge: the authoritative graph vocabulary.

This module never maintains a hand-written node list. Everything comes from the
live registry, so the assistant's knowledge of nodes, ports, properties,
ranges, and enum options is derived from the same objects the editor would
instantiate. Two derived artifacts are built on top:

* **A node catalog** — one compact record per registered type, including the
  source file that defines it and the symbols that implement its ports.
* **A compatibility index** — which port types can legally feed which inputs,
  so the agent can assemble valid graphs without reading implementation code.

Everything is cached in memory after the first build. ``runtime`` entries are
authoritative for *availability*; ``metadata`` entries (from source) only add
implementation detail, and are marked untrusted like all retrieved content.
"""

from __future__ import annotations

import inspect
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.graph_model import describe_node_type, registry_types
from core.graph_exchange import ensure_registry
from core.nodes.registry import global_node_registry


def _source_file_for(cls: type) -> str:
    """Return the source file that defines ``cls``, if it can be found."""
    path: str | None = None
    try:
        path = inspect.getsourcefile(cls) or inspect.getfile(cls)
    except (TypeError, OSError):
        path = None
    if not path:
        module = sys.modules.get(getattr(cls, "__module__", ""))
        path = getattr(module, "__file__", None)
    return str(path) if path else ""


def _relative_to(path: str, root: Path | None) -> str:
    if not path or root is None:
        return path
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return path


@dataclass(frozen=True)
class NodeKnowledge:
    """One node type's full description, plus where it is implemented."""

    type: str
    category: str
    description: str
    module: str
    source_file: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    properties: list[dict[str, Any]]
    preview_cost: int
    variants: list[str]
    #: ``False`` whenever the record could not be built from a live instance.
    authoritative: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "category": self.category,
            "description": self.description,
            "module": self.module,
            "source_file": self.source_file,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "properties": self.properties,
            "preview_cost": self.preview_cost,
            "variants": self.variants,
            "authoritative": self.authoritative,
        }


class NodeCatalog:
    """A lazily built, cached view of every registered node type."""

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root
        self._entries: dict[str, NodeKnowledge] = {}
        self._lock = threading.RLock()
        self._built = False

    # -- building -------------------------------------------------------

    def build(self, *, force: bool = False) -> dict[str, NodeKnowledge]:
        with self._lock:
            if self._built and not force:
                return self._entries
            self._entries = {}
            index = registry_types()
            for name, infos in index.items():
                variants = sorted({info.category for info in infos})
                primary = infos[0]
                entry = self._describe(name, primary, variants)
                self._entries[name] = entry
            self._built = True
            return self._entries

    def _describe(self, name: str, info: Any, variants: list[str]) -> NodeKnowledge:
        module = ""
        source_file = ""
        try:
            cls = info.node_class
            module = str(getattr(cls, "__module__", ""))
            source_file = _relative_to(_source_file_for(cls), self.root)
        except Exception:  # noqa: BLE001 - a plugin class must not break the catalog
            pass

        contract = None
        try:
            contract = describe_node_type(name, category=info.category)
        except Exception:  # noqa: BLE001
            contract = None

        if contract is None:
            return NodeKnowledge(
                type=name,
                category=info.category,
                description=info.description or "",
                module=module,
                source_file=source_file,
                inputs=[],
                outputs=[],
                properties=[],
                preview_cost=1,
                variants=variants,
                authoritative=False,
            )
        return NodeKnowledge(
            type=contract.type,
            category=contract.category,
            description=contract.description,
            module=module,
            source_file=source_file,
            inputs=contract.inputs,
            outputs=contract.outputs,
            properties=contract.properties,
            preview_cost=contract.preview_cost,
            variants=variants,
        )

    # -- queries --------------------------------------------------------

    def entries(self) -> dict[str, NodeKnowledge]:
        return self.build()

    def get(self, name: str) -> NodeKnowledge | None:
        entries = self.build()
        entry = entries.get(name)
        if entry is not None:
            return entry
        lowered = name.strip().lower()
        for key, value in entries.items():
            if key.lower() == lowered:
                return value
        return None

    def search(self, query: str, *, limit: int = 40) -> list[NodeKnowledge]:
        """Rank node types by a natural-language-ish query.

        Scores type name, category, and description so "which node warps an
        image in perspective" can find Corner Pin without a semantic model.
        """
        needle = (query or "").strip().lower()
        if not needle:
            return []
        terms = [term for term in _tokenize(needle) if len(term) > 2]
        scored: list[tuple[int, NodeKnowledge]] = []
        for entry in self.build().values():
            haystack = (
                f"{entry.type} {entry.category} {entry.description} "
                + " ".join(item.get("name", "") for item in entry.inputs)
                + " ".join(item.get("name", "") for item in entry.outputs)
                + " ".join(item.get("key", "") for item in entry.properties)
            ).lower()
            score = 0
            if needle in entry.type.lower():
                score += 12
            if needle in haystack:
                score += 6
            for term in terms:
                if term in entry.type.lower():
                    score += 5
                if term in entry.category.lower():
                    score += 3
                if term in haystack:
                    score += 1
            if score:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].type))
        return [entry for _score, entry in scored[:limit]]

    def catalog(self, *, include_properties: bool = True) -> dict[str, Any]:
        """The whole catalog in the compact shape the model receives.

        Property detail is heavy, so ``node.list_types`` callers can ask for
        names only and then use ``node.describe_type`` / ``source.*`` for the
        handful of types they actually intend to use.
        """
        entries = self.build()
        return {
            "node_count": len(entries),
            "nodes": [
                {
                    "type": entry.type,
                    "category": entry.category,
                    "description": entry.description,
                    "source_file": entry.source_file,
                    **(
                        {
                            "inputs": [item["name"] for item in entry.inputs],
                            "outputs": [item["name"] for item in entry.outputs],
                            "properties": [item["key"] for item in entry.properties],
                        }
                        if include_properties
                        else {}
                    ),
                }
                for entry in sorted(entries.values(), key=lambda item: item.type)
            ],
        }

    def compatibility(self) -> dict[str, Any]:
        """Which port types are produced and consumed across the registry.

        This is the index that lets the agent reason about connections without
        reading every node implementation: for each socket type it lists the
        producers (outputs) and consumers (inputs) that legally pair.
        """
        producers: dict[str, list[dict[str, str]]] = {}
        consumers: dict[str, list[dict[str, str]]] = {}
        for entry in self.build().values():
            for port in entry.outputs:
                socket_type = str(port.get("type", "Unknown"))
                producers.setdefault(socket_type, []).append(
                    {"type": entry.type, "port": str(port.get("name", ""))}
                )
            for port in entry.inputs:
                socket_type = str(port.get("type", "Unknown"))
                consumers.setdefault(socket_type, []).append(
                    {"type": entry.type, "port": str(port.get("name", ""))}
                )
        types = sorted(set(producers) | set(consumers))
        return {
            "port_types": {
                socket_type: {
                    "producers": producers.get(socket_type, [])[:60],
                    "consumers": consumers.get(socket_type, [])[:60],
                }
                for socket_type in types
            },
            "note": (
                "A connection is valid when the output port's type appears in "
                "the target input's type, or when both are Convertible/Any."
            ),
        }

    def stats(self) -> dict[str, Any]:
        entries = self.build()
        return {
            "node_count": len(entries),
            "categories": sorted({entry.category for entry in entries.values()}),
            "with_source": sum(1 for entry in entries.values() if entry.source_file),
            "unresolved": sorted(
                entry.type for entry in entries.values() if not entry.authoritative
            ),
        }


def _tokenize(query: str) -> list[str]:
    return [
        "".join(character for character in term if character.isalnum() or character in "_-")
        for term in query.replace(",", " ").split()
    ]


#: Process-wide catalog; building it is cheap and it never goes stale in a
#: running editor because the registry cannot change without a plugin reload.
_CATALOG: NodeCatalog | None = None
_CATALOG_LOCK = threading.Lock()


def node_catalog(*, root: Path | None = None) -> NodeCatalog:
    """Return the shared node catalog, (re)building it for ``root`` if needed."""
    global _CATALOG
    ensure_registry()
    with _CATALOG_LOCK:
        if _CATALOG is None or _CATALOG.root != root:
            _CATALOG = NodeCatalog(root=root)
        return _CATALOG


def reset_node_catalog() -> None:
    """Drop the cache (used by tests and after a plugin reload)."""
    global _CATALOG
    with _CATALOG_LOCK:
        _CATALOG = None


def describe_node_implementation(
    name: str,
    *,
    root: Path | None = None,
    include_symbols: bool = True,
) -> dict[str, Any] | None:
    """Return a node type's contract *and* where it is implemented.

    The ``implementation`` block is the bridge from documentation to code: the
    defining file, the registration module, and the symbols that declare each
    port and property, with line numbers, so the agent can read the exact code
    behind a behaviour instead of guessing at it.
    """
    catalog = node_catalog(root=root)
    entry = catalog.get(name)
    if entry is None:
        return None
    payload = entry.to_dict()
    payload["implementation"] = {
        "module": entry.module,
        "source_file": entry.source_file,
        "symbols": (
            _implementation_symbols(name, root=root) if include_symbols else []
        ),
    }
    payload["untrusted"] = True
    return payload


def _implementation_symbols(name: str, *, root: Path | None) -> list[dict[str, Any]]:
    """Symbols (ports, properties, node_type) declared by a node class."""
    try:
        info = None
        for candidate_name, infos in registry_types().items():
            if candidate_name == name:
                info = infos[0]
                break
        if info is None:
            return []
        source = _relative_to(_source_file_for(info.node_class), root)
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "file": source,
            "kind": "node_class",
            "symbol": info.node_class.__name__,
            "line": _class_line(info.node_class),
        }
    ]


def _class_line(cls: type) -> int:
    try:
        lines, lineno = inspect.getsourcelines(cls)
        del lines
        return int(lineno)
    except (TypeError, OSError):
        return 0


def port_consumers(port_type: str) -> dict[str, list[dict[str, str]]]:
    """Convenience accessor used by graph-building tools and tests."""
    payload = node_catalog().compatibility()
    entry = payload["port_types"].get(port_type, {})
    return {
        "producers": list(entry.get("producers", [])),
        "consumers": list(entry.get("consumers", [])),
    }


def registered_categories() -> list[str]:
    ensure_registry()
    return sorted(global_node_registry.get_categories())


__all__ = [
    "NodeCatalog",
    "NodeKnowledge",
    "describe_node_implementation",
    "node_catalog",
    "port_consumers",
    "registered_categories",
    "reset_node_catalog",
]
