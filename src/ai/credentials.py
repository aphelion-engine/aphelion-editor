"""Secure credential storage for AI provider API keys.

Rules this module exists to enforce:

* API keys never enter a ``.aph`` project file, an exported graph, a tutorial,
  a log line, or a crash report.
* Keys are encrypted at rest with :mod:`cryptography` (already a dependency).
* On Windows the *encryption key itself* is additionally wrapped with DPAPI
  (``CryptProtectData``) so it can only be unwrapped by the same user account
  on the same machine. Elsewhere, the key file is created with owner-only
  permissions as the best available protection.
* The full secret is never returned to display code; :func:`mask_secret`
  yields ``sk-••••••••1234``-style summaries.
"""

from __future__ import annotations

import ctypes
import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from utils.logging_setup import get_logger
from utils.paths import app_data_path, ensure_directory

_LOG = get_logger("ai.credentials")

CREDENTIALS_FILENAME: str = "ai_credentials.json"
KEY_FILENAME: str = "ai_credentials.key"

#: Number of trailing characters of a secret that are safe to display.
VISIBLE_TAIL: int = 4


def mask_secret(secret: str | None, *, visible_tail: int = VISIBLE_TAIL) -> str:
    """Return a display-safe summary of ``secret``.

    The full value is never reconstructed by callers; settings UIs show this
    string and nothing else.
    """
    if not secret:
        return "(not set)"
    text = str(secret)
    if len(text) <= visible_tail + 3:
        return "•" * len(text)
    prefix = ""
    if "-" in text[:6]:
        prefix = text.split("-", 1)[0] + "-"
    return f"{prefix}{'•' * 8}{text[-visible_tail:]}"


# ======================================================================
# Windows DPAPI (best effort, never fatal)
# ======================================================================


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi(protect: bool, payload: bytes) -> bytes | None:
    """Wrap or unwrap ``payload`` with DPAPI. Returns ``None`` on failure."""
    if not _dpapi_available():
        return None
    try:
        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None

    buffer = ctypes.create_string_buffer(payload, len(payload))
    blob_in = _DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    description = ctypes.c_wchar_p("Aphelion AI credentials")
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN

    if protect:
        # CryptProtectData(pDataIn, szDataDescr, pOptionalEntropy, pvReserved,
        #                  pPromptStruct, dwFlags, pDataOut)
        args = (
            ctypes.byref(blob_in),
            description,
            None,
            None,
            None,
            flags,
            ctypes.byref(blob_out),
        )
        function = crypt32.CryptProtectData
    else:
        # CryptUnprotectData takes the same shape but no description.
        args = (
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(blob_out),
        )
        function = crypt32.CryptUnprotectData

    try:
        if not function(*args):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:  # noqa: BLE001 - DPAPI is an enhancement, not a requirement
        return None


# ======================================================================
# Store
# ======================================================================


@dataclass
class CredentialStore:
    """Encrypted ``ref → secret`` map backed by two files under ``userdata``."""

    directory: Path | None = None
    _fernet: object | None = None
    _secrets: dict[str, str] | None = None

    def __post_init__(self) -> None:
        self._fernet = None
        self._secrets = None

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def _key_path(self) -> Path:
        if self.directory is not None:
            return Path(self.directory) / KEY_FILENAME
        return app_data_path("userdata", KEY_FILENAME)

    @property
    def _vault_path(self) -> Path:
        if self.directory is not None:
            return Path(self.directory) / CREDENTIALS_FILENAME
        return app_data_path("userdata", CREDENTIALS_FILENAME)

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _load_or_create_key(self) -> bytes:
        """Return the 32-byte Fernet key, creating it on first use."""
        from cryptography.fernet import Fernet

        path = self._key_path
        if path.is_file():
            try:
                raw = path.read_bytes()
            except OSError:
                raw = b""
            if raw:
                unwrapped = _dpapi(False, raw)
                key = unwrapped if unwrapped is not None else raw
                if len(key) >= 32:
                    return key
        key = Fernet.generate_key()
        self._write_key(key)
        return key

    def _write_key(self, key: bytes) -> None:
        path = self._key_path
        ensure_directory(path.parent)
        wrapped = _dpapi(True, key)
        payload = wrapped if wrapped is not None else key
        handle, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
            try:
                os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _cipher(self) -> object | None:
        if self._fernet is None:
            try:
                from cryptography.fernet import Fernet

                self._fernet = Fernet(self._load_or_create_key())
            except Exception as exc:  # noqa: BLE001 - no crypto, no stored keys
                _LOG.warning(
                    "Secure credential storage unavailable (%s); AI provider "
                    "keys will be kept in memory for this session only.",
                    type(exc).__name__,
                )
                self._fernet = False
        return self._fernet or None

    # ------------------------------------------------------------------
    # Vault
    # ------------------------------------------------------------------

    def _load_secrets(self) -> dict[str, str]:
        if self._secrets is not None:
            return self._secrets
        cipher = self._cipher()
        path = self._vault_path
        if cipher is None or not path.is_file():
            self._secrets = {}
            return self._secrets
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("AI credential vault unreadable: %s", type(exc).__name__)
            self._secrets = {}
            return self._secrets

        decoded: dict[str, str] = {}
        entries = document.get("entries", {}) if isinstance(document, dict) else {}
        if isinstance(entries, dict):
            for ref, token in entries.items():
                try:
                    decoded[str(ref)] = cipher.decrypt(str(token).encode("ascii")).decode("utf-8")
                except Exception:  # noqa: BLE001 - wrong key/machine: skip silently
                    continue
        self._secrets = decoded
        return self._secrets

    def _save_secrets(self) -> None:
        cipher = self._cipher()
        if cipher is None:
            # Without crypto we deliberately persist nothing.
            return
        secrets = self._secrets or {}
        entries = {
            ref: cipher.encrypt(value.encode("utf-8")).decode("ascii")
            for ref, value in secrets.items()
        }
        path = self._vault_path
        ensure_directory(path.parent)
        payload = {"version": 1, "entries": entries}
        text = json.dumps(payload, indent=2) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, ref: str) -> str | None:
        """Return the stored secret for ``ref``, if any."""
        if not ref:
            return None
        return self._load_secrets().get(str(ref))

    def set(self, ref: str, secret: str) -> None:
        """Store (or clear, when ``secret`` is empty) a secret."""
        if not ref:
            return
        secrets = self._load_secrets()
        if secret:
            secrets[str(ref)] = str(secret)
        else:
            secrets.pop(str(ref), None)
        self._save_secrets()

    def delete(self, ref: str) -> None:
        self.set(ref, "")

    def has(self, ref: str) -> bool:
        return bool(self.get(ref))

    def refs(self) -> list[str]:
        return sorted(self._load_secrets())

    def usable(self) -> bool:
        """Whether encrypted persistence is working on this machine."""
        return self._cipher() is not None

    def describe(self, ref: str) -> str:
        """Return a masked display string for ``ref``."""
        return mask_secret(self.get(ref))
