"""Aphelion application entry point."""

from __future__ import annotations

import sys

from utils.runtime_env import prepare_process_environment

# Must run before OpenCV / FFmpeg-backed imports pull in native loggers.
prepare_process_environment()

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
    """CLI entry used by ``python main.py`` and packaged launchers."""
    try:
        return run()
    except Exception:
        get_logger("main").exception("Fatal error during application bootstrap")
        return 1


if __name__ == "__main__":
    sys.exit(main())
