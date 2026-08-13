"""cx_Freeze metadata, include lists, and freeze options."""

from __future__ import annotations

import sys
from typing import Final

from srcpath import SRC_ROOT

APP_NAME: Final[str] = "Aphelion Editor"
VERSION: Final[str] = "0.1.0"
DESCRIPTION: Final[str] = (
    "Aphelion Editor - A modern, lightweight video editor for the modern age."
)

APP_PACKAGES: Final[list[str]] = [
    "app_io",
    "config",
    "core",
    "effects",
    "render",
    "timeline",
    "ui",
    "utils",
]

THIRD_PARTY_PACKAGES: Final[list[str]] = [
    "PyQt6",
    "numpy",
    "cv2",
    "imageio",
    "imageio_ffmpeg",
]

INCLUDE_FILES: Final[list[tuple[str, str]]] = [
    ("resources/", "resources/"),
    ("userdata/", "userdata/"),
    ("logs/", "logs/"),
]

DEFAULT_EXCLUDES: Final[list[str]] = [
    "tkinter",
    "unittest",
    "tests",
]


def _module_finder_path() -> list[str]:
    """Return import paths for the freezer: ``src/`` first, then ``sys.path``.

    Passing only ``src/`` hides site-packages, so ``include_package('cv2')``
    fails even when OpenCV is installed.

    Returns:
        Deduplicated module search path.

    Side effects:
        None.
    """
    ordered: list[str] = [str(SRC_ROOT)]
    for entry in sys.path:
        if entry != "" and entry not in ordered:
            ordered.append(entry)
    return ordered


def create_exe_build_options(
    excludes: list[str] | None = None,
    include_files: list[tuple[str, str]] | None = None,
    optimize_level: int = 2,
) -> dict[str, object]:
    """Return cx_Freeze ``build_exe`` options for a standalone editor freeze.

    Parameters:
        excludes: Optional module names to omit from the freeze.
        include_files: Optional ``(source, dest)`` pairs copied into the freeze.
        optimize_level: Bytecode optimization level passed to cx_Freeze.

    Returns:
        Mapping suitable for ``setup(options={"build_exe": ...})``.

    Side effects:
        None.
    """
    return {
        "packages": [*APP_PACKAGES, *THIRD_PARTY_PACKAGES],
        "excludes": excludes if excludes is not None else list(DEFAULT_EXCLUDES),
        "include_files": include_files if include_files is not None else list(INCLUDE_FILES),
        "optimize": optimize_level,
        "path": _module_finder_path(),
    }
