"""Single-module build pipeline for Aphelion Editor.

Everything required to ship the editor lives in this one file:

* **config** — one :class:`BuildConfig` holding name, version, paths and
  MSI identity, so a release bump is a one-line edit.
* **freeze** — cx_Freeze ``build_exe`` options and the standalone build.
* **installer** — cx_Freeze ``bdist_msi`` options, the custom wizard
  tables (install scope, PATH, desktop shortcut, SDK install) and the
  post-build MSI layout patch.
* **fresh app data** — every artifact bundles a pristine ``userdata/`` and an
  empty ``logs/`` folder, so a build never ships the author's recent
  projects, saved custom nodes, preferences, plugins, or session logs. The
  built tree and the finished installer are both verified afterwards.
* **SDK bundling** — builds the sibling ``aphelion-sdk`` wheel so plugin
  authors can pip-install it straight from the installer.

Usage::

    python -m aphelion_build --exe          # frozen tree -> dist/
    python -m aphelion_build --installer    # Windows .msi -> releases/
    python -m aphelion_build --clean        # delete build artifacts
    aphelion --build-installer              # same, through the app CLI
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable

from config.constants import LOG_DIR_NAME, PLUGINS_DIR_NAME, USERDATA_DIR_NAME
from utils.paths import ensure_directory, resource_path

# ============================================================================
# Paths
# ============================================================================

SRC_ROOT: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = SRC_ROOT.parent
ENGINE_ROOT: Final[Path] = REPO_ROOT.parent

PLUGIN_SDK_ROOT: Final[Path] = ENGINE_ROOT / "aphelion-sdk"
BUILD_BASE_DIR: Final[Path] = REPO_ROOT / "build"
DIST_DIR: Final[Path] = REPO_ROOT / "dist"
EDITOR_RELEASES_DIR: Final[Path] = REPO_ROOT / "releases"
SDK_RELEASES_DIR: Final[Path] = PLUGIN_SDK_ROOT / "releases"

#: Scratch area for packaging inputs generated at release time. Holds the
#: pristine ``userdata/``/``logs/`` payload that every freeze bundles.
PACKAGING_STAGE_DIR: Final[Path] = BUILD_BASE_DIR / "_packaging"

#: Legacy frozen tree that used to live in the repository root. It is a build
#: artifact (its ``aphelion-host.json`` records absolute machine paths), so
#: ``--clean`` removes it like any other output.
LEGACY_FROZEN_TREE_DIR: Final[Path] = REPO_ROOT / "AphelionEditor"

_INSTALL_SDK_CMD: Final[Path] = REPO_ROOT / "installer" / "install_sdk.cmd"
_WINDOWS_PLATFORM: Final[str] = "win32"
_GUI_BASE: Final[str] = "gui"


# ============================================================================
# Config
# ============================================================================


@dataclass(frozen=True, slots=True)
class BuildConfig:
    """Release identity and packaging knobs for the build pipeline."""

    app_name: str = "Aphelion Editor"
    version: str = "0.1.0"
    description: str = (
        "Aphelion Editor - A modern, lightweight video editor for the modern age."
    )
    author: str = "youthx"
    keywords: str = "video,editor,aphelion"

    # Frozen executable
    entry_script: str = "main.py"
    target_name: str = "AphelionEditor"
    icon_name: str = "icon.ico"
    optimize: int = 2

    # MSI identity. The upgrade code is stable on purpose: newer builds
    # replace older installs instead of stacking side by side.
    upgrade_code: str = "{412A43A8-9158-59E0-9642-D4918B488D95}"
    msi_output_stem: str = "AphelionEditor"
    shortcut_dir: str = "Aphelion"
    user_target_dir: str = r"[LocalAppDataFolder]Aphelion\Aphelion Editor"
    machine_target_dir: str = r"[ProgramFiles64Folder]Aphelion\Aphelion Editor"

    #: Python packages that must be pulled into the freeze.
    app_packages: tuple[str, ...] = (
        "aphelion_sdk",
        "app_io",
        "config",
        "core",
        "effects",
        "render",
        "timeline",
        "ui",
        "utils",
    )

    #: Third-party packages that cx_Freeze cannot always infer.
    third_party_packages: tuple[str, ...] = (
        "PyQt6",
        "numpy",
        "cv2",
        "imageio",
        "imageio_ffmpeg",
        "soundfile",
        "librosa",
        "sounddevice",
    )

    #: ``(source, destination)`` pairs copied next to the frozen executable.
    #: ``userdata/`` and ``logs/`` are placeholders: :func:`freeze_include_files`
    #: swaps them for the pristine staged payload, so the working tree's own
    #: documents and session logs can never reach an artifact.
    include_files: tuple[tuple[str, str], ...] = (
        ("resources/", "resources/"),
        ("userdata/", "userdata/"),
        ("plugins/", "plugins/"),
        ("logs/", "logs/"),
    )

    #: Modules with no place in a shipped editor.
    excludes: tuple[str, ...] = ("tkinter", "unittest", "tests")

    @property
    def msi_output_name(self) -> str:
        """Return the versioned installer filename."""
        return f"{self.msi_output_stem}Setup-{self.version}-win64.msi"


CONFIG: Final[BuildConfig] = BuildConfig()

# Convenience aliases kept for callers that only need a single value.
APP_NAME: Final[str] = CONFIG.app_name
VERSION: Final[str] = CONFIG.version
DESCRIPTION: Final[str] = CONFIG.description
APP_PACKAGES: Final[list[str]] = list(CONFIG.app_packages)
THIRD_PARTY_PACKAGES: Final[list[str]] = list(CONFIG.third_party_packages)
#: Declarative source list. Prefer :func:`freeze_include_files` when building:
#: this raw list still points at the working tree's own ``userdata/``/``logs/``.
INCLUDE_FILES: Final[list[tuple[str, str]]] = list(CONFIG.include_files)
DEFAULT_EXCLUDES: Final[list[str]] = list(CONFIG.excludes)
MSI_UPGRADE_CODE: Final[str] = CONFIG.upgrade_code
MSI_OUTPUT_NAME: Final[str] = CONFIG.msi_output_name
MSI_SHORTCUT_DIR: Final[str] = CONFIG.shortcut_dir
MSI_USER_TARGET_DIR: Final[str] = CONFIG.user_target_dir
MSI_MACHINE_TARGET_DIR: Final[str] = CONFIG.machine_target_dir
MSI_INITIAL_TARGET_DIR: Final[str] = CONFIG.user_target_dir


# ============================================================================
# Errors
# ============================================================================


class BuildError(RuntimeError):
    """Raised when a packaging step cannot complete."""


class InstallerBuildError(BuildError):
    """Raised when an MSI installer cannot be produced."""


class InstallerUiError(BuildError):
    """Raised when the built MSI cannot be opened or patched."""


class SdkReleaseError(BuildError):
    """Raised when the SDK pip artifacts cannot be built."""


# ============================================================================
# Fresh application data
# ============================================================================
#
# ``userdata/`` holds whatever the person running the editor accumulated:
# recent project paths, saved custom-node definitions, and preferences. The
# companion ``logs/`` folder holds their session logs. Both live in the
# working tree during development, so freezing them "as found" shipped the
# author's own history to every user.
#
# A freeze therefore never copies the working-tree folders. Instead:
#
# 1. :func:`stage_fresh_userdata` writes a pristine payload to a scratch dir.
# 2. :func:`freeze_include_files` points ``include_files`` at that payload.
# 3. :func:`reset_tree_app_data` rewrites the folders in the built tree, and
#    :func:`verify_tree_app_data` / :func:`verify_msi_app_data` refuse to let
#    a build that still carries user documents pass as finished.

#: Runtime documents the editor owns under ``userdata/``. They are literals
#: rather than imports so packaging stays free of Qt/OpenCV; the test suite
#: asserts they still match ``core``'s constants.
PREFERENCES_FILENAME: Final[str] = "preferences.json"
RECENT_PROJECTS_FILENAME: Final[str] = "recent_projects.json"
CUSTOM_NODES_FILENAME: Final[str] = "custom_nodes.json"
CUSTOM_NODES_FORMAT_ID: Final[str] = "aphelion-custom-nodes"
CUSTOM_NODES_FORMAT_VERSION: Final[int] = 1

#: Marker written into every staged folder. Installers drop directories that
#: contain no files, and the editor recreates these folders at runtime, so a
#: marker keeps the shipped layout self-explanatory and non-empty.
_KEEP_FILE_NAME: Final[str] = "README.txt"

_USERDATA_README: Final[str] = (
    "Aphelion Editor application data\n"
    "===============================\n\n"
    "This folder holds your personal editor state and is created fresh on\n"
    "install:\n\n"
    "  preferences.json     editor, theme, performance, and audio settings\n"
    "  recent_projects.json projects you have opened recently\n"
    "  custom_nodes.json    reusable custom nodes you have saved\n"
    "  plugins/             drop-in SDK plugins (*.py) loaded at startup\n\n"
    "Deleting a file here resets that part of the editor to its defaults.\n"
)

_PLUGINS_README: Final[str] = (
    "Drop-in plugin folder\n"
    "=====================\n\n"
    "Place Aphelion SDK plugins (*.py) in this folder; they are imported at\n"
    "startup and their nodes appear alongside the built-in ones.\n"
)

_LOGS_README: Final[str] = (
    "Session logs\n"
    "============\n\n"
    "Aphelion writes aphelion.log here at runtime. The folder is emptied on\n"
    "install so a fresh build never ships someone else's session history.\n"
)


@dataclass(frozen=True, slots=True)
class StagedAppData:
    """Pristine ``userdata/`` and ``logs/`` folders ready for a freeze."""

    root: Path
    userdata: Path
    logs: Path


def default_preferences_document() -> dict[str, Any]:
    """Return the editor's factory-default preference document.

    The live model is imported when available so the shipped defaults can
    never drift from the ones the editor writes on first run. A minimal
    document is used when the application package is not importable.

    Returns:
        JSON-compatible mapping matching ``AppPreferences.defaults()``.
    """
    try:
        from core.preferences.models import AppPreferences
    except ImportError:
        return {"version": 1}
    return dict(AppPreferences.defaults().to_dict())


def fresh_userdata_documents() -> dict[str, dict[str, Any]]:
    """Return the pristine JSON documents a build ships in ``userdata/``.

    Returns:
        Mapping of filename to an empty/default document.
    """
    return {
        PREFERENCES_FILENAME: default_preferences_document(),
        RECENT_PROJECTS_FILENAME: {"projects": []},
        CUSTOM_NODES_FILENAME: {
            "format": CUSTOM_NODES_FORMAT_ID,
            "version": CUSTOM_NODES_FORMAT_VERSION,
            "definitions": [],
        },
    }


def _write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` with a trailing newline."""
    path.write_text(text, encoding="utf-8")


