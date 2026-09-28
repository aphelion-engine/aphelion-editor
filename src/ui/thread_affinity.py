"""Thread-affinity assertions for development builds.

QGraphicsItem / QObject subclasses carry a thread affinity: only the thread
that created them may touch them.  The classic manifestation is

    QBasicTimer::start: Timers cannot be started from another thread

which usually surface as a crash or a swallowed warning instead of a clear
message.  In development builds this module checks the affinity explicitly and
writes out useful context, so the problem is diagnosed instead of hidden.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
#: Enable run-time thread-affinity checks.  Off in release builds to keep the
#: performance cost (and the risk of false positives in third-party code)
#: out of the shipped product.
_DEBUG_ASSERTIONS = os.environ.get("APHELION_DEBUG_THREADS") not in (
    None,
    "0",
    "false",
    "False",
)

#: The thread that owns the Qt GUI event loop.
_MAIN_THREAD = threading.main_thread()


def _is_main_thread() -> bool:
    return threading.current_thread() is _MAIN_THREAD


# ---------------------------------------------------------------------------
# Helper predicates
# ---------------------------------------------------------------------------

def assert_main_thread(message: str = "") -> None:
    """Fail loudly if the current thread is not the Qt GUI thread."""
    if not _DEBUG_ASSERTIONS or _is_main_thread():
        return
    _report(
        "thread-affinity violation",
        "expected the main/GUI thread",
        f"current thread: {threading.current_thread().name} "
        f"(id={threading.current_thread().ident})",
        message,
    )


def assert_same_thread(expected_thread: threading.Thread, message: str = "") -> None:
    """Fail loudly if the current thread is not ``expected_thread``."""
    if not _DEBUG_ASSERTIONS:
        return
    if threading.current_thread() is expected_thread:
        return
    _report(
        "thread-affinity violation",
        f"expected thread {expected_thread.name} "
        f"(id={expected_thread.ident})",
        f"current thread: {threading.current_thread().name} "
        f"(id={threading.current_thread().ident})",
        message,
    )


def assert_thread_is(obj: Any, message: str = "") -> None:
    """Fail loudly if ``obj`` belongs to a different thread than the GUI one.

    Works for any object that exposes a ``thread()``-style attribute; when that
    is missing we fall back to a generic check against the main thread.
    """
    if not _DEBUG_ASSERTIONS:
        return
    if _is_main_thread():
        return
    owner = getattr(obj, "thread", None)
    if callable(owner):
        try:
            owner = owner()
        except Exception:
            owner = None
    if owner is not None and getattr(owner, "isRunning", lambda: False)():
        # A running QThread is not the main thread.  Distinguish it from the
        # worker threads that are allowed to do model work.
        if owner is not threading.main_thread():
            _report(
                "thread-affinity violation",
                "object belongs to a worker thread",
                f"object thread: {owner.name} "
                f"(id={owner.ident})",
                message,
            )
    # ``thread()`` missing or not a running thread: fall back to the main
    # thread check.
    if not _is_main_thread():
        _report(
            "thread-affinity violation",
            "expected the main/GUI thread",
            f"current thread: {threading.current_thread().name} "
            f"(id={threading.current_thread().ident})",
            message,
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _report(
    kind: str,
    expected: str,
    actual: str,
    context: str = "",
) -> None:
    """Emit a clear diagnostic.  Never raise: a crash here would be bad."""
    frame = sys._getframe(1)
    filename = frame.f_globals.get("__file__", "?")
    lineno = frame.f_lineno
    location = f"{filename}:{lineno}" if filename != "?" else "?"

    lines = [
        "",
        "=" * 72,
        f"[thread-affinity] {kind} - {actual}, expected {expected}",
        f"  location : {location}",
        f"  context  : {context}" if context else "  context  : (none)",
        "=" * 72,
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assert_gui_thread(message: str = "") -> None:
    """Alias for :func:`assert_main_thread` so the intent is obvious."""
    assert_main_thread(message)


def is_gui_thread() -> bool:
    """Return True when the current thread owns the Qt event loop."""
    return _is_main_thread()


def assert_widget_on_widget_thread(widget: Any, message: str = "") -> None:
    """Check a QWidget's affinity is the main/Qt thread."""
    assert_thread_is(widget, message)
