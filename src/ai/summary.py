"""Structured completion summaries.

The user must always be told, clearly, that a task finished and what it
changed. That answer is built here — from the *authoritative* record of what
the tools actually did — rather than being left to the model's memory of its
own actions.

The inputs are the action lines the editor's commands produced
(``+ Add Color Grading 'Cinematic Grade'``, ``~ Set ...``, ``+ Connect ...``),
plus validation, warnings, and the plan's own state. Nothing here trusts a
model's claim of success; a summary can only report operations that really ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CompletionStatus(str, Enum):
    """How completely a task finished. Drives the status card and headline."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def symbol(self) -> str:
        return {
            CompletionStatus.COMPLETED: "✓",
            CompletionStatus.COMPLETED_WITH_WARNINGS: "⚠",
            CompletionStatus.PARTIALLY_COMPLETED: "◐",
            CompletionStatus.FAILED: "✕",
            CompletionStatus.CANCELLED: "■",
        }[self]

    @property
    def label(self) -> str:
        return {
            CompletionStatus.COMPLETED: "Finished",
            CompletionStatus.COMPLETED_WITH_WARNINGS: "Finished with warnings",
            CompletionStatus.PARTIALLY_COMPLETED: "Partially completed",
            CompletionStatus.FAILED: "Could not complete",
            CompletionStatus.CANCELLED: "Cancelled",
        }[self]

    @property
    def headline_prefix(self) -> str:
        return {
            CompletionStatus.COMPLETED: "Done",
            CompletionStatus.COMPLETED_WITH_WARNINGS: "Done, with warnings",
            CompletionStatus.PARTIALLY_COMPLETED: "Partly done",
            CompletionStatus.FAILED: "I could not complete this",
            CompletionStatus.CANCELLED: "Cancelled",
        }[self]

    @property
    def is_success(self) -> bool:
        return self in (
            CompletionStatus.COMPLETED,
            CompletionStatus.COMPLETED_WITH_WARNINGS,
        )


# -- action-line parsing -------------------------------------------------

_ADD_NODE = re.compile(r"^\+\s*Add\s+(?P<type>.+?)\s+'(?P<name>.+)'\s*$")
_DELETE = re.compile(r"^-\s*Delete\s+(?P<names>.+)$")
_CONNECT = re.compile(r"^\+\s*Connect\s+(?P<src>.+?)\s*→\s*(?P<dst>.+)$")
_DISCONNECT = re.compile(r"^-\s*Disconnect\s+(?P<src>.+?)\s*→\s*(?P<dst>.+)$")
_SET_PROPERTY = re.compile(r"^~\s*Set\s+(?P<target>.+?)\s*→\s*(?P<value>.*)$")
_SET_EQUALS = re.compile(r"^~\s*(?P<target>[^=]+?)\s*=\s*(?P<value>.+)$")
_RENAME = re.compile(r"^~\s*Rename\s+'(?P<old>.+?)'\s*→\s*'(?P<new>.+?)'\s*$")
_ARRANGE = re.compile(r"^~\s*Arrange\s+(?P<count>\d+)\s+node")
_SECTION = re.compile(r"^\+\s*Create section\s+(?P<name>\S+)")


