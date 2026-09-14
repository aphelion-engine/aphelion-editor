"""Best-effort scheduling priority for the playback thread.

Playback is the one workload in the editor with a hard deadline. Every
other thread in the process — the UI, background probing, proxy encoding,
OpenCV's internal pools, FFmpeg's decoder threads — can tolerate being
pre-empted for a few milliseconds. The frame evaluator cannot.

This module asks the OS to treat that one thread slightly more favourably.
It is deliberately **bounded**: ``ABOVE_NORMAL``, never ``TIME_CRITICAL``.
A video editor that starves the rest of the machine to render preview is
not faster in any way the user can perceive, and time-critical priority
also raises the risk of the UI thread itself being starved.

Everything here is best-effort and reversible. A failure to raise priority
is not an error: on a loaded or restricted machine the request is simply
declined, and the caller carries on unchanged.
"""

from __future__ import annotations

import os
import sys
import threading

__all__ = [
    "PriorityResult",
    "lower_current_thread_priority",
    "raise_current_thread_priority",
    "supported",
]

#: Win32: two steps above normal, well below TIME_CRITICAL (15).
_THREAD_PRIORITY_ABOVE_NORMAL = 1


class PriorityResult:
    """Outcome of a priority request."""

    __slots__ = ("applied", "previous", "detail")

    def __init__(self, applied: bool, previous: int | None = None, detail: str = "") -> None:
        self.applied = applied
        self.previous = previous
        self.detail = detail

    def __bool__(self) -> bool:
        return self.applied

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"PriorityResult(applied={self.applied}, "
            f"previous={self.previous}, detail={self.detail!r})"
        )


#: Priorities applied per thread id, so they can be undone exactly.
_APPLIED: dict[int, int | None] = {}
_LOCK = threading.Lock()


def supported() -> bool:
    """Return whether thread priority can be adjusted on this platform."""
    return sys.platform == "win32" or os.name == "posix"


def raise_current_thread_priority() -> PriorityResult:
    """Ask the OS to schedule the calling thread slightly more favourably.

    Idempotent: a thread that already raised its priority is left alone,
    which keeps the previous value recorded so it can be restored exactly.

    Returns:
        A :class:`PriorityResult`; falsy when the request was declined.
    """
    thread_id = threading.get_ident()
    with _LOCK:
        if thread_id in _APPLIED:
            return PriorityResult(True, _APPLIED[thread_id], "already applied")

    if sys.platform == "win32":
        result = _raise_windows()
    elif os.name == "posix":
        result = _raise_posix()
    else:
        return PriorityResult(False, detail="unsupported platform")

    if result.applied:
        with _LOCK:
            _APPLIED[thread_id] = result.previous
    return result


def lower_current_thread_priority() -> PriorityResult:
    """Restore the priority a thread had before :func:`raise_current_thread_priority`.

    Called on playback stop so the editor does not permanently run one
    thread above the rest of the system.
    """
    thread_id = threading.get_ident()
    with _LOCK:
        if thread_id not in _APPLIED:
            return PriorityResult(False, detail="not applied")
        previous = _APPLIED.pop(thread_id)

    if sys.platform == "win32":
        if previous is None:
            previous = 0  # THREAD_PRIORITY_NORMAL
        return _set_windows(previous)
    if os.name == "posix":
        return _set_posix(0)
    return PriorityResult(False, detail="unsupported platform")


# ----------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------


def _raise_windows() -> PriorityResult:
    """Request ``THREAD_PRIORITY_ABOVE_NORMAL`` for this thread."""
    import ctypes

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetCurrentThread()
        previous = int(kernel32.GetThreadPriority(handle))
        if previous >= _THREAD_PRIORITY_ABOVE_NORMAL:
            return PriorityResult(True, previous, "already above normal")
        if not kernel32.SetThreadPriority(handle, _THREAD_PRIORITY_ABOVE_NORMAL):
            return PriorityResult(False, previous, "SetThreadPriority declined")
        return PriorityResult(True, previous, "above normal")
    except Exception as exc:  # noqa: BLE001
        return PriorityResult(False, None, f"{type(exc).__name__}: {exc}")


def _set_windows(priority: int) -> PriorityResult:
    """Set an explicit Win32 thread priority."""
    import ctypes

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetCurrentThread()
        previous = int(kernel32.GetThreadPriority(handle))
        if not kernel32.SetThreadPriority(handle, int(priority)):
            return PriorityResult(False, previous, "SetThreadPriority declined")
        return PriorityResult(True, previous, "restored")
    except Exception as exc:  # noqa: BLE001
        return PriorityResult(False, None, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
# POSIX
# ----------------------------------------------------------------------


def _raise_posix() -> PriorityResult:
    """Apply a small ``nice`` reduction, best-effort.

    Unprivileged processes may only lower their own niceness on most
    systems, so this commonly fails — which is fine, and is reported
    honestly rather than silently swallowed.
    """
    try:
        previous = os.nice(0)
        applied = os.nice(-4)
        return PriorityResult(True, previous, f"nice {previous} -> {applied}")
    except Exception as exc:  # noqa: BLE001
        return PriorityResult(False, None, f"{type(exc).__name__}: {exc}")


def _set_posix(niceness: int) -> PriorityResult:
    """Restore a POSIX niceness value."""
    try:
        current = os.nice(0)
        delta = int(niceness) - current
        os.nice(delta)
        return PriorityResult(True, current, "restored")
    except Exception as exc:  # noqa: BLE001
        return PriorityResult(False, None, f"{type(exc).__name__}: {exc}")
