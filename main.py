"""Aphelion application entry point for source-tree launches."""

from __future__ import annotations

import sys

from srcpath import ensure_src_on_path

ensure_src_on_path()

from aphelion_cli import main

if __name__ == "__main__":
    sys.exit(main())
