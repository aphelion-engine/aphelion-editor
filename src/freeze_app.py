"""cx_Freeze entry points for producing a standalone Aphelion executable."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from cx_Freeze import Executable, setup

from freeze_config import APP_NAME, DESCRIPTION, VERSION, create_exe_build_options
from utils.paths import ensure_directory, resource_path

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
BUILD_BASE_DIR: Final[Path] = _REPO_ROOT / "build"
DIST_DIR: Final[Path] = _REPO_ROOT / "dist"
_DEFAULT_ENTRY_SCRIPT: Final[str] = "main.py"
_DEFAULT_TARGET_NAME: Final[str] = "AphelionEditor"
_GUI_BASE: Final[str] = "gui"
_ICON_NAME: Final[str] = "icon.ico"


def create_executable(
    entry: str = _DEFAULT_ENTRY_SCRIPT,
    target_name: str = _DEFAULT_TARGET_NAME,
    base: str = _GUI_BASE,
) -> Executable:
    """Build a cx_Freeze executable descriptor for the GUI editor.

    Parameters:
        entry: Python script used as the frozen process entry point.
        target_name: Output executable stem. cx_Freeze appends ``.exe`` on Windows.
        base: cx_Freeze bootstrap. ``gui`` replaces the removed ``Win32GUI`` name.

    Returns:
        Configured ``Executable`` ready to pass to ``setup``.

    Raises:
        distutils.errors.DistutilsOptionError: If ``base`` is not a known bootstrap.

    Side effects:
        None.
    """
    icon_path: Path = resource_path(_ICON_NAME)
    return Executable(
        script=entry,
        target_name=target_name,
        base=base,
        icon=str(icon_path),
    )


def _resolve_freeze_directories(build_dir: str) -> tuple[Path, Path]:
    """Return ``(build_base, build_exe)`` directories that do not collide.

    cx_Freeze rejects a freeze when ``build_exe`` equals ``build_base``.
    Intermediates always live under ``build/``; the executable tree defaults
    to ``dist/``. If the caller asks for ``build`` as the exe dir, the trees
    are split into ``build/base`` and ``build/exe``.

    Parameters:
        build_dir: Requested frozen-output directory.

    Returns:
        Pair of existing directories ``(build_base, build_exe)``.

    Side effects:
        Creates both directories when they are missing.
    """
    output_dir: Path = Path(build_dir)
    base_dir: Path = BUILD_BASE_DIR
    if output_dir.resolve() == base_dir.resolve():
        base_dir = BUILD_BASE_DIR / "base"
        output_dir = BUILD_BASE_DIR / "exe"
    return ensure_directory(base_dir), ensure_directory(output_dir)


def build_standalone(build_dir: str | None = None) -> None:
    """Freeze Aphelion into a standalone executable via cx_Freeze.

    Parameters:
        build_dir: Directory that will receive the frozen tree (``build_exe``).
            Defaults to ``dist/``. Freeze intermediates go to ``build/``.

    Returns:
        None.

    Raises:
        distutils.errors.DistutilsOptionError: If the freeze configuration is invalid.

    Side effects:
        Creates freeze directories, temporarily rewrites ``sys.argv`` so
        cx_Freeze receives a ``build_exe`` command, and writes artifacts.
    """
    requested: str = str(DIST_DIR) if build_dir is None else build_dir
    base_dir: Path
    output_dir: Path
    base_dir, output_dir = _resolve_freeze_directories(requested)
    build_options: dict[str, object] = create_exe_build_options()
    original_argv: list[str] = sys.argv.copy()
    try:
        sys.argv = [original_argv[0], "build_exe"]
        setup(
            name=APP_NAME,
            version=VERSION,
            description=DESCRIPTION,
            packages=[],
            options={
                "build": {"build_base": str(base_dir)},
                "build_exe": {
                    **build_options,
                    "build_exe": str(output_dir),
                },
            },
            executables=[create_executable()],
        )
    finally:
        sys.argv = original_argv
