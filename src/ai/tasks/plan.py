"""Effort-aware agent task planning: the todo list the UI renders as a
progress card.

A large request is not one action, it is a sequence of them.  The engine keeps
that sequence explicit so the model has a stable plan to work through and the
UI can show real progress (``✓ Find compatible nodes`` / ``● Build graph``).
Completion is decided by step status and real tool results, never by the
model's claim.

Step status is driven by the host's tool results (see
:class:`ai.engine.AgentEngine`), so the list cannot drift away from reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from .effort import AgentEffort

#: The plan used for a plain edit that needs no professional workflow research.
DEFAULT_EDIT_PLAN: tuple[str, ...] = (
    "Inspect the current graph",
    "Apply the requested changes",
    "Validate the result",
    "Organise the new nodes",
)

#: Workflow plan (no effort variation).
WORKFLOW_EDIT_PLAN: tuple[str, ...] = (
    "Understood the professional workflow",
    "Found the Aphelion nodes for each stage",
    "Built the nodes",
    "Configured their properties",
    "Connected the chain",
    "Validated the graph",
    "Organised the layout",
    "Summarised the changes",
)

#: Read-only work.
INSPECT_PLAN: tuple[str, ...] = ("Inspect and answer",)

#: Minimal plan for fast mechanical edits.
FAST_PLAN: tuple[str, ...] = (
    "Apply the change",
    "Validate the result",
)

#: Extended plan for expert/maximum inspection and QA.
EXPERT_PLAN: tuple[str, ...] = (
    "Understood the professional workflow",
    "Found the Aphelion nodes for each stage",
    "Built the nodes",
    "Configured their properties",
    "Connected the chain",
    "Validated the graph",
    "Organised the layout",
    "Ran visual QA on representative frames",
    "Finalised the summary",
)

#: Maximum plan adds workspace research and iterative refinement.
MAXIMUM_PLAN: tuple[str, ...] = (
    "Understood the professional workflow",
    "Researched the request against real-world practice",
    "Found the Aphelion nodes for each stage",
    "Built the nodes",
    "Configured their properties",
    "Connected the chain",
    "Validated the graph",
    "Organised the layout",
    "Ran visual QA on representative frames",
    "Refined the result after QA",
    "Finalised the summary",
)

_EFFORT_TO_PLAN: dict[AgentEffort, tuple[str, ...]] = {
    AgentEffort.FAST: FAST_PLAN,
    AgentEffort.NORMAL: DEFAULT_EDIT_PLAN,
    AgentEffort.EXPERT: EXPERT_PLAN,
    AgentEffort.MAXIMUM: MAXIMUM_PLAN,
    AgentEffort.AUTO: DEFAULT_EDIT_PLAN,
}

#: Extra steps applied on top of the effort base when the request names a
#: recognised professional workflow.
WORKFLOW_EXTRA_STEPS: tuple[str, ...] = (
    "Understood the professional workflow",
    "Found the Aphelion nodes for each stage",
)


class StepStatus(str, Enum):
    """Where a plan step is in its lifecycle."""

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def symbol(self) -> str:
        """Glyph used in text renderings and the activity card."""
        return {
            StepStatus.PENDING: "○",
            StepStatus.ACTIVE: "●",
            StepStatus.DONE: "✓",
            StepStatus.FAILED: "✕",
            StepStatus.SKIPPED: "–",
        }[self]

    @property
    def is_finished(self) -> bool:
        return self in (StepStatus.DONE, StepStatus.SKIPPED)


@dataclass
class TodoItem:
    """One step of the agent's plan."""
    id: str
    title: str
    status: StepStatus = StepStatus.PENDING
    detail: str = ""
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "detail": self.detail,
            "optional": self.optional,
        }


def _slug(title: str, index: int) -> str:
    cleaned = "".join(
        character.lower() if character.isalnum() else "_" for character in title
    ).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or f"step_{index}"


