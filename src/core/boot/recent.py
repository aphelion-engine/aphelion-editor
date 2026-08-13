"""Persist and query recently opened ``.aph`` project paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.constants import USERDATA_DIR_NAME
from utils.paths import app_data_path, ensure_directory

RECENT_PROJECTS_FILENAME: str = "recent_projects.json"
DEFAULT_RECENT_LIMIT: int = 12


@dataclass(frozen=True, slots=True)
class RecentProjectEntry:
    """One remembered project path with last-opened metadata."""

    path: str
    name: str
    opened_at: str

    @property
    def exists(self) -> bool:
        """Return whether the project file is still on disk."""
        return Path(self.path).is_file()


class RecentProjectsStore:
    """JSON-backed recent-project list under the app data directory."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        limit: int = DEFAULT_RECENT_LIMIT,
    ) -> None:
        self._path: Path = path or app_data_path(USERDATA_DIR_NAME, RECENT_PROJECTS_FILENAME)
        self._limit: int = max(1, limit)

    def list_entries(self) -> list[RecentProjectEntry]:
        """Return recent entries newest-first (missing files kept, flagged)."""
        raw = self._read()
        entries: list[RecentProjectEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            name = str(item.get("name", "")).strip() or Path(path).stem
            opened_at = str(item.get("opened_at", ""))
            entries.append(
                RecentProjectEntry(path=path, name=name, opened_at=opened_at)
            )
        return entries

    def remember(self, project_path: str | Path, *, name: str | None = None) -> None:
        """Move ``project_path`` to the front of the recent list.

        Parameters:
            project_path: Absolute or relative ``.aph`` path.
            name: Display name; defaults to the file stem.

        Side effects:
            Writes the recent-projects JSON file.
        """
        resolved = str(Path(project_path).resolve())
        display = (name or Path(resolved).stem).strip() or "Untitled"
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        remaining = [
            item
            for item in self.list_entries()
            if Path(item.path).resolve().as_posix()
            != Path(resolved).resolve().as_posix()
        ]
        updated: list[RecentProjectEntry] = [
            RecentProjectEntry(path=resolved, name=display, opened_at=stamp),
            *remaining,
        ][: self._limit]
        self._write(updated)

    def remove(self, project_path: str | Path) -> None:
        """Drop a path from the recent list if present."""
        target = Path(project_path).resolve().as_posix()
        kept = [
            item
            for item in self.list_entries()
            if Path(item.path).resolve().as_posix() != target
        ]
        self._write(kept)

    def _read(self) -> list[Any]:
        if not self._path.is_file():
            return []
        try:
            data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, dict):
            items = data.get("projects", [])
            return items if isinstance(items, list) else []
        return data if isinstance(data, list) else []

    def _write(self, entries: list[RecentProjectEntry]) -> None:
        ensure_directory(self._path.parent)
        payload: dict[str, Any] = {
            "projects": [
                {
                    "path": entry.path,
                    "name": entry.name,
                    "opened_at": entry.opened_at,
                }
                for entry in entries
            ]
        }
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