def _write_document(path: Path, document: dict[str, Any]) -> None:
    """Write ``document`` as indented JSON with a trailing newline."""
    _write_text(
        path,
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
    )


def _reset_directory(path: Path) -> Path:
    """Delete ``path`` when present and return it, empty and created."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    return ensure_directory(path)


def stage_fresh_userdata(stage_root: Path | None = None) -> StagedAppData:
    """Write a pristine ``userdata/`` + ``logs/`` payload for packaging.

    Parameters:
        stage_root: Directory that receives the staged folders. Defaults to
            ``build/_packaging``.

    Returns:
        The staged folders, ready to hand to ``include_files``.

    Side effects:
        Recreates the staged folders from scratch on every call, so a build
        can never pick up leftovers from an earlier run.
    """
    root: Path = ensure_directory(stage_root or PACKAGING_STAGE_DIR)
    userdata: Path = _reset_directory(root / USERDATA_DIR_NAME)
    logs: Path = _reset_directory(root / LOG_DIR_NAME)

    for filename, document in fresh_userdata_documents().items():
        _write_document(userdata / filename, document)

    plugins: Path = ensure_directory(userdata / PLUGINS_DIR_NAME)
    _write_text(userdata / _KEEP_FILE_NAME, _USERDATA_README)
    _write_text(plugins / _KEEP_FILE_NAME, _PLUGINS_README)
    _write_text(logs / _KEEP_FILE_NAME, _LOGS_README)
    return StagedAppData(root=root, userdata=userdata, logs=logs)


def freeze_include_files(*extra: tuple[str, str]) -> list[tuple[str, str]]:
    """Return ``include_files`` pairs that bundle pristine application data.

    The working tree's ``userdata/`` and ``logs/`` are replaced by the staged
    payload, so the freeze cannot inherit recent projects, saved custom
    nodes, preferences, user plugins, or session logs.

    Parameters:
        *extra: Additional ``(source, destination)`` pairs to append.

    Returns:
        Copy list for the ``build_exe`` options.
    """
    staged: StagedAppData = stage_fresh_userdata()
    replacements: dict[str, Path] = {
        USERDATA_DIR_NAME: staged.userdata,
        LOG_DIR_NAME: staged.logs,
    }
    pairs: list[tuple[str, str]] = []
    for source, destination in CONFIG.include_files:
        replacement: Path | None = replacements.get(destination.rstrip("/\\"))
        pairs.append((str(replacement) if replacement is not None else source, destination))
    pairs.extend(extra)
    return pairs


def _expected_userdata_entries() -> set[str]:
    """Return the names a pristine ``userdata/`` folder may contain."""
    return {*fresh_userdata_documents(), _KEEP_FILE_NAME, PLUGINS_DIR_NAME}


def _read_document(path: Path) -> Any:
    """Return the parsed JSON at ``path``, or ``None`` when unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _describe_stale_document(filename: str, document: Any) -> str:
    """Return a short, human-readable reason a document is not pristine."""
    if not isinstance(document, dict):
        return "unreadable or non-object contents"
    if filename == RECENT_PROJECTS_FILENAME:
        projects = document.get("projects")
        count = len(projects) if isinstance(projects, list) else "?"
        return f"{count} recent project(s)"
    if filename == CUSTOM_NODES_FILENAME:
        definitions = document.get("definitions")
        count = len(definitions) if isinstance(definitions, list) else "?"
        return f"{count} custom node definition(s)"
    return "non-default settings"