class TodoList:
    """An ordered set of :class:`TodoItem` objects.

    One step is ``ACTIVE`` at a time; finishing it activates the next pending
    step.  This keeps the progress card honest without the model having to
    micromanage indices.
    """

    def __init__(self, items: Iterable["TodoItem"] = ()) -> None:
        self._items: list[TodoItem] = []
        if items:
            self.replace(items)

    # -- construction -----------------------------------------------------

    def replace(self, items: Iterable[str | TodoItem], *, optional: Iterable[str] = ()) -> None:
        optional_titles = {title.strip().lower() for title in optional}
        steps: list[TodoItem] = []
        for index, item in enumerate(items):
            if isinstance(item, TodoItem):
                steps.append(item)
                continue
            title = str(item).strip()
            if not title:
                continue
            steps.append(
                TodoItem(
                    id=_slug(title, index),
                    title=title,
                    optional=title.lower() in optional_titles,
                )
            )
        self._items = steps
        self.activate_first()

    def add(self, title: str, *, key: str = "", optional: bool = False) -> TodoItem:
        step = TodoItem(
            id=key or _slug(title, len(self._items)),
            title=str(title).strip(),
            optional=optional,
        )
        self._items.append(step)
        return step

    def clear(self) -> None:
        self._items = []

    # -- access -----------------------------------------------------------

    @property
    def items(self) -> list[TodoItem]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def get(self, key: str) -> TodoItem | None:
        """Find a step by id or (case-insensitively) by title."""
        wanted = (key or "").strip().lower()
        if not wanted:
            return None
        for step in self._items:
            if step.id == wanted or step.title.lower() == wanted:
                return step
        return None

    def active(self) -> TodoItem | None:
        return next((step for step in self._items if step.status is StepStatus.ACTIVE), None)

    def next_pending(self) -> TodoItem | None:
        return next((step for step in self._items if step.status is StepStatus.PENDING), None)

    def unfinished(self) -> list[TodoItem]:
        return [step for step in self._items if step.status in (StepStatus.PENDING, StepStatus.ACTIVE)]

    def failed(self) -> list[TodoItem]:
        return [step for step in self._items if step.status is StepStatus.FAILED]

    # -- transitions --------------------------------------------------------

    def activate_first(self) -> TodoItem | None:
        """Make the first pending step active when nothing is active."""
        if self.active() is not None:
            return self.active()
        step = self.next_pending()
        if step is not None:
            step.status = StepStatus.ACTIVE
        return step

    def begin(self, key: str) -> TodoItem | None:
        """Mark one step active, leaving the others alone."""
        step = self.get(key)
        if step is None:
            return None
        if step.status is not StepStatus.DONE:
            step.status = StepStatus.ACTIVE
        return step

    def complete(self, key: str) -> TodoItem | None:
        step = self.get(key)
        if step is None:
            return None
        step.status = StepStatus.DONE
        return step

    def fail(self, key: str, reason: str = "") -> TodoItem | None:
        step = self.get(key)
        if step is None:
            return None
        step.status = StepStatus.FAILED
        if reason:
            step.detail = reason
        return step

    def skip(self, key: str) -> TodoItem | None:
        step = self.get(key)
        if step is None:
            return None
        step.status = StepStatus.SKIPPED
        return step

    def complete_active(self) -> TodoItem | None:
        """Finish the active step and activate the next one."""
        step = self.active()
        if step is None:
            step = self.next_pending()
            if step is None:
                return None
        step.status = StepStatus.DONE
        self.activate_first()
        return step

    def skip_remaining(self, *, detail: str = "") -> None:
        """Mark every outstanding step skipped (used when a run stops)."""
        for step in self.unfinished():
            step.status = StepStatus.SKIPPED
            if detail:
                step.detail = detail

    def fail_remaining(self, reason: str) -> None:
        for step in self.unfinished():
            step.status = StepStatus.FAILED
            step.detail = reason

    # -- reporting ----------------------------------------------------------

    def progress(self) -> tuple[int, int]:
        finished = sum(1 for step in self._items if step.status.is_finished)
        return finished, len(self._items)

    def is_complete(self) -> bool:
        """Whether every required step finished successfully."""
        if not self._items:
            return True
        return not self.unfinished() and not self._blocking_failures()

    def _blocking_failures(self) -> list[TodoItem]:
        return [step for step in self.failed() if not step.optional]

    def headline(self) -> str:
        finished, total = self.progress()
        if not total:
            return "No plan"
        if self.is_complete():
            return f"{total}/{total} steps complete"
        return f"{finished}/{total} steps"

    def render(self) -> str:
        """A plain-text checklist, used in prompts and diagnostics."""
        return "\n".join(
            f"{step.status.symbol} {step.title}"
            + (f" — {step.detail}" if step.detail else "")
            for step in self._items
        )

    def to_dict(self) -> dict[str, Any]:
        finished, total = self.progress()
        return {
            "steps": [step.to_dict() for step in self._items],
            "finished": finished,
            "total": total,
            "complete": self.is_complete(),
            "headline": self.headline(),
        }


def plan_title_for_effort(*, needs_edit: bool, workflow: bool, effort: AgentEffort) -> tuple[str, ...]:
    """Return the right plan template for a request and effort level."""
    if not needs_edit:
        return INSPECT_PLAN
    base = _EFFORT_TO_PLAN.get(effort, DEFAULT_EDIT_PLAN)
    if workflow:
        return tuple(t for t in base if t not in WORKFLOW_EXTRA_STEPS) + WORKFLOW_EXTRA_STEPS
    return base


def plan_titles_for_effort(*, needs_edit: bool, workflow: bool, effort: AgentEffort) -> list[str]:
    """Return the plan as a list of titles."""
    return list(plan_title_for_effort(needs_edit=needs_edit, workflow=workflow, effort=effort))


def plan_titles(*, needs_edit: bool, workflow: bool) -> tuple[str, ...]:
    """Return the right plan template for a request (legacy helper)."""
    if not needs_edit:
        return INSPECT_PLAN
    return WORKFLOW_EDIT_PLAN if workflow else DEFAULT_EDIT_PLAN


def compute_parent_plan(*, needs_edit: bool, workflow: bool, effort: AgentEffort) -> tuple[str, ...]:
    """Return the composite plan for a request and effort, with workflow steps first."""
    base = plan_title_for_effort(needs_edit=needs_edit, workflow=workflow, effort=effort)
    if workflow:
        return tuple(t for t in WORKFLOW_EXTRA_STEPS if t not in base) + base
    return base
