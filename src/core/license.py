"""Local trial state and online license activation for Aphelion Editor."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config.constants import APP_VERSION
from utils.paths import app_data_path

LICENSE_SITE_URL = "https://www.aphelion-community.com"
LICENSE_VALIDATE_URL = f"{LICENSE_SITE_URL}/api/licenses/validate"
PRODUCT_ID = "aphelion-editor"
TRIAL_DAYS = 7
_KEY_PATTERN = re.compile(r"^APHL(?:-[A-F0-9]{6}){3}$")
# Ed25519 SubjectPublicKeyInfo DER, base64 encoded. The matching private key
# exists only in the web deployment/CI secret store and is never shipped.
_ENTITLEMENT_PUBLIC_KEY_DER = "MCowBQYDK2VwAyEAPd/fqrrW939qF5Oxsm3bhcvY4VFVfhNQSVR1wtSqGnQ="


@dataclass(frozen=True, slots=True)
class LicenseStatus:
    """Current local entitlement state."""

    activated: bool
    days_remaining: int
    trial_expired: bool


class LicenseStore:
    """Persist trial start and activation state outside project documents."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_license_path()
        self._data = self._load()

    def status(self) -> LicenseStatus:
        if _verify_entitlement(str(self._data.get("entitlement", ""))):
            return LicenseStatus(True, 0, False)

        now = datetime.now(timezone.utc)
        started = _parse_timestamp(self._data.get("first_seen"))
        if started is None:
            started = now
            self._data["first_seen"] = started.isoformat()
            self._data["last_seen"] = started.isoformat()
            self._save()

        last_seen = _parse_timestamp(self._data.get("last_seen"))
        if last_seen is not None and now < last_seen:
            # Treat a wall-clock rollback as the end of the trial rather than
            # allowing the local countdown to be extended indefinitely.
            return LicenseStatus(False, 0, True)
        self._data["last_seen"] = now.isoformat()
        self._save()

        elapsed = max(0.0, (now - started).total_seconds())
        remaining = max(0, TRIAL_DAYS - int(elapsed // 86400))
        return LicenseStatus(False, remaining, remaining <= 0)

    def activate(self, key: str, timeout: float = 8.0) -> tuple[bool, str]:
        normalized = _normalize_key(key)
        payload = json.dumps(
            {"licenseKey": normalized, "productId": PRODUCT_ID, "productVersion": APP_VERSION}
        ).encode("utf-8")
        request = urllib.request.Request(
            LICENSE_VALIDATE_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return False, f"Could not verify the license online: {exc}"

        if not bool(body.get("active")) or not isinstance(body.get("entitlement"), str):
            return False, str(body.get("error") or "License key was not accepted.")
        if not _verify_entitlement(body["entitlement"]):
            return False, "The licensing service returned an invalid entitlement."
        self._data["entitlement"] = body["entitlement"]
        self._data["key_fingerprint"] = normalized[-4:]
        self._save()
        return True, "License activated. Thank you."

    def _load(self) -> dict[str, object]:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            # Editing must remain available even when the install directory is
            # read-only; the next launch will simply start a fresh trial clock.
            return


def _normalize_key(value: str) -> str:
    normalized = str(value).strip().upper()
    if not _KEY_PATTERN.fullmatch(normalized):
        raise ValueError("Enter a license key in APHL-XXXXXX-XXXXXX-XXXXXX format.")
    return normalized


def _default_license_path() -> Path:
    """Use per-user writable storage, not the install directory."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or app_data_path("userdata"))
        return root / "Aphelion" / "Editor" / "license.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return root / "aphelion-editor" / "license.json"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None


def _verify_entitlement(token: str) -> bool:
    """Verify a server-signed entitlement without trusting local flags."""
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_der_public_key

        encoded_payload, encoded_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        key = load_der_public_key(base64.b64decode(_ENTITLEMENT_PUBLIC_KEY_DER))
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(signature, payload)
        claims = json.loads(payload.decode("utf-8"))
        return claims.get("productId") == PRODUCT_ID
    except Exception:  # noqa: BLE001 - invalid local state is unlicensed
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