def reset_tree_app_data(tree_root: Path) -> list[Path]:
    """Rewrite ``userdata/``/``logs/`` inside a built tree as pristine copies.

    cx_Freeze never empties its output directory, so freezing into an existing
    ``dist/`` (or any reused tree) can otherwise keep documents from an
    earlier run.

    Parameters:
        tree_root: Frozen application tree.

    Returns:
        Folders that were rewritten.
    """
    staged: StagedAppData = stage_fresh_userdata()
    rewritten: list[Path] = []
    for name, source in (
        (USERDATA_DIR_NAME, staged.userdata),
        (LOG_DIR_NAME, staged.logs),
    ):
        target: Path = tree_root / name
        if not target.exists():
            continue
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target, dirs_exist_ok=True)
        rewritten.append(target)
    return rewritten


def verify_tree_app_data(tree_root: Path) -> None:
    """Fail when a built tree still carries user documents, plugins, or logs.

    Both the file *set* and the *contents* of the documents are checked, so a
    working-tree ``recent_projects.json`` cannot slip through just because its
    filename matches the pristine one.

    Parameters:
        tree_root: Frozen application tree.

    Raises:
        BuildError: If ``userdata/`` holds anything outside the pristine set,
            if a document is not the factory-default one, or if ``logs/``
            holds a real log file.
    """
    userdata: Path = tree_root / USERDATA_DIR_NAME
    if userdata.is_dir():
        allowed: set[str] = _expected_userdata_entries()
        unexpected: list[str] = sorted(
            entry.name for entry in userdata.iterdir() if entry.name not in allowed
        )
        if unexpected:
            raise BuildError(
                f"{userdata} still contains user data: {', '.join(unexpected)}. "
                "A build must ship a pristine userdata folder."
            )

        for filename, document in fresh_userdata_documents().items():
            path: Path = userdata / filename
            if not path.is_file():
                # Absent documents are fine: the editor writes defaults.
                continue
            actual: Any = _read_document(path)
            if actual != document:
                raise BuildError(
                    f"{path} is not the pristine document a build must ship "
                    f"({_describe_stale_document(filename, actual)}). "
                    "Rebuild so the freeze stages a fresh userdata folder."
                )

        plugins: Path = userdata / PLUGINS_DIR_NAME
        if plugins.is_dir():
            strays: list[str] = sorted(
                entry.name
                for entry in plugins.iterdir()
                if entry.name != _KEEP_FILE_NAME
            )
            if strays:
                raise BuildError(
                    f"{plugins} still contains user plugins: {', '.join(strays)}."
                )

    logs: Path = tree_root / LOG_DIR_NAME
    if logs.is_dir():
        leftovers: list[str] = sorted(
            entry.name for entry in logs.iterdir() if entry.name != _KEEP_FILE_NAME
        )
        if leftovers:
            raise BuildError(
                f"{logs} still contains log files: {', '.join(leftovers)}."
            )


def _require_icon() -> Path:
    """Return the packaged application icon, or raise if it is missing.

    Raises:
        BuildError: When ``resources/icon.ico`` is absent. Freezing without it
            fails deep inside cx_Freeze with an opaque error, so it is checked
            up front.
    """
    icon: Path = resource_path(CONFIG.icon_name)
    if not icon.is_file():
        raise BuildError(
            f"Missing packaging asset: {icon}. The application icon is "
            "required to freeze the executable and to stamp the installer."
        )
    return icon


# ============================================================================
# cx_Freeze options
# ============================================================================


def _module_finder_path() -> list[str]:
    """Return import paths for the freezer: ``src/`` and ``aphelion-sdk/`` first.

    Passing only ``src/`` hides site-packages, so ``include_package('cv2')``
    fails even when OpenCV is installed.

    Returns:
        Deduplicated module search path.
    """
    ordered: list[str] = [str(SRC_ROOT), str(PLUGIN_SDK_ROOT)]
    for entry in sys.path:
        if entry != "" and entry not in ordered:
            ordered.append(entry)
    return ordered


