"""Global, cross-project storage for reusable custom node definitions.

Definitions live in ``userdata/custom_nodes.json`` so they survive project
changes and are available in every project. Loading the store registers each
definition with the global node registry under the ``Custom`` category, which
is what makes them appear in every Add Node menu and the node search palette.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config.constants import USERDATA_DIR_NAME
from core.nodes.custom_nodes import (CUSTOM_NODE_CATEGORY, CustomNode,
                                     CustomNodeDefinition,
                                     make_custom_node_class)
from core.nodes.registry import global_node_registry
from utils.paths import app_data_path, ensure_directory

if TYPE_CHECKING:
    from core.project import Project

CUSTOM_NODES_FILENAME: str = "custom_nodes.json"
CUSTOM_NODES_FORMAT_ID: str = "aphelion-custom-nodes"
CUSTOM_NODES_FORMAT_VERSION: int = 1


class CustomNodeStore:
    """JSON-backed library of reusable custom node definitions."""

    def __init__(self, *, path: Path | None = None) -> None:
        self._path: Path = path or app_data_path(
            USERDATA_DIR_NAME,
            CUSTOM_NODES_FILENAME,
        )
        self._definitions: dict[str, CustomNodeDefinition] = {}
        self._loaded: bool = False
        self._version: int = 0

    # -- accessors ---------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def version(self) -> int:
        """Bumped on every mutation; lets callers invalidate caches."""
        return self._version

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def definitions(self) -> list[CustomNodeDefinition]:
        """Return saved definitions sorted by name."""
        return [
            self._definitions[name].copy()
            for name in sorted(self._definitions)
        ]

    def names(self) -> list[str]:
        return sorted(self._definitions)

    def get(self, name: str) -> CustomNodeDefinition | None:
        definition = self._definitions.get(str(name))
        return None if definition is None else definition.copy()

    def has(self, name: str) -> bool:
        return str(name) in self._definitions

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        """Load definitions from disk and register them."""
        self._definitions = {}
        self._read_file()
        self._loaded = True
        self.register_all()

    def save(self) -> None:
        """Write definitions to disk."""
        ensure_directory(self._path.parent)
        document = {
            "format": CUSTOM_NODES_FORMAT_ID,
            "version": CUSTOM_NODES_FORMAT_VERSION,
            "definitions": [
                self._definitions[name].to_dict()
                for name in sorted(self._definitions)
            ],
        }
        self._path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _read_file(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        raw_defs = raw.get("definitions")
        if not isinstance(raw_defs, list):
            return
        for blob in raw_defs:
            definition = CustomNodeDefinition.from_dict(blob)
            if definition.is_empty():
                continue
            self._definitions[definition.name] = definition

    # -- mutation ----------------------------------------------------------

    def upsert(
        self,
        definition: CustomNodeDefinition,
        *,
        persist: bool = True,
    ) -> None:
        """Insert or replace ``definition`` (keyed by name) and register it."""
        name = definition.name.strip() or "Custom Node"
        if name != definition.name:
            definition = definition.copy()
            definition.name = name

        self._definitions[name] = definition.copy()
        self.register(name)
        self._version += 1
        if persist:
            self.save()

    def remove(self, name: str, *, persist: bool = True) -> bool:
        """Delete a definition, unregister it, and persist the result."""
        key = str(name)
        if key not in self._definitions:
            return False
        del self._definitions[key]
        self._unregister_class(key)
        self._version += 1
        if persist:
            self.save()
        return True

    # -- registration ------------------------------------------------------

    def register_all(self) -> None:
        """Register every loaded definition with the node registry."""
        for name in list(self._definitions):
            self.register(name)

    def register(self, name: str) -> None:
        definition = self._definitions.get(str(name))
        if definition is None:
            return
        node_class = make_custom_node_class(definition)
        global_node_registry.register(
            node_class,
            CUSTOM_NODE_CATEGORY,
            definition.name,
            definition.description
            or f"Reusable custom node: {definition.name}",
            definition.color,
        )

    def _unregister_class(self, name: str) -> None:
        global_node_registry.unregister(CUSTOM_NODE_CATEGORY, str(name))

    # -- project integration -----------------------------------------------

    def refresh_instances(
        self,
        project: Project,
        name: str,
        *,
        definition: CustomNodeDefinition | None = None,
    ) -> int:
        """Push an updated definition onto matching instances in ``project``.

        Returns:
            Number of instances updated.
        """
        key = str(name)
        target = definition if definition is not None else self._definitions.get(key)
        if target is None:
            return 0
        updated = 0
        for node_id, node in list(project.nodes.items()):
            if not isinstance(node, CustomNode):
                continue
            if node.definition_name != key:
                continue
            node.set_definition(target)
            project.invalidate_cache(node_id)
            updated += 1
        return updated

    def all_definitions(self) -> Iterable[CustomNodeDefinition]:
        return self.definitions()


#: Process-wide store used by the boot driver and the editor UI.
global_custom_node_store = CustomNodeStore()


__all__ = [
    "CUSTOM_NODES_FILENAME",
    "CUSTOM_NODES_FORMAT_ID",
    "CUSTOM_NODES_FORMAT_VERSION",
    "CustomNodeStore",
    "global_custom_node_store",
]
