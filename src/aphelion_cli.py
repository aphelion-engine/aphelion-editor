"""Installed console-script entry for Aphelion Editor."""

from __future__ import annotations

import sys

from utils.runtime_env import prepare_process_environment

# Must run before OpenCV / FFmpeg-backed imports pull in native loggers.
prepare_process_environment()

import argparse
from pathlib import Path

from config.constants import APP_VERSION
from ui.windows.runtime import AphelionRuntime
from utils.logging_setup import configure_logging, get_logger, install_exception_hooks, log_banner

# Strong process-lifetime reference (prevents GC of the session/windows).
_RUNTIME: AphelionRuntime | None = None


def _default_dist_dir() -> str:
    """Return the source-tree ``dist/`` path used by ``--build``."""
    return str(Path(__file__).resolve().parent.parent / "dist")


def _default_installer_dir() -> str:
    """Return ``releases/`` for MSI output."""
    return str(Path(__file__).resolve().parent.parent / "releases")


def _build_parser() -> argparse.ArgumentParser:
    """Return the editor CLI parser."""
    parser = argparse.ArgumentParser(
        description="Aphelion Editor - A modern, lightweight video editor for the modern age."
    )
    parser.add_argument("--version", action="version", version=f"Aphelion Editor {APP_VERSION}")
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build the application as a standalone executable.",
    )
    parser.add_argument(
        "--build-installer",
        action="store_true",
        help="Build a Windows MSI installer (cx_Freeze bdist_msi). Windows only.",
    )
    parser.add_argument(
        "--build-dir",
        type=str,
        default=None,
        help="Output directory for --build (frozen tree) or --build-installer (MSI).",
    )
    return parser


def _run_packaging(args: argparse.Namespace) -> int | None:
    """Run a packaging command when requested.

    Parameters:
        args: Parsed CLI arguments.

    Returns:
        Process exit code when a packaging flag was set; otherwise ``None``.

    Raises:
        None. Packaging errors are printed and returned as exit code ``1``.
    """
    if not args.build and not args.build_installer:
        return None
    try:
        return _dispatch_packaging(args)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


def _dispatch_packaging(args: argparse.Namespace) -> int:
    """Freeze and/or build an installer based on CLI flags.

    ``--build-installer`` includes a freeze, so it wins when both flags are set.

    Parameters:
        args: Parsed CLI arguments. ``build`` or ``build_installer`` is set.

    Returns:
        ``0`` after a successful packaging run.

    Raises:
        InstallerBuildError: When MSI creation is requested off Windows.
        distutils.errors.DistutilsOptionError: If freeze options are invalid.
    """
    if args.build_installer:
        from installer_build import build_installer

        dest = args.build_dir or _default_installer_dir()
        msi_path = build_installer(build_dir=dest)
        print(f"Wrote installer: {msi_path}")
        return 0
    from freeze_app import build_standalone

    dest = args.build_dir or _default_dist_dir()
    build_standalone(build_dir=dest)
    return 0


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
    """Parse CLI flags and either package a build or launch the editor.

    Returns:
        Process exit code.
    """
    args = _build_parser().parse_args()
    packaged = _run_packaging(args)
    if packaged is not None:
        return packaged
    try:
        return run()
    except Exception:  # noqa: BLE001
        get_logger("main").exception("Fatal error during application bootstrap")
        return 1


if __name__ == "__main__":
    sys.exit(main())