def create_exe_build_options(
    excludes: list[str] | None = None,
    include_files: list[tuple[str, str]] | None = None,
    optimize_level: int | None = None,
) -> dict[str, object]:
    """Return cx_Freeze ``build_exe`` options for a standalone editor freeze.

    Parameters:
        excludes: Optional module names to omit from the freeze.
        include_files: Optional ``(source, dest)`` pairs copied into the freeze.
            Defaults to :func:`freeze_include_files`, which bundles a pristine
            ``userdata/`` and an empty ``logs/`` folder instead of the working
            tree copies.
        optimize_level: Bytecode optimization level; defaults to the config.

    Returns:
        Mapping suitable for ``setup(options={"build_exe": ...})``.
    """
    return {
        "packages": [*APP_PACKAGES, *THIRD_PARTY_PACKAGES],
        "includes": ["aphelion_cli"],
        "excludes": excludes if excludes is not None else list(DEFAULT_EXCLUDES),
        "include_files": include_files if include_files is not None else freeze_include_files(),
        "optimize": CONFIG.optimize if optimize_level is None else optimize_level,
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
    """
    return {
        "upgrade_code": CONFIG.upgrade_code,
        "add_to_path": False,
        "all_users": False,
        "initial_target_dir": CONFIG.user_target_dir,
        "install_icon": str(install_icon),
        "dist_dir": str(dist_dir),
        "product_name": CONFIG.app_name,
        "product_version": CONFIG.version,
        "output_name": CONFIG.msi_output_name,
        "launch_on_finish": True,
        "summary_data": {
            "author": CONFIG.author,
            "comments": CONFIG.description,
            "keywords": CONFIG.keywords,
        },
        "data": msi_table_data(
            product_name=CONFIG.app_name,
            start_menu_dir=CONFIG.shortcut_dir,
            user_target_dir=CONFIG.user_target_dir,
            machine_target_dir=CONFIG.machine_target_dir,
        ),
    }


# ============================================================================
# MSI wizard tables
# ============================================================================
#
# cx_Freeze's generated wizard is minimal. These rows add an options page
# (install scope, PATH, desktop shortcut, SDK install), a usable folder
# browser, and registry keys that let the SDK find the editor.

OPTIONS_DIALOG: Final[str] = "OptionsDlg"
DIRECTORY_DIALOG: Final[str] = "SelectDirectoryDlg"
FEATURE_NAME: Final[str] = "default"
EXE_FILE_NAME: Final[str] = "AphelionEditor.exe"

COMPONENT_PATH_USER: Final[str] = "C_PathUser"
COMPONENT_PATH_MACHINE: Final[str] = "C_PathMachine"
COMPONENT_DESKTOP: Final[str] = "C_DesktopShortcut"
COMPONENT_LOCATION: Final[str] = "C_EditorLocation"

_GUID_PATH_USER: Final[str] = "{8F3C1A90-2B47-4E6D-9C18-A7D4E21B0F01}"
_GUID_PATH_MACHINE: Final[str] = "{8F3C1A90-2B47-4E6D-9C18-A7D4E21B0F02}"
_GUID_DESKTOP: Final[str] = "{8F3C1A90-2B47-4E6D-9C18-A7D4E21B0F03}"
_GUID_LOCATION: Final[str] = "{8F3C1A90-2B47-4E6D-9C18-A7D4E21B0F04}"

_VISIBLE_ENABLED: Final[int] = 3
_VISIBLE_ONLY: Final[int] = 1
_TEXT_TRANSPARENT: Final[int] = 196611
_DIALOG_MODAL: Final[int] = 3
_OPTIONAL_COMPONENT: Final[int] = 2
_REGISTRY_KEYPATH: Final[int] = 4
_SET_PROPERTY: Final[int] = 51
_RUN_CMD: Final[int] = 98
_INSTALL_SDK_SEQUENCE: Final[int] = 4100
_COMBO_ATTRIBUTES: Final[int] = 393219

MsiTableData = dict[str, list[tuple[object, ...]]]


def msi_table_data(
    *,
    product_name: str,
    start_menu_dir: str,
    user_target_dir: str,
    machine_target_dir: str,
) -> MsiTableData:
    """Return extra MSI tables for the Aphelion installer wizard.

    Parameters:
        product_name: Display name used in shortcut labels.
        start_menu_dir: Directory table id for the Start Menu folder.
        user_target_dir: Default TARGETDIR for a per-user install.
        machine_target_dir: Default TARGETDIR for an all-users install.

    Returns:
        Mapping of MSI table name to rows, merged for ``bdist_msi`` ``data``.
    """
    tables: MsiTableData = {}
    blocks: tuple[MsiTableData, ...] = (
        _directory_rows(start_menu_dir),
        _property_rows(),
        _options_dialog_rows(),
        _radio_rows(),
        _checkbox_rows(),
        _component_rows(),
        _registry_rows(),
        _shortcut_rows(product_name),
        _environment_rows(),
        _custom_action_rows(user_target_dir, machine_target_dir),
        _sequence_rows(),
        _directory_browser_rows(),
    )
    for block in blocks:
        _merge_tables(tables, block)
    return tables


def _merge_tables(target: MsiTableData, incoming: MsiTableData) -> None:
    """Append ``incoming`` rows onto ``target`` by table name."""
    for table_name, rows in incoming.items():
        target.setdefault(table_name, []).extend(rows)


def _directory_rows(start_menu_dir: str) -> MsiTableData:
    """Return Start Menu and Desktop directory entries."""
    return {
        "Directory": [
            ("ProgramMenuFolder", "TARGETDIR", "."),
            (start_menu_dir, "ProgramMenuFolder", "APHLI~1|Aphelion"),
            ("DesktopFolder", "TARGETDIR", "."),
        ]
    }


def _property_rows() -> MsiTableData:
    """Return default values for the options-page properties."""
    return {
        "Property": [
            ("INSTALLSCOPE", "PerUser"),
            ("ADDTOPATH", "1"),
            ("INSTALLDESKTOP", "1"),
            ("INSTALLSDK", "0"),
        ]
    }


def _options_dialog_rows() -> MsiTableData:
    """Return Dialog, Control, and ControlEvent rows for ``OptionsDlg``."""
    return {
        "Dialog": [
            (
                OPTIONS_DIALOG,
                50,
                50,
                370,
                322,
                _DIALOG_MODAL,
                "[ProductName] Setup",
                "InstallScope",
                "Next",
                "Cancel",
            )
        ],
        "Control": _options_controls(),
        "ControlEvent": _options_events(),
    }


def _options_controls() -> list[tuple[object, ...]]:
    """Return controls for the per-user / extras options page."""
    return [
        ("OptionsDlg", "Title", "Text", 15, 10, 340, 28, _TEXT_TRANSPARENT, None,
         r"{\VerdanaBold10}Installation options", "Description", None),
        ("OptionsDlg", "Description", "Text", 15, 40, 340, 24, _TEXT_TRANSPARENT, None,
         "Choose who can use Aphelion Editor and optional extras.", "InstallScope", None),
        ("OptionsDlg", "ScopeLabel", "Text", 15, 70, 340, 14, _TEXT_TRANSPARENT, None,
         "Install for:", "InstallScope", None),
        ("OptionsDlg", "InstallScope", "RadioButtonGroup", 20, 88, 330, 52, _VISIBLE_ENABLED,
         "INSTALLSCOPE", None, "AddToPath", None),
        ("OptionsDlg", "AddToPath", "CheckBox", 20, 150, 330, 18, _VISIBLE_ENABLED,
         "ADDTOPATH", "Add Aphelion Editor to the PATH", "InstallDesktop", None),
        ("OptionsDlg", "InstallDesktop", "CheckBox", 20, 172, 330, 18, _VISIBLE_ENABLED,
         "INSTALLDESKTOP", "Create a desktop shortcut", "InstallSdk", None),
        ("OptionsDlg", "InstallSdk", "CheckBox", 20, 194, 330, 18, _VISIBLE_ENABLED,
         "INSTALLSDK", "Install Aphelion SDK for plugin development (pip)", "Next", None),
        ("OptionsDlg", "BottomLine", "Line", 0, 286, 370, 0, 1, None, None, "Back", None),
        ("OptionsDlg", "Back", "PushButton", 180, 295, 56, 17, _VISIBLE_ONLY,
         None, "< Back", "Next", None),
        ("OptionsDlg", "Next", "PushButton", 236, 295, 56, 17, _VISIBLE_ENABLED,
         None, "Next >", "Cancel", None),
        ("OptionsDlg", "Cancel", "PushButton", 304, 295, 56, 17, _VISIBLE_ENABLED,
         None, "Cancel", "Back", None),
    ]


def _options_events() -> list[tuple[object, ...]]:
    """Return Next/Cancel actions and scope-dependent property updates."""
    return [
        (OPTIONS_DIALOG, "Cancel", "SpawnDialog", "CancelDlg", "1", 1),
        (OPTIONS_DIALOG, "Next", "DoAction", "CA_ALLUSERS_USER", 'INSTALLSCOPE="PerUser"', 1),
        (OPTIONS_DIALOG, "Next", "DoAction", "CA_PERUSER_ON", 'INSTALLSCOPE="PerUser"', 2),
        (OPTIONS_DIALOG, "Next", "DoAction", "CA_TARGET_USER", 'INSTALLSCOPE="PerUser"', 3),
        (OPTIONS_DIALOG, "Next", "DoAction", "CA_ALLUSERS_MACHINE", 'INSTALLSCOPE="PerMachine"', 4),
        (OPTIONS_DIALOG, "Next", "DoAction", "CA_PERUSER_OFF", 'INSTALLSCOPE="PerMachine"', 5),
        (OPTIONS_DIALOG, "Next", "DoAction", "CA_TARGET_MACHINE", 'INSTALLSCOPE="PerMachine"', 6),
        (OPTIONS_DIALOG, "Next", "EndDialog", "Return", "1", 7),
    ]


def _radio_rows() -> MsiTableData:
    """Return per-user / all-users radio buttons for INSTALLSCOPE."""
    return {
        "RadioButton": [
            ("INSTALLSCOPE", 1, "PerUser", 0, 0, 320, 20,
             "Only me (this user)", None),
            ("INSTALLSCOPE", 2, "PerMachine", 0, 24, 320, 24,
             "Anyone who uses this computer (requires administrator)", None),
        ]
    }


def _checkbox_rows() -> MsiTableData:
    """Return CheckBox values written when extras are ticked."""
    return {
        "CheckBox": [
            ("ADDTOPATH", "1"),
            ("INSTALLDESKTOP", "1"),
            ("INSTALLSDK", "1"),
        ]
    }


def _component_rows() -> MsiTableData:
    """Return optional PATH and desktop-shortcut components."""
    return {
        "Component": [
            (COMPONENT_PATH_USER, _GUID_PATH_USER, "TARGETDIR", _OPTIONAL_COMPONENT,
             'ADDTOPATH="1" AND NOT ALLUSERS=1', None),
            (COMPONENT_PATH_MACHINE, _GUID_PATH_MACHINE, "TARGETDIR", _OPTIONAL_COMPONENT,
             'ADDTOPATH="1" AND ALLUSERS=1', None),
            (COMPONENT_DESKTOP, _GUID_DESKTOP, "DesktopFolder", _OPTIONAL_COMPONENT,
             'INSTALLDESKTOP="1"', None),
            (COMPONENT_LOCATION, _GUID_LOCATION, "TARGETDIR", _REGISTRY_KEYPATH,
             None, "EditorInstallPath"),
        ],
        "FeatureComponents": [
            (FEATURE_NAME, COMPONENT_PATH_USER),
            (FEATURE_NAME, COMPONENT_PATH_MACHINE),
            (FEATURE_NAME, COMPONENT_DESKTOP),
            (FEATURE_NAME, COMPONENT_LOCATION),
        ],
    }


def _shortcut_rows(product_name: str) -> MsiTableData:
    """Return the optional desktop shortcut row."""
    return {
        "Shortcut": [
            (
                "S_DESKTOP",
                "DesktopFolder",
                product_name,
                COMPONENT_DESKTOP,
                f"[TARGETDIR]{EXE_FILE_NAME}",
                None,
                product_name,
                None,
                None,
                None,
                None,
                "TARGETDIR",
            )
        ]
    }


def _environment_rows() -> MsiTableData:
    """Return PATH mutations, scoped to user vs machine components."""
    path_value: str = "[~];[TARGETDIR]"
    return {
        "Environment": [
            ("E_PATH_USER", "=-Path", path_value, COMPONENT_PATH_USER),
            ("E_PATH_MACHINE", "=-*Path", path_value, COMPONENT_PATH_MACHINE),
        ]
    }


def _custom_action_rows(user_target_dir: str, machine_target_dir: str) -> MsiTableData:
    """Return type-51 actions that apply scope to ALLUSERS and TARGETDIR."""
    return {
        "CustomAction": [
            ("CA_ALLUSERS_USER", _SET_PROPERTY, "ALLUSERS", ""),
            ("CA_ALLUSERS_MACHINE", _SET_PROPERTY, "ALLUSERS", "1"),
            ("CA_PERUSER_ON", _SET_PROPERTY, "MSIINSTALLPERUSER", "1"),
            ("CA_PERUSER_OFF", _SET_PROPERTY, "MSIINSTALLPERUSER", ""),
            ("CA_TARGET_USER", _SET_PROPERTY, "TARGETDIR", user_target_dir),
            ("CA_TARGET_MACHINE", _SET_PROPERTY, "TARGETDIR", machine_target_dir),
            ("CA_INSTALL_SDK", _RUN_CMD, "TARGETDIR", "install_sdk.cmd"),
        ]
    }


def _registry_rows() -> MsiTableData:
    """Return registry rows that advertise this install to the SDK."""
    key: str = r"Software\Aphelion\Editor"
    return {
        "Registry": [
            ("EditorInstallPath", -1, key, "InstallPath", "[TARGETDIR]",
             COMPONENT_LOCATION),
            ("EditorExecutable", -1, key, "Executable",
             f"[TARGETDIR]{EXE_FILE_NAME}", COMPONENT_LOCATION),
            ("EditorVersion", -1, key, "Version", "[ProductVersion]",
             COMPONENT_LOCATION),
        ]
    }


def _sequence_rows() -> MsiTableData:
    """Show ``OptionsDlg`` in the UI and pip-install the SDK after files."""
    return {
        "InstallUISequence": [
            (OPTIONS_DIALOG, "not Installed", 1220),
        ],
        "InstallExecuteSequence": [
            (
                "CA_INSTALL_SDK",
                'INSTALLSDK="1" AND NOT REMOVE',
                _INSTALL_SDK_SEQUENCE,
            ),
        ],
    }


def _directory_browser_rows() -> MsiTableData:
    """Return labels, Back navigation, and combo event mapping."""
    return {
        "Control": [
            (DIRECTORY_DIALOG, "LookInLabel", "Text", 15, 36, 52, 16, _TEXT_TRANSPARENT,
             None, "Look in:", "DirectoryCombo", None),
            (DIRECTORY_DIALOG, "PathLabel", "Text", 15, 214, 52, 16, _TEXT_TRANSPARENT,
             None, "Folder:", "PathEdit", None),
        ],
        "ControlEvent": [
            (DIRECTORY_DIALOG, "Back", "NewDialog", OPTIONS_DIALOG, "1", 1),
        ],
        "EventMapping": [
            (DIRECTORY_DIALOG, "DirectoryCombo", "IgnoreChange", "IgnoreChange"),
            (DIRECTORY_DIALOG, "DirectoryList", "IgnoreChange", "IgnoreChange"),
            (DIRECTORY_DIALOG, "PathEdit", "IgnoreChange", "IgnoreChange"),
        ],
    }


# ============================================================================
# MSI post-build patch
# ============================================================================
#
# cx_Freeze draws ``DirectoryCombo`` 80px tall on top of ``DirectoryList``.
# Repositioning those controls into a standard Look-in / folder-tree / path
# stack makes the folder page usable and lets Back reach the options page.


def enhance_installer_ui(msi_path: Path) -> None:
    """Rewrite the destination dialog layout on ``msi_path``.

    Parameters:
        msi_path: Existing ``.msi`` produced by cx_Freeze ``bdist_msi``.

    Raises:
        InstallerUiError: If ``msilib`` cannot open or commit the database.
    """
    try:
        from msilib import MSIDBOPEN_TRANSACT, OpenDatabase
    except ImportError as exc:
        raise InstallerUiError(
            "python-msilib is required to finish the installer UI."
        ) from exc
    database = OpenDatabase(str(msi_path), MSIDBOPEN_TRANSACT)
    try:
        _apply_directory_layout(database)
        _enable_directory_back_button(database)
        _widen_secure_properties(database)
        database.Commit()
    except Exception as exc:
        raise InstallerUiError(f"Failed to enhance installer UI: {exc}") from exc


def _apply_directory_layout(database: object) -> None:
    """Reposition the folder browser into a Look-in / list / path stack."""
    updates: tuple[str, ...] = (
        _control_update("Title", y=8, height=22),
        _control_update("LookInLabel", x=15, y=36, width=52, height=16),
        _control_update(
            "DirectoryCombo",
            x=70,
            y=34,
            width=230,
            height=19,
            attributes=_COMBO_ATTRIBUTES,
        ),
        _control_update("Up", x=306, y=34, width=24, height=19),
        _control_update("NewDir", x=334, y=34, width=28, height=19),
        _control_update("DirectoryList", x=15, y=58, width=340, height=148),
        _control_update("PathLabel", x=15, y=214, width=52, height=16),
        _control_update("PathEdit", x=15, y=230, width=340, height=16),
    )
    for sql in updates:
        _execute(database, sql)
    _execute(
        database,
        "UPDATE `Control` SET `Text`='{\\VerdanaBold10}Choose Install Location' "
        f"WHERE `Dialog_`='{DIRECTORY_DIALOG}' AND `Control`='Title'",
    )


def _enable_directory_back_button(database: object) -> None:
    """Make Back visible+enabled so it can return to the options page."""
    _execute(
        database,
        "UPDATE `Control` SET `Attributes`=3 "
        f"WHERE `Dialog_`='{DIRECTORY_DIALOG}' AND `Control`='Back'",
    )


def _widen_secure_properties(database: object) -> None:
    """Allow the options-page properties through the secure-property list."""
    _execute(
        database,
        "UPDATE `Property` SET `Value`="
        "'TARGETDIR;REINSTALLMODE;INSTALLSCOPE;ADDTOPATH;INSTALLDESKTOP;INSTALLSDK' "
        "WHERE `Property`='SecureCustomProperties'",
    )


def _control_update(
    control: str,
    *,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
    attributes: int | None = None,
) -> str:
    """Return an UPDATE statement for one destination-dialog control."""
    assignments: list[str] = []
    if x is not None:
        assignments.append(f"`X`={x}")
    if y is not None:
        assignments.append(f"`Y`={y}")
    if width is not None:
        assignments.append(f"`Width`={width}")
    if height is not None:
        assignments.append(f"`Height`={height}")
    if attributes is not None:
        assignments.append(f"`Attributes`={attributes}")
    set_clause: str = ", ".join(assignments)
    return (
        f"UPDATE `Control` SET {set_clause} "
        f"WHERE `Dialog_`='{DIRECTORY_DIALOG}' AND `Control`='{control}'"
    )


def _execute(database: object, sql: str) -> None:
    """Run one MSI SQL statement and close the view."""
    view = getattr(database, "OpenView")(sql)
    view.Execute(None)
    view.Close()


# ============================================================================
# MSI payload verification
# ============================================================================
#
# Staging pristine documents is what keeps user data out of an installer; this
# check proves the file *set* afterwards. cx_Freeze stores names as
# ``SHORT|long`` and links every file to a directory through the Component
# table, so the install-relative path of each bundled file can be rebuilt from
# the MSI tables alone — no need to unpack the cabinet.
#
# Filenames cannot prove a JSON document's contents (the pristine
# ``recent_projects.json`` legitimately exists, just empty), so document
# contents are verified in the frozen tree the MSI is authored from, via
# :func:`verify_tree_app_data`. This check catches what names *can* prove:
# stray user files, user plugins, ``__pycache__``, and session logs.


def _msi_long_name(value: str) -> str:
    """Return the long half of an MSI ``FileName``/``DefaultDir`` value."""
    return value.rsplit("|", 1)[-1]


def _msi_rows(database: object, sql: str, columns: int) -> list[tuple[str, ...]]:
    """Run ``sql`` and return every row as strings.

    Parameters:
        database: Open ``msilib`` database handle.
        sql: Query selecting ``columns`` textual columns.
        columns: Number of columns to read from each record.

    Returns:
        Rows in fetch order.
    """
    view = getattr(database, "OpenView")(sql)
    view.Execute(None)
    rows: list[tuple[str, ...]] = []
    try:
        while True:
            record = view.Fetch()
            if record is None:
                break
            rows.append(
                tuple(
                    str(record.GetString(index)) for index in range(1, columns + 1)
                )
            )
    finally:
        view.Close()
    return rows


def _msi_directory_paths(database: object) -> dict[str, str]:
    """Return the install-relative path of every MSI ``Directory`` row."""
    parents: dict[str, tuple[str, str]] = {
        directory: (parent, _msi_long_name(default_dir))
        for directory, parent, default_dir in _msi_rows(
            database,
            "SELECT `Directory`, `Directory_Parent`, `DefaultDir` FROM `Directory`",
            3,
        )
    }
    cache: dict[str, str] = {}

    def resolve(directory: str, depth: int = 0) -> str:
        if directory in cache:
            return cache[directory]
        if depth > 32 or directory not in parents:
            return ""
        parent, segment = parents[directory]
        if not parent or parent == directory:
            cache[directory] = ""
        else:
            prefix: str = resolve(parent, depth + 1)
            cache[directory] = f"{prefix}/{segment}" if prefix else segment
        return cache[directory]

    for directory in parents:
        resolve(directory)
    return cache


def _msi_file_paths(database: object) -> list[str]:
    """Return the install-relative path of every file the MSI lays down."""
    directories: dict[str, str] = _msi_directory_paths(database)
    components: dict[str, str] = {
        component: directory
        for component, directory in _msi_rows(
            database, "SELECT `Component`, `Directory_` FROM `Component`", 2
        )
    }
    paths: list[str] = []
    for _key, component, file_name in _msi_rows(
        database, "SELECT `File`, `Component_`, `FileName` FROM `File`", 3
    ):
        directory: str = directories.get(components.get(component, ""), "")
        name: str = _msi_long_name(file_name)
        paths.append(f"{directory}/{name}" if directory else name)
    return paths


def _expected_userdata_paths() -> set[str]:
    """Return the install-relative ``userdata/`` paths a pristine build may hold."""
    entries: set[str] = {*fresh_userdata_documents(), _KEEP_FILE_NAME}
    entries.add(f"{PLUGINS_DIR_NAME}/{_KEEP_FILE_NAME}")
    return entries


def unexpected_app_data_paths(paths: Iterable[str]) -> list[str]:
    """Return bundled paths that would carry user data into an install.

    Only names are inspected, so this catches stray documents, user plugins,
    bytecode caches, and session logs — not the contents of a document that
    happens to share a pristine filename.

    Parameters:
        paths: Install-relative paths of every file an artifact lays down.

    Returns:
        Sorted offending paths.
    """
    userdata_prefix: str = f"{USERDATA_DIR_NAME}/"
    logs_prefix: str = f"{LOG_DIR_NAME}/"
    allowed: set[str] = _expected_userdata_paths()
    offenders: list[str] = []
    for path in paths:
        if path.startswith(userdata_prefix):
            if path[len(userdata_prefix):] not in allowed:
                offenders.append(path)
        elif path.startswith(logs_prefix):
            if path[len(logs_prefix):] != _KEEP_FILE_NAME:
                offenders.append(path)
    return sorted(set(offenders))


def verify_msi_app_data(msi_path: Path) -> int:
    """Fail when an installer would lay down stray user data or logs.

    Parameters:
        msi_path: Installer produced by cx_Freeze ``bdist_msi``.

    Returns:
        Number of bundled files that were inspected.

    Raises:
        InstallerUiError: If the MSI cannot be opened for reading.
        InstallerBuildError: If stray user data survived into the installer.
    """
    try:
        from msilib import MSIDBOPEN_READONLY, OpenDatabase
    except ImportError as exc:
        raise InstallerUiError(
            "python-msilib is required to verify the installer payload."
        ) from exc

    try:
        database = OpenDatabase(str(msi_path), MSIDBOPEN_READONLY)
        paths: list[str] = _msi_file_paths(database)
    except Exception as exc:
        raise InstallerUiError(f"Failed to read {msi_path}: {exc}") from exc

    offenders: list[str] = unexpected_app_data_paths(paths)
    if offenders:
        raise InstallerBuildError(
            "Installer would ship personal application data: "
            + ", ".join(offenders)
            + ". Rebuild so the freeze bundles a pristine userdata folder."
        )
    return len(paths)


# ============================================================================
# Plugin SDK wheel
# ============================================================================


def ensure_sdk_release() -> Path:
    """Build wheel and sdist into ``aphelion-sdk/releases`` and return the wheel.

    Returns:
        Path to ``aphelion_sdk-*-py3-none-any.whl``.

    Raises:
        SdkReleaseError: If the build produces no wheel.
    """
    ensure_directory(SDK_RELEASES_DIR)
    _run_sdk_build(SDK_RELEASES_DIR)
    wheel: Path | None = _latest_wheel(SDK_RELEASES_DIR)
    if wheel is None:
        raise SdkReleaseError(f"SDK build produced no wheel in {SDK_RELEASES_DIR}")
    return wheel


def installer_include_files(wheel: Path) -> list[tuple[str, str]]:
    """Return extra freeze include pairs for the SDK wheel and pip helper."""
    files: list[tuple[str, str]] = [(str(wheel.resolve()), f"sdk/{wheel.name}")]
    if _INSTALL_SDK_CMD.is_file():
        files.append((str(_INSTALL_SDK_CMD.resolve()), "install_sdk.cmd"))
    else:
        print(
            f"warning: {_INSTALL_SDK_CMD} is missing; this installer will not "
            "bundle the SDK pip helper.",
            file=sys.stderr,
        )
    return files


def _latest_wheel(directory: Path) -> Path | None:
    """Return the newest ``aphelion_sdk-*.whl`` in ``directory``."""
    wheels: list[Path] = sorted(directory.glob("aphelion_sdk-*.whl"))
    if not wheels:
        return None
    return wheels[-1]


def _run_sdk_build(output_dir: Path) -> None:
    """Run ``python -m build`` and fall back to ``pip wheel``."""
    build_cmd: list[str] = [
        sys.executable,
        "-m",
        "build",
        "--outdir",
        str(output_dir),
        str(PLUGIN_SDK_ROOT),
    ]
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        build_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0:
        return
    _run_pip_wheel(output_dir, completed.stderr)


def _run_pip_wheel(output_dir: Path, build_stderr: str) -> None:
    """Build a wheel with pip when the ``build`` frontend is missing."""
    command: list[str] = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(output_dir),
        str(PLUGIN_SDK_ROOT),
    ]
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail: str = completed.stderr.strip() or build_stderr.strip()
        raise SdkReleaseError(f"Failed to build aphelion-sdk:\n{detail}")


# ============================================================================
# Freeze
# ============================================================================


def create_executable(
    entry: str | None = None,
    target_name: str | None = None,
    base: str = _GUI_BASE,
    *,
    shortcut_name: str | None = None,
    shortcut_dir: str | None = None,
) -> object:
    """Build a cx_Freeze executable descriptor for the GUI editor.

    Parameters:
        entry: Python script used as the frozen process entry point.
        target_name: Output executable stem. cx_Freeze appends ``.exe``.
        base: cx_Freeze bootstrap. ``gui`` replaces the old ``Win32GUI`` name.
        shortcut_name: Optional Start Menu shortcut label (MSI builds).
        shortcut_dir: Optional Start Menu folder id matching the Directory table.

    Returns:
        Configured ``Executable`` ready to pass to ``setup``.
    """
    from cx_Freeze import Executable

    icon_path: Path = _require_icon()
    options: dict[str, object] = {
        "script": entry or CONFIG.entry_script,
        "target_name": target_name or CONFIG.target_name,
        "base": base,
        "icon": str(icon_path),
    }
    if shortcut_name is not None and shortcut_dir is not None:
        options["shortcut_name"] = shortcut_name
        options["shortcut_dir"] = shortcut_dir
    return Executable(**options)  # type: ignore[arg-type]


def _resolve_freeze_directories(build_dir: str) -> tuple[Path, Path]:
    """Return ``(build_base, build_exe)`` directories that do not collide.

    cx_Freeze rejects a freeze when ``build_exe`` equals ``build_base``.
    Intermediates always live under ``build/``; the executable tree defaults
    to ``dist/``. If the caller asks for ``build`` as the exe dir, the trees
    are split into ``build/base`` and ``build/exe``.
    """
    output_dir: Path = Path(build_dir)
    base_dir: Path = BUILD_BASE_DIR
    if output_dir.resolve() == base_dir.resolve():
        base_dir = BUILD_BASE_DIR / "base"
        output_dir = BUILD_BASE_DIR / "exe"
    return ensure_directory(base_dir), ensure_directory(output_dir)


def build_standalone(build_dir: str | None = None) -> Path:
    """Freeze Aphelion into a standalone executable via cx_Freeze.

    Parameters:
        build_dir: Directory that receives the frozen tree (``build_exe``).
            Defaults to ``dist/``. Freeze intermediates go to ``build/``.

    Returns:
        Directory containing the frozen executable.
    """
    from cx_Freeze import setup

    requested: str = str(DIST_DIR) if build_dir is None else build_dir
    base_dir: Path
    output_dir: Path
    base_dir, output_dir = _resolve_freeze_directories(requested)
    # Stage before freezing: include_files must point at pristine documents,
    # never at the working tree's own userdata/logs.
    stage_fresh_userdata()
    build_options: dict[str, object] = create_exe_build_options()
    original_argv: list[str] = sys.argv.copy()
    try:
        sys.argv = [original_argv[0], "build_exe"]
        setup(
            name=CONFIG.app_name,
            version=CONFIG.version,
            description=CONFIG.description,
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
    reset_tree_app_data(output_dir)
    verify_tree_app_data(output_dir)
    return output_dir


# ============================================================================
# Installer
# ============================================================================


def _require_windows() -> None:
    """Reject installer builds on non-Windows hosts."""
    if sys.platform != _WINDOWS_PLATFORM:
        raise InstallerBuildError(
            "--installer produces a Windows MSI and can only run on Windows."
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
        build_dir: Directory that receives the ``.msi``.

    Returns:
        Path to the built ``.msi`` installer.

    Raises:
        InstallerBuildError: When invoked on a non-Windows host, or when
            cx_Freeze finishes without writing the ``.msi``.
    """
    _require_windows()
    msi_dir: Path = _msi_output_dir(build_dir)
    base_dir: Path = ensure_directory(BUILD_BASE_DIR)
    if msi_dir.resolve() == base_dir.resolve():
        msi_dir = ensure_directory(base_dir.parent / "dist")
    return _run_bdist_msi(base_dir, msi_dir)


def _run_bdist_msi(base_dir: Path, msi_dir: Path) -> Path:
    """Invoke cx_Freeze ``bdist_msi`` with Aphelion freeze and MSI options."""
    from cx_Freeze import setup

    # Stage before freezing: the installer must bundle pristine documents.
    stage_fresh_userdata()
    original_argv: list[str] = sys.argv.copy()
    try:
        sys.argv = [original_argv[0], "bdist_msi"]
        setup(
            name=CONFIG.app_name,
            version=CONFIG.version,
            description=CONFIG.description,
            packages=[],
            options=_msi_setup_options(base_dir, msi_dir),
            executables=[
                create_executable(
                    shortcut_name=CONFIG.app_name,
                    shortcut_dir=CONFIG.shortcut_dir,
                )
            ],
        )
    finally:
        sys.argv = original_argv

    # The frozen tree the installer was authored from is verified so a
    # regression in include_files fails the build instead of shipping.
    for tree in _freeze_exe_dirs(base_dir):
        reset_tree_app_data(tree)
        verify_tree_app_data(tree)

    msi_path: Path = _require_msi_file(msi_dir)
    try:
        enhance_installer_ui(msi_path)
    except InstallerUiError as exc:
        raise InstallerBuildError(str(exc)) from exc
    verify_msi_app_data(msi_path)
    return msi_path


def _freeze_exe_dirs(base_dir: Path) -> list[Path]:
    """Return the frozen ``exe.*`` trees cx_Freeze produced under ``base_dir``."""
    return sorted(
        (entry for entry in base_dir.glob("exe.*") if entry.is_dir()),
        key=lambda path: path.name,
    )


def _require_msi_file(msi_dir: Path) -> Path:
    """Return the built installer, or raise if cx_Freeze omitted the ``.msi``."""
    msi_path: Path = (msi_dir / CONFIG.msi_output_name).resolve()
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
        include_files=freeze_include_files(*extras),
    )
    build_options["include_msvcr"] = True
    return {
        "build": {"build_base": str(base_dir)},
        "build_exe": build_options,
        "bdist_msi": create_msi_options(
            dist_dir=msi_dir,
            install_icon=_require_icon(),
        ),
    }


