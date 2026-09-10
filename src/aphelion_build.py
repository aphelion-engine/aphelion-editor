"""Single-module build pipeline for Aphelion Editor.

Everything required to ship the editor lives in this one file:

* **config** — one :class:`BuildConfig` holding name, version, paths and
  MSI identity, so a release bump is a one-line edit.
* **freeze** — cx_Freeze ``build_exe`` options and the standalone build.
* **installer** — cx_Freeze ``bdist_msi`` options, the custom wizard
  tables (install scope, PATH, desktop shortcut, SDK install) and the
  post-build MSI layout patch.
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
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

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
        optimize_level: Bytecode optimization level; defaults to the config.

    Returns:
        Mapping suitable for ``setup(options={"build_exe": ...})``.
    """
    return {
        "packages": [*APP_PACKAGES, *THIRD_PARTY_PACKAGES],
        "includes": ["aphelion_cli"],
        "excludes": excludes if excludes is not None else list(DEFAULT_EXCLUDES),
        "include_files": include_files if include_files is not None else list(INCLUDE_FILES),
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

    icon_path: Path = resource_path(CONFIG.icon_name)
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
    msi_path: Path = _require_msi_file(msi_dir)
    try:
        enhance_installer_ui(msi_path)
    except InstallerUiError as exc:
        raise InstallerBuildError(str(exc)) from exc
    return msi_path


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
        include_files=[*INCLUDE_FILES, *extras],
    )
    build_options["include_msvcr"] = True
    return {
        "build": {"build_base": str(base_dir)},
        "build_exe": build_options,
        "bdist_msi": create_msi_options(
            dist_dir=msi_dir,
            install_icon=resource_path(CONFIG.icon_name),
        ),
    }


def clean_build_artifacts() -> list[Path]:
    """Delete freeze output trees and return the paths that were removed."""
    removed: list[Path] = []
    for directory in (BUILD_BASE_DIR, DIST_DIR, REPO_ROOT / "build"):
        if directory.is_dir():
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
            return 0
        dist = build_standalone(build_dir=args.build_dir)
        print(f"Wrote frozen build: {dist}")
        return 0
    except BuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
