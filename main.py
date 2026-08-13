"""Aphelion application entry point."""

from __future__ import annotations

import sys

from srcpath import DIST_DIR, ensure_src_on_path

ensure_src_on_path()

from utils.runtime_env import prepare_process_environment

# Must run before OpenCV / FFmpeg-backed imports pull in native loggers.
prepare_process_environment()

import argparse

from config.constants import APP_VERSION  # noqa: E402
from ui.windows.runtime import AphelionRuntime  # noqa: E402
from utils.logging_setup import (  # noqa: E402
    configure_logging,
    get_logger,
    install_exception_hooks,
    log_banner,
)

# Strong process-lifetime reference (prevents GC of the session/windows).
_RUNTIME: AphelionRuntime | None = None


def run(argv: list[str] | None = None) -> int:
    """Configure logging and run the Aphelion runtime.

    Parameters:
        argv: Optional argument vector; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    global _RUNTIME
    logger = configure_logging()
    install_exception_hooks(logger)
    log_banner(logger, version=APP_VERSION)

    _RUNTIME = AphelionRuntime()
    return _RUNTIME.run(argv)


def main() -> int:
    """Parse CLI flags and either freeze a standalone build or launch the editor.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Aphelion Editor - A modern, lightweight video editor for the modern age."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Aphelion Editor {APP_VERSION}",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build the application as a standalone executable.",
    )
    parser.add_argument(
        "--build-dir",
        type=str,
        default=str(DIST_DIR),
        help="Directory for the frozen executable tree (cx_Freeze build_exe).",
    )

    args = parser.parse_args()

    if args.build:
        from build import build_standalone

        build_standalone(build_dir=args.build_dir)
        return 0

    try:
        return run()
    except Exception:  # noqa: BLE001
        get_logger("main").exception("Fatal error during application bootstrap")
        return 1


if __name__ == "__main__":
    sys.exit(main())
