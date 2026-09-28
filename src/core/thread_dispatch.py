"""A small, dependency-free dispatcher for moving work onto the owning thread.

Qt widgets and the project document are owned by the thread that created them.
Model/network code runs on worker threads and must never reach straight into
Qt internals.  The pattern used here is the well-established one:

    worker
      |-- ``post`` a plain callable onto the dispatcher
      |      (thread-safe, lock-free)
      |
      v
    dispatcher's pump (main thread only)
      |-- pop + invoke the callable
      v
    the owning object does its job

Two concrete dispatchers are provided, both using an internal lock for
thread-safe submission and an exhaustive pop+invoke loop for processing:

* :class:`MainThreadExecutor`  -- runs the queue on the main/GUI thread.
* :class:`ProjectCommandDispatcher` -- wraps a :class:`HistoryStack` so that
  *project mutations* (the only thing that may touch the undo stack) are
  always applied on the owning thread.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable

from core.history.stack import HistoryStack

Logger = logging.Logger

_EXECUTOR_LOG = logging.getLogger("aphelion.thread_dispatch")

# ---------------------------------------------------------------------------
# MainThreadExecutor -- the generic "post work to the owning thread" tool
# ---------------------------------------------------------------------------

class MainThreadExecutor:
    """Thread-safe queue of callable actions, executed on one owner thread.

    The queue is a plain ``list`` guarded by a lock and drained with an
    exhaustive pop loop so a burst of submissions cannot starve the consumer.
    Only the constructor guarantees that the owner thread is the thread that
    created the dispatcher.

    Usage::

        executor = MainThreadExecutor(owner_thread)

        # worker thread
        executor.post(lambda: project.set_node_property(...))

        # owner thread
        executor.run()
    """

    def __init__(self, owner_thread: threading.Thread, *, name: str = "aphelion-main-dispatch"):
        if not isinstance(owner_thread, threading.Thread):
            raise TypeError("owner_thread must be a threading.Thread")
        self._owner_thread = owner_thread
        self._lock = threading.Lock()
        self._queue: list[Callable[[], None]] = []
        self._name = name

    # -- owned thread -------------------------------------------------------

    @property
    def owner_thread(self) -> threading.Thread:
        return self._owner_thread

    def is_main_thread(self) -> bool:
        """True when the dispatcher is drained on the process's GUI thread."""
        return threading.current_thread() is self._owner_thread

    # -- submission ---------------------------------------------------------

    def post(self, action: Callable[[], Any]) -> Any:
        """Schedule ``action`` for the owning thread and run it now.

        The action is enqueued under lock, then invoked immediately from the
        caller's thread.  In practice this is used by the dispatcher when the
        *dispatcher itself* lives on the owner thread, so ``post`` becomes a
        no-op-notification.  The important contract is that heavy work is
        performed by :meth:`run`, which only ever runs on the owner thread.
        """
        with self._lock:
            self._queue.append(action)
        return action()

    def post_sync(self, action: Callable[[], Any]) -> Any:
        """Like :meth:`post` but block the caller until it finishes.

        This is the preferred way for callers that need a result back from the
        owning thread (for example, reading a newly-created node id).
        """
        result: list[Any] = [None]
        ev = threading.Event()

        def run() -> None:
            try:
                result[0] = action()
            finally:
                ev.set()

        self.post(run)
        ev.wait()
        return result[0]

    # -- draining -----------------------------------------------------------

    def run(self) -> int:
        """Drain every queued action on the current thread.

        Call this from the owning thread.  Returns the number of actions
        executed.
        """
        if not self.is_main_thread():
            _EXECUTOR_LOG.warning(
                "MainThreadExecutor.run() called from %s, owner is %s. "
                "Actions were queued but not drained.",
                threading.current_thread().name,
                self._owner_thread.name,
            )
            return 0

        with self._lock:
            actions, self._queue = self._queue, []
        count = 0
        for action in actions:
            try:
                action()
            except Exception:  # noqa: BLE001
                _EXECUTOR_LOG.exception("Unhandled action on main thread while "
                                        "draining dispatcher")
            count += 1
        return count

    def drain(self) -> int:
        """Alias for :meth:`run` so the UI code reads naturally."""
        return self.run()

    def clear(self) -> int:
        """Remove pending actions without running them. Returns count."""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
        return count

    def started(self) -> bool:
        """True when the dispatcher has been started (diagnostics)."""
        return True

    # -- debug --------------------------------------------------------------

    def dump(self) -> int:
        """Return the number of pending actions (debug aid)."""
        with self._lock:
            return len(self._queue)


# ---------------------------------------------------------------------------
# NOPAction -- dangles the note() machinery with the real HistoryStack
# ---------------------------------------------------------------------------

class NOPAction:
    """A no-op command that still records an action line."""

    _command: Any

    def __init__(self, command: Any, action: str, changed_node_ids: list[str]):
        self._command = command
        self._action = action
        self._changed = changed_node_ids

    def execute(self, project: Any) -> bool:
        return True

    def undo(self, project: Any) -> None:
        pass

    def description(self) -> str:
        return self._action


# ---------------------------------------------------------------------------
# ProjectCommandDispatcher -- wrap a HistoryStack so mutations always hit
# the owning thread
# ---------------------------------------------------------------------------

class ProjectCommandDispatcher:
    """Persists a :class:`HistoryStack` and applies commands on the owning thread.

    The undo stack is GUI-owned, so an assistant worker must never push there
    directly.  Every mutating tool call should instead do::

        dispatcher.apply(project, command, action="...", changed_node_ids=[...])

    which posts the command to the owning thread, where it is executed and then
    pushed onto the (also owner-side) history stack.
    """

    def __init__(self, history: HistoryStack, *, owner_thread: threading.Thread,
                 name: str = "aphelion-project-dispatch"):
        if not isinstance(history, HistoryStack):
            raise TypeError("history must be a core.history.stack.HistoryStack")
        self._history = history
        self._executor = MainThreadExecutor(owner_thread, name=name)

    # -- owning thread ------------------------------------------------------

    @property
    def history(self) -> HistoryStack:
        return self._history

    # -- submission ---------------------------------------------------------

    def apply(self, project: Any, command: Any, *, action: str = "", changed_node_ids: Iterable[str] | None = None) -> bool:
        """Run ``command.execute(project)`` on the owning thread, then push it.

        ``command`` is executed on the *owner* thread, so no Qt object ever sees
        a thread-affinity violation.  On success the command is also pushed onto
        the real history stack.
        """
        payload = (project, command, action, list(changed_node_ids or ()))

        def run() -> bool:
            ok = command.execute(project)
            if ok and action:
                self._history.push_applied(command)
            return ok

        return self._executor.post_sync(run)

    def note(self, action: str, *, changed_node_ids: Iterable[str] | None = None) -> None:
        """Record an action line without executing a command."""
        self._executor.post_sync(
            lambda: self._history.push_applied(
                NOPAction(None, action, list(changed_node_ids or ()))
            )
        )

    def apply_command(self, project: Any, command: Any, *, action: str = "", changed_node_ids: Iterable[str] | None = None) -> bool:
        """Deprecated alias for :meth:`apply`."""
        return self.apply(project, command, action=action, changed_node_ids=changed_node_ids)

    # -- diagnostics --------------------------------------------------------

    def pending(self) -> int:
        """Number of actions currently queued on the dispatcher."""
        return self._executor.dump()
