"""Application-wide logging configuration (console + rotating file)."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from config.constants import (
    APP_NAME,
    DEFAULT_LOG_LEVEL,
    LOG_BACKUP_COUNT,
    LOG_DIR_NAME,
    LOG_FILE_NAME,
    LOG_MAX_BYTES,
)
from utils.paths import app_data_path, ensure_directory

_ROOT_LOGGER_NAME: Final[str] = "aphelion"
_CONFIGURED: bool = False


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the Aphelion namespace.

    Parameters:
        name: Optional dotted suffix (e.g. ``boot.driver``). When omitted,
            returns the root ``aphelion`` logger.

    Returns:
        A ``logging.Logger`` instance.
    """
    if name is None or name == _ROOT_LOGGER_NAME:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    if name.startswith(f"{_ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def configure_logging(*, level: str | None = None) -> logging.Logger:
    """Configure console + rotating file handlers for the app.

    Parameters:
        level: Optional level name (``DEBUG``, ``INFO``, …). Falls back to
            ``APHELION_LOG_LEVEL`` then ``DEFAULT_LOG_LEVEL``.

    Returns:
        The configured root Aphelion logger.

    Side effects:
        Attaches handlers to ``aphelion`` once; subsequent calls are no-ops.
        Creates the log directory under app data when needed.
    """
    global _CONFIGURED
    logger = get_logger()
    if _CONFIGURED:
        return logger

    resolved = _resolve_level(level)
    logger.setLevel(resolved)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(resolved)
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_path = _log_file_path()
    ensure_directory(log_path.parent)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(resolved)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _CONFIGURED = True
    logger.debug("Logging configured (level=%s, file=%s)", resolved, log_path)
    return logger


def install_exception_hooks(logger: logging.Logger | None = None) -> None:
    """Route uncaught exceptions through the application logger.

    Parameters:
        logger: Logger to use; defaults to the Aphelion root logger.

    Side effects:
        Replaces ``sys.excepthook``.
    """
    target = logger or get_logger()

    def _hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: object,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]
            return
        target.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc, tb),  # type: ignore[arg-type]
        )

    sys.excepthook = _hook  # type: ignore[assignment]


def log_file_path() -> Path:
    """Return the active rotating log file path."""
    return _log_file_path()


def _log_file_path() -> Path:
    return app_data_path(LOG_DIR_NAME, LOG_FILE_NAME)


def _resolve_level(level: str | None) -> int:
    raw = (level or os.environ.get("APHELION_LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    return int(getattr(logging, raw, logging.INFO))


def log_banner(logger: logging.Logger, *, version: str) -> None:
    """Emit a short startup banner with identity and log location."""
    logger.info("%s v%s starting", APP_NAME, version)
    logger.info("Log file: %s", _log_file_path())
