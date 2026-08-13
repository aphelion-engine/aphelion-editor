"""Pytest hook: keep application packages importable from ``src/``."""

from __future__ import annotations

from srcpath import ensure_src_on_path

ensure_src_on_path()
