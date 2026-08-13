"""Test-suite path bootstrap so application packages import from ``src/``."""

from __future__ import annotations

from srcpath import ensure_src_on_path

ensure_src_on_path()
