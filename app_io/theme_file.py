"""Load and save ``.aph.theme`` theme files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.theme_tokens import ThemeTokens

APH_THEME_FORMAT: str = "aphelion.theme"
APH_THEME_VERSION: int = 1
APH_THEME_FILTER: str = "Aphelion Theme (*.aph.theme)"


class ThemeFileError(Exception):
    """Raised when a theme file cannot be parsed."""


def save_theme_file(path: Path, tokens: ThemeTokens) -> None:
    """Write ``tokens`` to an ``.aph.theme`` file.

    Parameters:
        path: Destination file path.
        tokens: Theme tokens to serialize.

    Side effects:
        Creates parent directories and writes JSON to disk.
    """
    payload: dict[str, Any] = {
        "format": APH_THEME_FORMAT,
        "version": APH_THEME_VERSION,
        **tokens.to_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_theme_file(path: Path) -> ThemeTokens:
    """Load theme tokens from an ``.aph.theme`` file.

    Parameters:
        path: Source file path.

    Returns:
        Parsed theme tokens.

    Raises:
        ThemeFileError: When the file is missing or invalid.
    """
    if not path.is_file():
        raise ThemeFileError(f"Theme file not found: {path}")
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeFileError(f"Invalid theme file: {path}") from exc
    if not isinstance(raw, dict):
        raise ThemeFileError("Theme file must contain a JSON object")
    file_format = str(raw.get("format", ""))
    if file_format and file_format != APH_THEME_FORMAT:
        raise ThemeFileError(f"Unsupported theme format: {file_format}")
    tokens = ThemeTokens.from_dict(raw)
    tokens.theme_id = "custom"
    tokens.display_name = str(raw.get("display_name", path.stem))
    return tokens
