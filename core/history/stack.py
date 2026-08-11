"""Global undo/redo stack for project document edits."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from core.history.command import Command

if TYPE_CHECKING:
    from core.project import Project

DEFAULT_HISTORY_DEPTH: int = 128


class HistoryStack:
    """Executes commands and supports undo / redo with coalescing."""

    def __init__(
        self,
        project: Project,
        *,
        max_depth: int = DEFAULT_HISTORY_DEPTH,
    ) -> None:
        self._project = project
        self._max_depth = max(1, max_depth)
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._listeners: list[Callable[[], None]] = []
        self._is_applying: bool = False

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def is_applying(self) -> bool:
        """True while undo/redo is mutating the project (not a fresh push)."""
        return self._is_applying

    def undo_text(self) -> str:
        if not self._undo:
            return "Undo"
        return f"Undo {self._undo[-1].description()}"

    def redo_text(self) -> str:
        if not self._redo:
            return "Redo"
        return f"Redo {self._redo[-1].description()}"

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def push(self, command: Command) -> bool:
        """Execute and record ``command``. Returns whether it was recorded."""
        if self._is_applying:
            return False

        if self._undo and command.merge_with(self._undo[-1]):
            # Merged into previous — re-execute only the delta via command.execute
            # Merge implementations update their own state then must apply.
            ok = command.execute(self._project)
            if not ok:
                return False
            self._redo.clear()
            self._notify()
            return True

        ok = command.execute(self._project)
        if not ok:
            return False

        self._undo.append(command)
        if len(self._undo) > self._max_depth:
            self._undo.pop(0)
        self._redo.clear()
        self._notify()
        return True

    def undo(self) -> bool:
        if not self._undo or self._is_applying:
            return False
        command = self._undo.pop()
        self._is_applying = True
        try:
            command.undo(self._project)
        finally:
            self._is_applying = False
        self._redo.append(command)
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo or self._is_applying:
            return False
        command = self._redo.pop()
        self._is_applying = True
        try:
            ok = command.execute(self._project)
        finally:
            self._is_applying = False
        if not ok:
            return False
        self._undo.append(command)
        self._notify()
        return True

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
