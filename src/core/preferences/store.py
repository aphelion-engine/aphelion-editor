"""Persist and load application preferences.

Writes are atomic: the document is serialized to a sibling temporary file
and then swapped in with :func:`os.replace`. A crash or power loss during a
save therefore leaves the previous preferences intact instead of a
half-written file that would be discarded on next start.

Loading is always backwards compatible — see
:data:`core.preferences.models.PREFERENCES_VERSION`. When an older document
is migrated in memory it is written back immediately, so the upgrade is
durable even if the user never opens Preferences.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from config.constants import USERDATA_DIR_NAME
from config.keybinds import KeyAction, KeybindStore
from core.nodes.registry import global_node_registry
from core.preferences.models import PREFERENCES_VERSION, AppPreferences
from utils.logging_setup import get_logger
from utils.paths import app_data_path, ensure_directory

_LOG = get_logger("core.preferences.store")

PREFERENCES_FILENAME: str = "preferences.json"


class PreferencesStore:
    """JSON-backed preference document under ``userdata/``."""

    def __init__(self, *, path: Path | None = None) -> None:
        self._path: Path = path or app_data_path(USERDATA_DIR_NAME, PREFERENCES_FILENAME)
        self.preferences: AppPreferences = AppPreferences.defaults()
        #: Schema version found on disk (``0`` when there was no file).
        self.loaded_version: int = 0
        #: Whether :meth:`load` upgraded an older document in memory.
        self.migrated: bool = False

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppPreferences:
        """Load preferences from disk, falling back to defaults.

        A missing, unreadable, or malformed file yields factory defaults.
        Malformed files are moved aside rather than deleted, so the next
        save cannot silently destroy whatever the user had.
        """
        self.migrated = False
        self.loaded_version = 0

        if not self._path.is_file():
            self.preferences = AppPreferences.defaults()
            return self.preferences

        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._quarantine_corrupt_file(exc)
            self.preferences = AppPreferences.defaults()
            return self.preferences

        if not isinstance(raw, dict):
            self._quarantine_corrupt_file(ValueError(
                "preferences root is not an object"))
            self.preferences = AppPreferences.defaults()
            return self.preferences

        self.loaded_version = _read_version(raw)
        self.preferences = AppPreferences.from_dict(raw)
        self.migrated = self.loaded_version < PREFERENCES_VERSION

        if self.migrated:
            # Persist the upgrade now so the migration is not replayed on
            # every start, and so a later downgrade still finds v1 keys.
            _LOG.info(
                "Upgraded preferences schema v%s → v%s",
                self.loaded_version or 1,
                PREFERENCES_VERSION,
            )
            self.save()

        return self.preferences

    def save(self) -> None:
        """Write the in-memory preference document to disk atomically."""
        ensure_directory(self._path.parent)
        payload = self.preferences.to_dict()
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

        handle, temporary_name = tempfile.mkstemp(
            prefix=self._path.name + ".",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            # Never leave a stray temp file behind on failure.
            temporary.unlink(missing_ok=True)
            raise

        self.loaded_version = PREFERENCES_VERSION

    def _quarantine_corrupt_file(self, error: BaseException) -> None:
        """Move an unreadable preferences file aside for inspection."""
        quarantine = self._path.with_suffix(
            self._path.suffix + f".corrupt-{int(time.time())}"
        )
        try:
            os.replace(self._path, quarantine)
            _LOG.warning(
                "Preferences file unreadable (%s); moved to %s and using defaults",
                error,
                quarantine.name,
            )
        except OSError as exc:  # pragma: no cover - filesystem dependent
            _LOG.warning(
                "Could not quarantine unreadable preferences: %s", exc)

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


def _read_version(raw: dict[str, Any]) -> int:
    """Return the schema version recorded in ``raw`` (defaulting to 1)."""
    try:
        return int(raw.get("version", 1))
    except (TypeError, ValueError):
        return 1
