"""Resolve application, bundle, and resource paths in dev and frozen builds."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_RESOURCES_DIR_NAME: Final[str] = "resources"


def is_frozen() -> bool:
    """Return whether the interpreter is running a bundled executable.

    Returns:
        ``True`` when launched via PyInstaller, cx_Freeze, Nuitka, or similar.
    """
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Return the root directory for read-only bundled assets.

    Development resolves to the project root. Frozen builds resolve to
    ``sys._MEIPASS`` when present (PyInstaller one-file), otherwise the
    directory containing the executable (one-folder and other freezers).

    Returns:
        Absolute path to bundled asset root.

    Side effects:
        None.
    """
    if is_frozen():
        meipass: object = getattr(sys, "_MEIPASS", None)
        if meipass is not None:
            return Path(str(meipass))
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def app_root() -> Path:
    """Return the directory that anchors runtime-writable application data.

    Use for settings, caches, and logs that should live beside the executable
    when frozen, or beside the project when running from source.

    Returns:
        Absolute path to the application anchor directory.

    Side effects:
        None.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def resource_path(*relative_parts: str) -> Path:
    """Resolve a path under the bundled ``resources/`` directory.

    Parameters:
        relative_parts: Path segments relative to ``resources/``, e.g.
            ``resource_path("icon.ico")`` or ``resource_path("themes", "dark.qss")``.

    Returns:
        Absolute path to the requested resource file or directory.

    Side effects:
        None.
    """
    return bundle_root().joinpath(_RESOURCES_DIR_NAME, *relative_parts)


def app_data_path(*relative_parts: str) -> Path:
    """Resolve a path under a writable directory anchored at ``app_root()``.

    Parameters:
        relative_parts: Path segments relative to the app data root, e.g.
            ``app_data_path("cache", "thumbnails")``.

    Returns:
        Absolute path to the requested app data location.

    Side effects:
        None.
    """
    return app_root().joinpath(*relative_parts)


def ensure_directory(path: Path) -> Path:
    """Create ``path`` when missing and return it.

    Parameters:
        path: Directory to create.

    Returns:
        The same ``path`` after ensuring it exists.

    Side effects:
        Creates the directory and any missing parents.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
