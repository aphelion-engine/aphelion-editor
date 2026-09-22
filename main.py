"""Aphelion application entry point for source-tree launches."""

from __future__ import annotations

import sys

from srcpath import ensure_src_on_path

ensure_src_on_path()

from aphelion_cli import main


def _ensure_native_backend() -> None:
    """Build the required native module before starting the application."""
    from core.native import require_available

    require_available()

if __name__ == "__main__":
    try:
        _ensure_native_backend()
    except Exception as exc:  # noqa: BLE001 - give source launches a clear error
        print(f"Aphelion native backend could not be built: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(main())