def clean_build_artifacts() -> list[Path]:
    """Delete freeze output trees and return the paths that were removed.

    Also removes the legacy in-repo frozen tree, so ``--clean`` leaves behind
    no artifact that could be committed by accident.
    """
    removed: list[Path] = []
    for directory in (BUILD_BASE_DIR, DIST_DIR, LEGACY_FROZEN_TREE_DIR):
        if not directory.is_dir():
            continue
        shutil.rmtree(directory, ignore_errors=True)
        removed.append(directory)
    return removed


# ============================================================================
# CLI
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    """Return the packaging CLI parser."""
    parser = argparse.ArgumentParser(
        prog="aphelion_build",
        description="Freeze Aphelion Editor and build a Windows installer.",
    )
    parser.add_argument("--version", action="version", version=f"Aphelion Editor {CONFIG.version}")
    parser.add_argument(
        "--exe",
        action="store_true",
        help="Build a standalone (frozen) executable tree.",
    )
    parser.add_argument(
        "--installer",
        action="store_true",
        help="Build a Windows MSI installer. Windows only.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete build/ and dist/ artifacts, then exit.",
    )
    parser.add_argument(
        "--build-dir",
        type=str,
        default=None,
        help="Output directory for --exe (frozen tree) or --installer (MSI).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the requested packaging step.

    ``--installer`` implies a freeze, so it wins when both flags are set.
    With no flags, the standalone executable is built.

    Parameters:
        argv: Optional argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = _build_parser().parse_args(argv)

    if args.clean:
        for directory in clean_build_artifacts():
            print(f"Removed {directory}")
        if not (args.exe or args.installer):
            return 0

    try:
        if args.installer:
            msi_path = build_installer(build_dir=args.build_dir)
            print(f"Wrote installer: {msi_path}")
            print("Bundled userdata/ and logs/ are pristine (no user content).")
            return 0
        dist = build_standalone(build_dir=args.build_dir)
        print(f"Wrote frozen build: {dist}")
        print("Bundled userdata/ and logs/ are pristine (no user content).")
        return 0
    except BuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
