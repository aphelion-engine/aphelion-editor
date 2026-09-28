"""AI edit transactions.

Every assistant edit goes through the editor's own ``Command`` objects. A
transaction applies those commands to the live project as the tools need to
observe their effects (a created node's id, a connection that could be
rejected), records them, and then either

* **commits** — the whole batch becomes *one* undo step labelled
  ``AI: <task>``, so a multi-node workflow is a single Ctrl+Z, or
* **rolls back** — each command is undone in reverse order, leaving the
  project exactly as it was.

The model never touches Qt items and never mutates the project directly; it
only ever causes commands to exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai.validation import ValidationIssue, ValidationReport
from core.history.command import Command


class TransactionError(Exception):
    """Raised when a transaction could not be committed."""


@dataclass
class AppliedTransaction(Command):
    """One undo step wrapping a batch of already-applied commands."""

    commands: list[Command]
    label: str

    def execute(self, project: Any) -> bool:
        """Re-apply the batch (used by redo)."""
        replayed: list[Command] = []
        for command in self.commands:
            if not command.execute(project):
                for done in reversed(replayed):
                    done.undo(project)
                return False
            replayed.append(command)
        return True

    def undo(self, project: Any) -> None:
        for command in reversed(self.commands):
            command.undo(project)

    def description(self) -> str:
        return self.label


@dataclass
class AIEditTransaction:
    """Collects commands for one assistant step."""

    label: str
    _commands: list[Command] = field(default_factory=list)
    _actions: list[str] = field(default_factory=list)
    _changed: list[str] = field(default_factory=list)
    _closed: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def commands(self) -> list[Command]:
        return list(self._commands)

    @property
    def actions(self) -> list[str]:
        """User-facing action lines, e.g. ``['+ Add Floor Tracker']``."""
        return list(self._actions)

    @property
    def changed_node_ids(self) -> list[str]:
        return list(dict.fromkeys(self._changed))

    @property
    def is_empty(self) -> bool:
        return not self._commands

    @property
    def is_open(self) -> bool:
        return not self._closed

    # ------------------------------------------------------------------
    # Applying
    # ------------------------------------------------------------------

    def apply(
        self,
        project: Any,
        command: Command,
        *,
        action: str = "",
        changed_node_ids: list[str] | None = None,
    ) -> bool:
        """Execute ``command`` immediately and record it.

        Returns:
            Whether the command was applied and accepted.
        """
        if self._closed:
            raise TransactionError("Transaction already committed or rolled back.")
        if not command.execute(project):
            return False
        self._commands.append(command)
        if action:
            self._actions.append(action)
        for node_id in changed_node_ids or ():
            if node_id:
                self._changed.append(node_id)
        return True

    def note(self, action: str, *, changed_node_ids: list[str] | None = None) -> None:
        """Record an action line without a command (e.g. a no-op rename)."""
        if action:
            self._actions.append(action)
        for node_id in changed_node_ids or ():
            if node_id:
                self._changed.append(node_id)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def commit(self, history: Any) -> bool:
        """Push the batch as a single undo step.

        Returns:
            ``False`` when there was nothing to record.
        """
        self._closed = True
        if not self._commands:
            return False
        history.push_applied(AppliedTransaction(self._commands, self.label))
        return True

    def rollback(self, project: Any) -> None:
        """Undo every applied command, restoring the pre-transaction state."""
        self._closed = True
        for command in reversed(self._commands):
            try:
                command.undo(project)
            except Exception:  # noqa: BLE001 - rollback must always finish
                continue
        self._commands.clear()

    def discard(self) -> tuple[list[Command], str]:
        """Detach the batch without pushing it (used by deferred Assist mode).

        Returns:
            ``(commands, label)`` so the caller can commit later.
        """
        self._closed = True
        commands, label = self._commands, self.label
        self._commands = []
        return commands, label


def issues_to_validation(payload: dict[str, Any]) -> ValidationReport:
    """Rebuild a :class:`ValidationReport` from a tool result payload."""
    report = ValidationReport()
    for raw in payload.get("issues", ()):
        if not isinstance(raw, dict):
            continue
        report.issues.append(
            ValidationIssue(
                code=str(raw.get("error", "ISSUE")),
                message=str(raw.get("message", "")),
                severity=str(raw.get("severity", "error")),
                node_id=raw.get("node_id"),
                port=raw.get("port"),
                suggestions=tuple(raw.get("suggestions", ()) or ()),
            )
        )
    return report
