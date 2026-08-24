"""MSI table rows that add installer choices cx_Freeze does not ship.

Injected through ``bdist_msi`` ``data`` so the wizard can:

* install for the current user or every user
* optionally append the install folder to PATH
* optionally create a desktop shortcut
* optionally pip-install the bundled Aphelion SDK
* record the install folder so the SDK can find this editor
"""

from __future__ import annotations

from typing import Final

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

    Exceptions:
        None.

    Side effects:
        None.
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