def _split_names(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass
class AgentCompletionSummary:
    """What one agent run actually accomplished."""

    task: str = ""
    status: CompletionStatus = CompletionStatus.COMPLETED
    #: Workflow that was applied, when one was recognized.
    workflow: str = ""
    workflow_title: str = ""
    #: One or two sentences explaining a significant choice.
    because: str = ""
    created_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    modified_nodes: list[str] = field(default_factory=list)
    changed_properties: list[str] = field(default_factory=list)
    created_connections: list[str] = field(default_factory=list)
    removed_connections: list[str] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    organized_nodes: int = 0
    validation_status: str = ""
    validation_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unsupported_stages: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    rolled_back: bool = False
    committed: bool = False
    plan: dict[str, Any] = field(default_factory=dict)
    #: Human reason for a non-success status.
    status_detail: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AgentCompletionSummary:
        """Rebuild a summary from :meth:`to_dict` output.

        The panel renders the completion card from the same structured payload
        the engine produced, so the card can never disagree with the run.
        """
        data = payload or {}
        try:
            status = CompletionStatus(str(data.get("status", "completed")))
        except ValueError:
            status = CompletionStatus.COMPLETED
        return cls(
            task=str(data.get("task", "") or ""),
            status=status,
            workflow=str(data.get("workflow", "") or ""),
            workflow_title=str(data.get("workflow_title", "") or ""),
            because=str(data.get("because", "") or ""),
            created_nodes=list(data.get("created_nodes", ()) or ()),
            removed_nodes=list(data.get("removed_nodes", ()) or ()),
            modified_nodes=list(data.get("modified_nodes", ()) or ()),
            changed_properties=list(data.get("changed_properties", ()) or ()),
            created_connections=list(data.get("created_connections", ()) or ()),
            removed_connections=list(data.get("removed_connections", ()) or ()),
            renamed=list(data.get("renamed", ()) or ()),
            sections=list(data.get("sections", ()) or ()),
            organized_nodes=int(data.get("organized_nodes", 0) or 0),
            validation_status=str(data.get("validation_status", "") or ""),
            validation_summary=str(data.get("validation_summary", "") or ""),
            warnings=list(data.get("warnings", ()) or ()),
            errors=list(data.get("errors", ()) or ()),
            unsupported_stages=list(data.get("unsupported_stages", ()) or ()),
            unmet=list(data.get("unmet", ()) or ()),
            rolled_back=bool(data.get("rolled_back", False)),
            committed=bool(data.get("committed", False)),
            plan=dict(data.get("plan") or {}),
            status_detail=str(data.get("status_detail", "") or ""),
        )

    # -- derived ---------------------------------------------------------

    @property
    def action_count(self) -> int:
        return (
            len(self.created_nodes)
            + len(self.removed_nodes)
            + len(self.changed_properties)
            + len(self.created_connections)
            + len(self.removed_connections)
            + len(self.renamed)
        )

    def has_changes(self) -> bool:
        return bool(
            self.created_nodes
            or self.removed_nodes
            or self.modified_nodes
            or self.changed_properties
            or self.created_connections
            or self.removed_connections
            or self.renamed
            or self.organized_nodes
        )

    def headline(self) -> str:
        name = self.workflow_title or self.task or "the task"
        name = name.strip().rstrip(".")
        if self.status is CompletionStatus.COMPLETED:
            return f"{self.status.headline_prefix} — {name}."
        return f"{self.status.headline_prefix} — {name}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "label": self.status.label,
            "symbol": self.status.symbol,
            "task": self.task,
            "workflow": self.workflow,
            "workflow_title": self.workflow_title,
            "because": self.because,
            "created_nodes": list(self.created_nodes),
            "removed_nodes": list(self.removed_nodes),
            "modified_nodes": list(self.modified_nodes),
            "changed_properties": list(self.changed_properties),
            "created_connections": list(self.created_connections),
            "removed_connections": list(self.removed_connections),
            "renamed": list(self.renamed),
            "sections": list(self.sections),
            "organized_nodes": self.organized_nodes,
            "validation_status": self.validation_status,
            "validation_summary": self.validation_summary,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "unsupported_stages": list(self.unsupported_stages),
            "unmet": list(self.unmet),
            "rolled_back": self.rolled_back,
            "committed": self.committed,
            "plan": dict(self.plan),
            "status_detail": self.status_detail,
            "action_count": self.action_count,
        }

    # -- prose -----------------------------------------------------------

    def change_lines(self, *, limit: int = 18) -> list[str]:
        """Bullet lines describing the changes at a useful level."""
        lines: list[str] = []
        if self.created_nodes:
            lines.extend(f"Added {name}" for name in self.created_nodes[:limit])
            if len(self.created_nodes) > limit:
                lines.append(f"…and {len(self.created_nodes) - limit} more node(s)")
        if self.removed_nodes:
            lines.extend(f"Removed {name}" for name in self.removed_nodes)
        if self.changed_properties:
            body = self.changed_properties[:limit]
            lines.extend(f"Set {item}" for item in body)
            if len(self.changed_properties) > limit:
                lines.append(
                    f"…and {len(self.changed_properties) - limit} more propert"
                    "y change(s)" if len(self.changed_properties) - limit == 1
                    else f"…and {len(self.changed_properties) - limit} more property changes"
                )
        if self.created_connections:
            lines.extend(
                f"Connected {item}" for item in self.created_connections[:limit]
            )
        if self.removed_connections:
            lines.extend(f"Disconnected {item}" for item in self.removed_connections)
        if self.renamed:
            lines.extend(f"Renamed {item}" for item in self.renamed)
        if self.modified_nodes:
            lines.extend(f"Moved {name}" for name in self.modified_nodes[:limit])
        if self.organized_nodes:
            lines.append(f"Organised {self.organized_nodes} node(s) into a clean layout")
        if self.sections:
            lines.extend(f"Created group {name}" for name in self.sections)
        return lines

    def to_text(self) -> str:
        """The natural-language final answer shown in the conversation."""
        parts: list[str] = [self.headline()]
        if self.because:
            parts.append(self.because)
        lines = self.change_lines()
        if lines:
            parts.append("Changes:\n" + "\n".join(f"• {line}" for line in lines))
        if self.unsupported_stages:
            parts.append(
                "Aphelion has no node for: "
                + ", ".join(self.unsupported_stages)
                + ". I left those stages out rather than inventing a node."
            )
        if self.warnings:
            parts.append("Warnings:\n" + "\n".join(f"! {w}" for w in self.warnings))
        if self.status is CompletionStatus.COMPLETED and self.validation_status == "passed":
            parts.append("Graph validation passed. The changes are one undo step.")
        elif self.validation_status == "passed" and self.committed:
            parts.append("Graph validation passed.")
        if self.unmet:
            parts.append(
                "Not completed:\n" + "\n".join(f"• {item}" for item in self.unmet)
            )
        if self.status_detail:
            parts.append(self.status_detail)
        if self.rolled_back:
            parts.append("The changes were rolled back; the project is unchanged.")
        return "\n\n".join(part for part in parts if part)


