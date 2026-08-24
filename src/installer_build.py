"""Build a Windows MSI installer for the frozen Aphelion Editor."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from cx_Freeze import setup

from freeze_app import BUILD_BASE_DIR, DIST_DIR, create_executable
from freeze_config import (
    APP_NAME,
    DESCRIPTION,
    INCLUDE_FILES,
    MSI_OUTPUT_NAME,
    MSI_SHORTCUT_DIR,
    VERSION,
    create_exe_build_options,
    create_msi_options,
)
from installer_patch import InstallerUiError, enhance_installer_ui
from sdk_release import EDITOR_RELEASES_DIR, ensure_sdk_release, installer_include_files
from utils.paths import ensure_directory, resource_path

_WINDOWS_PLATFORM: Final[str] = "win32"
_ICON_NAME: Final[str] = "icon.ico"


class InstallerBuildError(RuntimeError):
    """Raised when an MSI installer cannot be produced."""


def _require_windows() -> None:
    """Reject installer builds on non-Windows hosts.

    Raises:
        InstallerBuildError: When ``sys.platform`` is not Windows.
    """
    if sys.platform != _WINDOWS_PLATFORM:
        raise InstallerBuildError(
            "--build-installer produces a Windows MSI and can only run on Windows."
        )


def _msi_output_dir(build_dir: str | None) -> Path:
    """Return the directory that should receive the ``.msi`` file."""
    requested: str = str(EDITOR_RELEASES_DIR) if build_dir is None else build_dir
    return ensure_directory(Path(requested))


def build_installer(build_dir: str | None = None) -> Path:
    """Freeze Aphelion and package it as a Windows MSI.

    Freeze intermediates stay under ``build/``. The installer file is written
    to ``build_dir`` (default ``releases/``).

    Parameters:
        build_dir: Directory that receives the ``.msi``. Defaults to ``dist/``.

    Returns:
        Path to the built ``.msi`` installer.

    Raises:
        InstallerBuildError: When invoked on a non-Windows host, or when
            cx_Freeze finishes without writing the ``.msi``.
        distutils.errors.DistutilsOptionError: If the freeze configuration is invalid.

    Side effects:
        Creates output directories, temporarily rewrites ``sys.argv`` so
        cx_Freeze receives ``bdist_msi``, and writes freeze plus MSI artifacts.
    """
    _require_windows()
    msi_dir: Path = _msi_output_dir(build_dir)
    base_dir: Path = ensure_directory(BUILD_BASE_DIR)
    if msi_dir.resolve() == base_dir.resolve():
        msi_dir = ensure_directory(base_dir.parent / "dist")
    return _run_bdist_msi(base_dir, msi_dir)


def _run_bdist_msi(base_dir: Path, msi_dir: Path) -> Path:
    """Invoke cx_Freeze ``bdist_msi`` with Aphelion freeze and MSI options.

    Parameters:
        base_dir: cx_Freeze ``build_base`` for freeze intermediates.
        msi_dir: Directory that receives the ``.msi``.

    Returns:
        Path to the ``.msi`` after setup completes.

    Raises:
        InstallerBuildError: If the expected ``.msi`` file was not written, or
            the installer UI patch fails.

    Side effects:
        Runs cx_Freeze ``setup`` and restores ``sys.argv`` afterwards.
    """
    original_argv: list[str] = sys.argv.copy()
    try:
        sys.argv = [original_argv[0], "bdist_msi"]
        setup(
            name=APP_NAME,
            version=VERSION,
            description=DESCRIPTION,
            packages=[],
            options=_msi_setup_options(base_dir, msi_dir),
            executables=[
                create_executable(
                    shortcut_name=APP_NAME,
                    shortcut_dir=MSI_SHORTCUT_DIR,
                )
            ],
        )
    finally:
        sys.argv = original_argv
    msi_path: Path = _require_msi_file(msi_dir)
    try:
        enhance_installer_ui(msi_path)
    except InstallerUiError as exc:
        raise InstallerBuildError(str(exc)) from exc
    return msi_path


def _require_msi_file(msi_dir: Path) -> Path:
    """Return the built installer, or raise if cx_Freeze omitted the ``.msi``.

    Parameters:
        msi_dir: Directory that should contain ``MSI_OUTPUT_NAME``.

    Returns:
        Absolute path to the ``.msi``.

    Raises:
        InstallerBuildError: If the file is missing.

    Side effects:
        None.
    """
    msi_path: Path = (msi_dir / MSI_OUTPUT_NAME).resolve()
    if not msi_path.is_file():
        raise InstallerBuildError(
            f"Installer build finished without writing {msi_path}. "
            "cx_Freeze only produces a runnable installer when output_name "
            "ends with .msi."
        )
    return msi_path


def _msi_setup_options(base_dir: Path, msi_dir: Path) -> dict[str, object]:
    """Return cx_Freeze ``setup(options=...)`` for an MSI build."""
    extras: list[tuple[str, str]] = installer_include_files(ensure_sdk_release())
    build_options: dict[str, object] = create_exe_build_options(
        include_files=[*INCLUDE_FILES, *extras],
    )
    build_options["include_msvcr"] = True
    return {
        "build": {"build_base": str(base_dir)},
        "build_exe": build_options,
        "bdist_msi": create_msi_options(
            dist_dir=msi_dir,
            install_icon=resource_path(_ICON_NAME),
        ),
    }
