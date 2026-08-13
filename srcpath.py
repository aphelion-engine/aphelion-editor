"""Put the application source tree on ``sys.path`` during development.

Frozen executables already ship packages beside the interpreter; this module
is a no-op in that case.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent
SRC_ROOT: Final[Path] = REPO_ROOT / "src"
BUILD_BASE_DIR: Final[Path] = REPO_ROOT / "build"
DIST_DIR: Final[Path] = REPO_ROOT / "dist"


def ensure_src_on_path() -> Path:
    """Insert ``src/`` at the front of ``sys.path`` when running from source.

    Returns:
        Absolute path to the application source tree.

    Side effects:
        Mutates ``sys.path`` in unfrozen (development) runs.
    """
    if bool(getattr(sys, "frozen", False)):
        return SRC_ROOT
    src: str = str(SRC_ROOT)
    if src not in sys.path:
        sys.path.insert(0, src)
    return SRC_ROOT
