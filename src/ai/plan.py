"""Agent task planning: the todo list the user can watch.

A large request is not one action, it is a sequence of them. The agent keeps
that sequence explicit in a :class:`TodoList` so that

* the model gets a stable, visible plan to work through instead of drifting;
* the UI can show real progress (``✓ Find compatible nodes`` / ``● Build graph``);
* completion is decided by *step status and real tool results*, never by the
  model's own claim that it is finished.

Step status is driven by the host's tool results (see
:func:`ai.engine.AgentEngine`), so the list cannot drift away from reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


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
class PlanStep:
    """One step of the agent's plan."""

    id: str
    title: str
    status: StepStatus = StepStatus.PENDING
    detail: str = ""
    #: Steps that are nice to have: an unmet optional step is a warning, not a
    #: failure to complete the task.
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "detail": self.detail,
            "optional": self.optional,
        }


#: The plan used for a plain edit that needs no professional workflow research.
DEFAULT_EDIT_PLAN: tuple[str, ...] = (
    "Inspect the current graph",
    "Apply the requested changes",
    "Validate the result",
    "Organise the new nodes",
)

#: The plan used for a request that names a professional workflow. The first
#: steps are the workflow-understanding stage the design calls for: work out
#: how professionals do it, then find which Aphelion nodes implement that.
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


def plan_titles(*, needs_edit: bool, workflow: bool) -> tuple[str, ...]:
    """Return the right plan template for a request."""
    if not needs_edit:
        return INSPECT_PLAN
    return WORKFLOW_EDIT_PLAN if workflow else DEFAULT_EDIT_PLAN


def _slug(title: str, index: int) -> str:
    cleaned = "".join(
        character.lower() if character.isalnum() else "_" for character in title
    ).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or f"step_{index}"


class TodoList:
    """An ordered set of :class:`PlanStep` objects.

    The list is intentionally small and stateful: one step is ``ACTIVE`` at a
    time, and finishing it activates the next pending step. That keeps the
    progress card honest without the model having to micromanage indices.
    """

    def __init__(self, titles: Iterable[str] = ()) -> None:
        self._steps: list[PlanStep] = []
        if titles:
            self.replace(titles)

    # -- construction ---------------------------------------------------

    def replace(self, titles: Iterable[str | PlanStep], *, optional: Iterable[str] = ()) -> None:
        """Reset the list to ``titles`` (strings) or ``PlanStep`` objects."""
        optional_titles = {title.strip().lower() for title in optional}
        steps: list[PlanStep] = []
        for index, item in enumerate(titles):
            if isinstance(item, PlanStep):
                steps.append(item)
                continue
            title = str(item).strip()
            if not title:
                continue
            steps.append(
                PlanStep(
                    id=_slug(title, index),
                    title=title,
                    optional=title.lower() in optional_titles,
                )
            )
        self._steps = steps
        self.activate_first()

    def add(self, title: str, *, key: str = "", optional: bool = False) -> PlanStep:
        """Append a step; the id is derived from the title unless given."""
        step = PlanStep(
            id=key or _slug(title, len(self._steps)),
            title=str(title).strip(),
            optional=optional,
        )
        self._steps.append(step)
        return step

    def clear(self) -> None:
        self._steps = []

    # -- access ---------------------------------------------------------

    @property
    def steps(self) -> list[PlanStep]:
        return list(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def __iter__(self):
        return iter(self._steps)

    def get(self, key: str) -> PlanStep | None:
        """Find a step by id or (case-insensitively) by title."""
        wanted = (key or "").strip().lower()
        if not wanted:
            return None
        for step in self._steps:
            if step.id == wanted:
                return step
        for step in self._steps:
            if step.title.lower() == wanted:
                return step
        return None

    def active(self) -> PlanStep | None:
        return next((step for step in self._steps if step.status is StepStatus.ACTIVE), None)

    def next_pending(self) -> PlanStep | None:
        return next((step for step in self._steps if step.status is StepStatus.PENDING), None)

    def unfinished(self) -> list[PlanStep]:
        """Steps that still need doing (nothing done, skipped, or failed)."""
        return [
            step for step in self._steps
            if step.status in (StepStatus.PENDING, StepStatus.ACTIVE)
        ]

    def failed(self) -> list[PlanStep]:
        return [step for step in self._steps if step.status is StepStatus.FAILED]

    # -- transitions ----------------------------------------------------

    def activate_first(self) -> PlanStep | None:
        """Make the first pending step active when nothing is active."""
        if self.active() is not None:
            return self.active()
        step = self.next_pending()
        if step is not None:
            step.status = StepStatus.ACTIVE
        return step

    def begin(self, key: str) -> PlanStep | None:
        """Mark one step active, leaving the others alone."""
        step = self.get(key)
        if step is None:
            return None
        if step.status is not StepStatus.DONE:
            step.status = StepStatus.ACTIVE
        return step

    def complete(self, key: str) -> PlanStep | None:
        step = self.get(key)
        if step is None:
            return None
        step.status = StepStatus.DONE
        return step

    def fail(self, key: str, reason: str = "") -> PlanStep | None:
        step = self.get(key)
        if step is None:
            return None
        step.status = StepStatus.FAILED
        if reason:
            step.detail = reason
        return step

    def skip(self, key: str) -> PlanStep | None:
        step = self.get(key)
        if step is None:
            return None
        step.status = StepStatus.SKIPPED
        return step

    def complete_active(self) -> PlanStep | None:
        """Finish the active step and activate the next one.

        This is what real, successful tool work does to the plan.
        """
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

    # -- reporting ------------------------------------------------------

    def progress(self) -> tuple[int, int]:
        """``(finished, total)`` counting steps that are done or skipped."""
        finished = sum(1 for step in self._steps if step.status.is_finished)
        return finished, len(self._steps)

    def is_complete(self) -> bool:
        """Whether every required step finished successfully."""
        if not self._steps:
            return True
        return not self.unfinished() and not self._blocking_failures()

    def _blocking_failures(self) -> list[PlanStep]:
        return [step for step in self.failed() if not step.optional]

    def headline(self) -> str:
        """One line describing the plan's state, e.g. ``4/8 steps``."""
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
            for step in self._steps
        )

    def to_dict(self) -> dict[str, Any]:
        finished, total = self.progress()
        return {
            "steps": [step.to_dict() for step in self._steps],
            "finished": finished,
            "total": total,
            "complete": self.is_complete(),
            "headline": self.headline(),
        }


__all__ = [
    "DEFAULT_EDIT_PLAN",
    "INSPECT_PLAN",
    "WORKFLOW_EDIT_PLAN",
    "PlanStep",
    "StepStatus",
    "TodoList",
    "plan_titles",
]
