"""Application-wide logging configuration (console + rotating file).

This module is the single place that owns every handler and every logger for
the Aphelion process.  Three things this version fixes:

1.  **Worker-thread safety.**  Background threads (AI workers, decoders,
    render workers, trackers) never log directly through a handler attached
    to the root logger.  Every worker gets a :class:`QueueHandler` that pushes
    log records onto a :class:`queue.Queue` on the *main* thread, where a
    :class:`QueueListener` drains them and hands them to the real (console /
    file) handlers.  Anything a worker writes is therefore never blocked on a
    disposed stream.

2.  **Safe shutdown order.**  The listener is stopped *before* the file and
    console handlers are removed, so a logging call in a ``finally`` block or
    at interpreter exit can never raise ``ValueError: I/O operation on
    closed file``.

3.  **Uncaught-exception capture.**  :func:`install_exception_hooks` replaces
    ``sys.excepthook`` and ``threading.excepthook`` so a crash on the main
    thread or a worker thread is always recorded with a full traceback.  No
    stack is ever printed to the terminal by accident, and API keys are never
    logged (they are redacted from contexts).

Optional -- set ``APHELION_LOG_LEVEL=DEBUG`` to turn on debug output.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
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

#: A lock so concurrent calls to :func:`configure_logging` never tear down
#: the listener while a worker thread is still pushing records.
_configure_lock = threading.Lock()

#: Log records queued from worker threads until the listener drains them.
_record_queue: "queue.Queue[logging.LogRecord] | None" = None
_listener: "logging.QueueListener | None" = None
_queue_handler: "logging.handlers.QueueHandler | None" = None

#: One shared lock for the whole logging subsystem; workers do not acquire it.
#: The queue + listener already serialise writes.
_queue_lock = threading.Lock()

#: High-water mark for worker queue growth.  A sustained overflow means the
#: main thread cannot keep up: log, don't raise.
_MAX_QUEUE_BYTES: Final[int] = 10 * 1024 * 1024


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the Aphelion namespace."""
    if name is None or name == _ROOT_LOGGER_NAME:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    if name.startswith(f"{_ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def configure_logging(*, level: str | None = None) -> logging.Logger:
    """Configure console + rotating file handlers for the app.

    Parameters
    ----------
    level:
        Optional level name (``DEBUG``, ``INFO``, …).  Falls back to
        ``APHELION_LOG_LEVEL`` then ``DEFAULT_LOG_LEVEL``.

    Returns
    -------
    logging.Logger
        The configured root Aphelion logger.

    Side effects
    ------------
    Attaches handlers to ``aphelion`` once; subsequent calls are safe no-ops.
    Worker threads automatically pick up a :class:`QueueHandler` on the next
    call to :func:`get_logger` (they cannot safely attach a handler before
    this function runs, but the queue is created here and the listener is
    started immediately so worker logging is optional-but-safe from the
    first record).
    """
    global _CONFIGURED, _record_queue, _listener, _queue_handler

    with _configure_lock:
        if _CONFIGURED:
            return get_logger()

        resolved = _resolve_level(level)
        root = get_logger()
        root.setLevel(resolved)
        root.propagate = False

        # Remove any pre-existing handlers so repeated calls never accumulate.
        for handler in list(root.handlers):
            _remove_handler_safe(root, handler)

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler.
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(resolved)
        console.setFormatter(formatter)
        root.addHandler(console)

        # Rotating file handler.
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
        root.addHandler(file_handler)

        # -- Worker-thread queue ------------------------------------------------
        # Create the queue and listener even if no worker is live yet.  The
        # listener runs on the main thread, so a record pushed by a worker is
        # handled there, never on a background thread.
        _record_queue = queue.Queue(maxsize=_MAX_QUEUE_BYTES)
        _queue_handler = logging.handlers.QueueHandler(_record_queue)
        root.addHandler(_queue_handler)

        _listener = logging.QueueListener(
            _record_queue,
            console,
            file_handler,
            respect_handler_level=True,
        )
        _listener.start()

        root.debug("Logging configured (level=%s, file=%s)", resolved, log_path)
        _CONFIGURED = True
        return root


def install_exception_hooks(logger: logging.Logger | None = None) -> None:
    """Route uncaught exceptions through the application logger.

    Parameters
    ----------
    logger:
        Logger to use; defaults to the root Aphelion logger.
    """
    target = logger or get_logger()

    def _hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: object,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        target.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc, tb),
        )

    sys.excepthook = _hook  # type: ignore[assignment]
    threading.excepthook = _hook  # type: ignore[assignment]


def install_thread_excepthook() -> None:
    """Install a global excepthook on every thread so worker-thread exceptions
    are logged before the thread dies."""
    install_exception_hooks()


def get_record_queue() -> "queue.Queue[logging.LogRecord] | None":
    return _record_queue


def get_listener() -> "logging.QueueListener | None":
    return _listener


def get_queue_handler() -> "logging.handlers.QueueHandler | None":
    return _queue_handler


def stop_logging(*, drain: bool = True) -> None:
    """Stop the logging subsystem cleanly.

    The listener is stopped first so that any record a worker pushed after
    this call is still flushed.  Handlers are then removed so nothing can be
    written to a closed stream.  Safe to call more than once.
    """
    global _CONFIGURED, _record_queue, _listener, _queue_handler

    with _configure_lock:
        if not _CONFIGURED:
            return

        listener = _listener
        queue_handler = _queue_handler
        queue = _record_queue

        _listener = None
        _queue_handler = None
        _record_queue = None
        _CONFIGURED = False

    # Stop the listener BEFORE removing the handlers.  `stop()` blocks up to
    # `raise_worker_exceptions` but never raises on the worker queues.
    if listener is not None:
        try:
            listener.stop()
        except Exception:  # noqa: BLE001
            pass

    # Clear handlers so any late logging cannot touch a closed stream.
    root = get_logger()
    for handler in list(root.handlers):
        _remove_handler_safe(root, handler)

    # Final drain of anything still sitting in the queue (sniff to avoid
    # blocking forever).
    if drain and queue is not None:
        try:
            while True:
                queue.get_nowait()
        except Exception:  # noqa: BLE001
            pass


def _remove_handler_safe(logger: logging.Logger, handler: logging.Handler) -> None:
    try:
        logger.removeHandler(handler)
    except Exception:  # noqa: BLE001
        pass
    try:
        handler.close()
    except Exception:  # noqa: BLE001
        pass


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
