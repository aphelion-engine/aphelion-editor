"""Aphelion project file format (``.aph``) — JSON document I/O."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.project import Project
from core.serialization import APH_FORMAT_ID, APH_FORMAT_VERSION

APH_EXTENSION: str = ".aph"
APH_FILE_FILTER: str = "Aphelion Project (*.aph);;All Files (*)"


class AphFormatError(ValueError):
    """Raised when a ``.aph`` document cannot be read or written."""


def save_aph(path: str | Path, project: Project) -> Path:
    """Serialize ``project`` to a ``.aph`` file.

    Parameters:
        path: Destination path (``.aph`` is appended when missing).
        project: Live project document.

    Returns:
        The resolved path that was written.

    Side effects:
        Writes UTF-8 JSON to disk and updates ``project.file_path``.

    Raises:
        AphFormatError: When the path cannot be written.
    """
    destination = Path(path)
    if destination.suffix.lower() != APH_EXTENSION:
        destination = destination.with_suffix(APH_EXTENSION)

    # Align identity with the destination before serializing so the file
    # and the live project agree on name / path.
    project.file_path = str(destination.resolve())
    if destination.stem:
        project.name = destination.stem

    document: dict[str, Any] = project.to_dict()
    document["format"] = APH_FORMAT_ID
    document["version"] = APH_FORMAT_VERSION

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise AphFormatError(f"Could not write project: {destination}") from exc

    return destination.resolve()


def load_aph(path: str | Path) -> Project:
    """Load a ``.aph`` project file into a new ``Project``.

    Parameters:
        path: Existing ``.aph`` file path.

    Returns:
        Reconstructed project with nodes, wires, and timeline state.

    Raises:
        AphFormatError: When the file is missing, invalid JSON, or unsupported.
    """
    source = Path(path)
    if not source.is_file():
        raise AphFormatError(f"Project file not found: {source}")

    try:
        raw = source.read_text(encoding="utf-8")
        document: Any = json.loads(raw)
    except OSError as exc:
        raise AphFormatError(f"Could not read project: {source}") from exc
    except json.JSONDecodeError as exc:
        raise AphFormatError(f"Invalid .aph JSON: {source}") from exc

    if not isinstance(document, dict):
        raise AphFormatError("Project root must be a JSON object")

    try:
        project = Project.from_dict(document)
    except ValueError as exc:
        raise AphFormatError(str(exc)) from exc

    project.file_path = str(source.resolve())
    if not project.name or project.name == "Untitled Project":
        project.name = source.stem
    return project