def build_summary(
    *,
    task: str = "",
    actions: list[str] | None = None,
    validation: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    unmet: list[str] | None = None,
    cancelled: bool = False,
    rolled_back: bool = False,
    committed: bool = False,
    error: str = "",
    workflow: str = "",
    workflow_title: str = "",
    because: str = "",
    unsupported_stages: list[str] | None = None,
    plan: dict[str, Any] | None = None,
) -> AgentCompletionSummary:
    """Build the summary from the authoritative record of a run."""
    summary = AgentCompletionSummary(
        task=task,
        workflow=workflow,
        workflow_title=workflow_title,
        because=because,
        warnings=list(warnings or []),
        errors=list(errors or []),
        unmet=list(unmet or []),
        unsupported_stages=list(unsupported_stages or []),
        rolled_back=rolled_back,
        committed=committed,
        plan=dict(plan or {}),
    )

    for action in actions or ():
        _absorb(summary, action)

    payload = validation or {}
    if payload:
        ok = bool(payload.get("ok", False))
        summary.validation_status = "passed" if ok else "failed"
        summary.validation_summary = str(payload.get("summary", "") or "")
        if not ok:
            summary.warnings.append(
                summary.validation_summary or "Graph validation reported problems."
            )

    summary.status, summary.status_detail = decide_status(
        has_changes=summary.has_changes(),
        cancelled=cancelled,
        rolled_back=rolled_back,
        error=error,
        errors=summary.errors,
        unmet=summary.unmet,
        unsupported=summary.unsupported_stages,
        warnings=summary.warnings,
        validation_failed=summary.validation_status == "failed",
    )
    return summary


def _absorb(summary: AgentCompletionSummary, action: str) -> None:
    """Fold one action line into the summary."""
    line = (action or "").strip()
    if not line:
        return

    match = _ADD_NODE.match(line)
    if match:
        summary.created_nodes.append(match.group("name"))
        return
    match = _SECTION.match(line)
    if match:
        summary.sections.append(match.group("name"))
        return
    match = _ARRANGE.match(line)
    if match:
        summary.organized_nodes = max(
            summary.organized_nodes, int(match.group("count"))
        )
        return
    match = _CONNECT.match(line)
    if match:
        summary.created_connections.append(
            f"{match.group('src')} → {match.group('dst')}"
        )
        return
    match = _DISCONNECT.match(line)
    if match:
        summary.removed_connections.append(
            f"{match.group('src')} → {match.group('dst')}"
        )
        return
    match = _RENAME.match(line)
    if match:
        summary.renamed.append(f"{match.group('old')} → {match.group('new')}")
        return
    match = _SET_PROPERTY.match(line)
    if match:
        target = match.group("target").strip()
        if "." in target:
            summary.changed_properties.append(f"{target} to {match.group('value').strip()}")
            return
    match = _SET_EQUALS.match(line)
    if match:
        target = match.group("target").strip()
        if "." in target:
            summary.changed_properties.append(f"{target} to {match.group('value').strip()}")
            return
    match = _DELETE.match(line)
    if match:
        summary.removed_nodes.extend(_split_names(match.group("names")))
        return
    if line.startswith("~ Move"):
        summary.modified_nodes.append(line[len("~ Move") :].strip())
        return
    if line.startswith("~ Project settings"):
        summary.changed_properties.append(line[len("~ ") :].strip())


def decide_status(
    *,
    has_changes: bool,
    cancelled: bool,
    rolled_back: bool,
    error: str,
    errors: list[str],
    unmet: list[str],
    unsupported: list[str],
    warnings: list[str],
    validation_failed: bool,
) -> tuple[CompletionStatus, str]:
    """Choose the completion state and the reason shown to the user."""
    if cancelled:
        if has_changes:
            return (
                CompletionStatus.CANCELLED,
                "You stopped the task. Completed changes were kept.",
            )
        return CompletionStatus.CANCELLED, "You stopped the task before it changed anything."

    if error or rolled_back:
        reason = error or (errors[0] if errors else "")
        detail = (
            "Nothing was changed — the edit was rolled back."
            if rolled_back and not error
            else (reason or "The task did not finish.")
        )
        return CompletionStatus.FAILED, detail

    blocking = [item for item in unmet if item]

    if not has_changes and blocking:
        return (
            CompletionStatus.PARTIALLY_COMPLETED,
            "None of the required changes were applied.",
        )

    if blocking:
        return (
            CompletionStatus.PARTIALLY_COMPLETED,
            "Part of the request could not be completed: " + ", ".join(blocking),
        )

    if unsupported:
        return (
            CompletionStatus.COMPLETED_WITH_WARNINGS,
            "Aphelion has no node for: " + ", ".join(unsupported) + ".",
        )

    if validation_failed or warnings:
        return (
            CompletionStatus.COMPLETED_WITH_WARNINGS,
            "",
        )

    return CompletionStatus.COMPLETED, ""


__all__ = [
    "AgentCompletionSummary",
    "CompletionStatus",
    "build_summary",
    "decide_status",
]
