"""cx_Freeze metadata, include lists, and freeze options."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from installer_ui import msi_table_data

SRC_ROOT: Final[Path] = Path(__file__).resolve().parent
PLUGIN_SDK_ROOT: Final[Path] = SRC_ROOT.parent.parent / "aphelion-sdk"

APP_NAME: Final[str] = "Aphelion Editor"
VERSION: Final[str] = "0.1.0"
DESCRIPTION: Final[str] = (
    "Aphelion Editor - A modern, lightweight video editor for the modern age."
)

APP_PACKAGES: Final[list[str]] = [
    "aphelion_sdk",
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
    "imageio_ffmpeg",    # Aphelion runtime dependencies
    "soundfile",
    "librosa",
    "sounddevice",
]

INCLUDE_FILES: Final[list[tuple[str, str]]] = [
    ("resources/", "resources/"),
    ("userdata/", "userdata/"),
    ("plugins/", "plugins/"),
    ("logs/", "logs/"),
]

DEFAULT_EXCLUDES: Final[list[str]] = [
    "tkinter",
    "unittest",
    "tests",
]

# Stable upgrade GUID so newer MSIs replace older Aphelion Editor installs.
MSI_UPGRADE_CODE: Final[str] = "{412A43A8-9158-59E0-9642-D4918B488D95}"
MSI_SHORTCUT_DIR: Final[str] = "Aphelion"
MSI_OUTPUT_STEM: Final[str] = "AphelionEditor"
MSI_OUTPUT_NAME: Final[str] = f"{MSI_OUTPUT_STEM}Setup-{VERSION}-win64.msi"
MSI_USER_TARGET_DIR: Final[str] = r"[LocalAppDataFolder]Aphelion\Aphelion Editor"
MSI_MACHINE_TARGET_DIR: Final[str] = (
    r"[ProgramFiles64Folder]Aphelion\Aphelion Editor"
)
MSI_INITIAL_TARGET_DIR: Final[str] = MSI_USER_TARGET_DIR


def _module_finder_path() -> list[str]:
    """Return import paths for the freezer: ``src/`` and ``aphelion-sdk/`` first.

    Passing only ``src/`` hides site-packages, so ``include_package('cv2')``
    fails even when OpenCV is installed.

    Returns:
        Deduplicated module search path.

    Side effects:
        None.
    """
    ordered: list[str] = [str(SRC_ROOT), str(PLUGIN_SDK_ROOT)]
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
        "includes": ["aphelion_cli"],
        "excludes": excludes if excludes is not None else list(DEFAULT_EXCLUDES),
        "include_files": include_files if include_files is not None else list(INCLUDE_FILES),
        "optimize": optimize_level,
        "path": _module_finder_path(),
    }


def create_msi_options(
    *,
    dist_dir: Path,
    install_icon: Path,
) -> dict[str, object]:
    """Return cx_Freeze ``bdist_msi`` options for a Windows installer.

    Parameters:
        dist_dir: Directory that receives the ``.msi`` file.
        install_icon: Icon shown in Apps & Features during install.

    Returns:
        Mapping suitable for ``setup(options={"bdist_msi": ...})``.

    Side effects:
        None.
    """
    return {
        "upgrade_code": MSI_UPGRADE_CODE,
        "add_to_path": False,
        "all_users": False,
        "initial_target_dir": MSI_INITIAL_TARGET_DIR,
        "install_icon": str(install_icon),
        "dist_dir": str(dist_dir),
        "product_name": APP_NAME,
        "product_version": VERSION,
        "output_name": MSI_OUTPUT_NAME,
        "launch_on_finish": True,
        "summary_data": {
            "author": "youthx",
            "comments": DESCRIPTION,
            "keywords": "video,editor,aphelion",
        },
        "data": msi_table_data(
            product_name=APP_NAME,
            start_menu_dir=MSI_SHORTCUT_DIR,
            user_target_dir=MSI_USER_TARGET_DIR,
            machine_target_dir=MSI_MACHINE_TARGET_DIR,
        ),
    }
