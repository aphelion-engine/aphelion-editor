"""Command protocol for undoable project mutations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.project import Project


class Command(ABC):
    """One undoable unit of work against a ``Project``."""

    @abstractmethod
    def execute(self, project: Project) -> bool:
        """Apply the change. Return ``False`` to reject (not pushed)."""

    @abstractmethod
    def undo(self, project: Project) -> None:
        """Reverse the change."""

    @abstractmethod
    def description(self) -> str:
        """Short label for menus / status bar."""

    def merge_with(self, previous: Command) -> bool:
        """Optionally absorb ``previous`` for coalescing. Default: no merge."""
        _ = previous
        return False
