"""Post-process a cx_Freeze MSI so the folder page is usable.

cx_Freeze draws ``DirectoryCombo`` 80px tall on top of ``DirectoryList``.
This module repositions those controls into a standard Look-in / folder-tree
/ path layout and enables Back to the options page.
"""

from __future__ import annotations

from pathlib import Path

from installer_ui import DIRECTORY_DIALOG

_COMBO_ATTRIBUTES: int = 393219


class InstallerUiError(RuntimeError):
    """Raised when the built MSI cannot be opened or patched."""


def enhance_installer_ui(msi_path: Path) -> None:
    """Rewrite the destination dialog layout on ``msi_path``.

    Parameters:
        msi_path: Existing ``.msi`` produced by cx_Freeze ``bdist_msi``.

    Returns:
        None.

    Raises:
        InstallerUiError: If ``msilib`` cannot open or commit the database.

    Side effects:
        Updates Control rows in the MSI and commits the file in place.
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
