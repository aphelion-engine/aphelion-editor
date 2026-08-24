"""Advertise this editor install so pip-installed ``aphelion_sdk`` can find it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from config.constants import APP_VERSION
from utils.logging_setup import get_logger
from utils.paths import app_data_path, app_root, is_frozen

_LOG = get_logger("host.publish")
_HOST_MANIFEST_NAME: str = "aphelion-host.json"
_REGISTRY_KEY: str = r"Software\Aphelion\Editor"
_EXE_NAME: str = "AphelionEditor.exe"


def publish_editor_host() -> None:
    """Write the host manifest and Windows registry install path.

    Side effects:
        Writes ``aphelion-host.json`` under the app root and records
        ``InstallPath`` in the current-user registry on Windows.
    """
    root: Path = app_root()
    executable: Path = _executable_path(root)
    payload: dict[str, str] = {
        "product": "Aphelion Editor",
        "version": APP_VERSION,
        "install_root": str(root),
        "executable": str(executable),
        "userdata_plugins": str(app_data_path("userdata", "plugins")),
    }
    _write_manifest(root / _HOST_MANIFEST_NAME, payload)
    _write_registry(root, executable)


def _executable_path(root: Path) -> Path:
    """Return the frozen exe or the source ``main.py`` entry."""
    frozen_exe: Path = root / _EXE_NAME
    if is_frozen() or frozen_exe.is_file():
        return frozen_exe
    return root / "main.py"


def _write_manifest(path: Path, payload: dict[str, str]) -> None:
    """Write ``payload`` as JSON, ignoring I/O errors."""
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        _LOG.debug("Could not write host manifest %s", path, exc_info=True)


def _write_registry(root: Path, executable: Path) -> None:
    """Record this install under HKCU so the SDK can locate it."""
    if sys.platform != "win32":
        return
    try:
        import winreg
    except ImportError:
        return
    _set_registry_values(root, executable, winreg)


def _set_registry_values(root: Path, executable: Path, winreg: object) -> None:
    """Write install path, exe, and version into ``Software\\Aphelion\\Editor``."""
    create_key = getattr(winreg, "CreateKey")
    set_value = getattr(winreg, "SetValueEx")
    close_key = getattr(winreg, "CloseKey")
    try:
        key = create_key(getattr(winreg, "HKEY_CURRENT_USER"), _REGISTRY_KEY)
        try:
            set_value(key, "InstallPath", 0, getattr(winreg, "REG_SZ"), str(root))
            set_value(key, "Executable", 0, getattr(winreg, "REG_SZ"), str(executable))
            set_value(key, "Version", 0, getattr(winreg, "REG_SZ"), APP_VERSION)
        finally:
            close_key(key)
    except OSError:
        _LOG.debug("Could not write editor location to the registry", exc_info=True)
