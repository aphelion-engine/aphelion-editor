"""Persist and load application preferences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.keybinds import KeyAction, KeybindStore
from core.nodes.registry import global_node_registry
from core.preferences.models import AppPreferences
from utils.paths import app_data_path, ensure_directory

PREFERENCES_FILENAME: str = "preferences.json"


class PreferencesStore:
    """JSON-backed preference document under ``userdata/``."""

    def __init__(self, *, path: Path | None = None) -> None:
        self._path: Path = path or app_data_path("userdata", PREFERENCES_FILENAME)
        self.preferences: AppPreferences = AppPreferences.defaults()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppPreferences:
        """Load preferences from disk, falling back to defaults."""
        if not self._path.is_file():
            self.preferences = AppPreferences.defaults()
            return self.preferences
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.preferences = AppPreferences.defaults()
            return self.preferences
        if not isinstance(raw, dict):
            self.preferences = AppPreferences.defaults()
            return self.preferences
        self.preferences = AppPreferences.from_dict(raw)
        return self.preferences

    def save(self) -> None:
        """Write the in-memory preference document to disk."""
        ensure_directory(self._path.parent)
        self._path.write_text(
            json.dumps(self.preferences.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def apply_keybinds(self, store: KeybindStore) -> None:
        """Hydrate a ``KeybindStore`` from persisted bindings."""
        for action in KeyAction:
            sequence = self.preferences.keybinds.get(action.value)
            if sequence:
                store.set_sequence(action, sequence)
        for slot_data in self.preferences.node_create_slots:
            slot_id = str(slot_data.get("slot_id", "")).strip()
            if not slot_id:
                continue
            sequence = str(slot_data.get("sequence", "")).strip()
            if sequence:
                store.set_node_create_sequence(slot_id, sequence)
            node_type = str(slot_data.get("node_type", "")).strip()
            node_category = str(slot_data.get("node_category", "")).strip()
            if node_type and node_category:
                store.set_node_create_target(slot_id, node_type, node_category)
            elif not node_type and not node_category:
                store.clear_node_create_target(slot_id)

    def capture_keybinds(self, store: KeybindStore) -> None:
        """Snapshot a ``KeybindStore`` into the preference document."""
        self.preferences.keybinds = {
            action.value: store.sequence(action) for action in KeyAction
        }
        self.preferences.node_create_slots = [
            {
                "slot_id": slot.slot_id,
                "sequence": slot.sequence,
                "node_type": slot.target.node_type,
                "node_category": slot.target.node_category,
            }
            for slot in store.node_create_slots()
        ]

    def apply_node_colors(self) -> None:
        """Push node-color overrides into the global registry."""
        overrides: dict[str, tuple[int, int, int]] = {}
        for key, rgb in self.preferences.node_colors.items():
            if len(rgb) >= 3:
                overrides[key] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        global_node_registry.set_color_overrides(overrides)

    def capture_node_colors_from_registry(self) -> None:
        """Persist current registry color overrides."""
        overrides = global_node_registry.color_overrides()
        self.preferences.node_colors = {
            key: [rgb[0], rgb[1], rgb[2]] for key, rgb in overrides.items()
        }
