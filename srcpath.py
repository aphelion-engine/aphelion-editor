"""Put the application source tree on ``sys.path`` during development.

Frozen executables already ship packages beside the interpreter; this module
is a no-op in that case.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent
ENGINE_ROOT: Final[Path] = REPO_ROOT.parent
SRC_ROOT: Final[Path] = REPO_ROOT / "src"
PLUGIN_SDK_ROOT: Final[Path] = ENGINE_ROOT / "aphelion-sdk"
BUILD_BASE_DIR: Final[Path] = REPO_ROOT / "build"
DIST_DIR: Final[Path] = REPO_ROOT / "dist"


def _prepend_sys_path(directory: Path) -> None:
    """Insert ``directory`` at the front of ``sys.path`` when it exists.

    Parameters:
        directory: Candidate import root.

    Side effects:
        Mutates ``sys.path`` in unfrozen runs when ``directory`` is a folder.
    """
    if bool(getattr(sys, "frozen", False)) or not directory.is_dir():
        return
    resolved: str = str(directory)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


def ensure_src_on_path() -> Path:
    """Insert ``src/`` and the sibling ``aphelion-sdk/`` onto ``sys.path``.

    Returns:
        Absolute path to the application source tree.

    Side effects:
        Mutates ``sys.path`` in unfrozen (development) runs.
    """
    _prepend_sys_path(PLUGIN_SDK_ROOT)
    _prepend_sys_path(SRC_ROOT)
    return SRC_ROOT
