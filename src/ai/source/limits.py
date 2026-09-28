"""Context budgets for source retrieval.

Kept dependency-free on purpose: :mod:`ai.settings` imports this module, and
loading the assistant's settings must never pull in the indexer, the node
registry, or a provider.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from ai.errors import SourceAccessError


@dataclass
class SourceLimits:
    """Hard ceilings that keep retrieval from exploding the context window."""

    #: Files returned by one search or symbol read.
    max_files_per_call: int = 4
    #: Characters of any single file that may be returned.
    max_chars_per_file: int = 12_000
    #: Characters of source across one tool call.
    max_chars_per_call: int = 24_000
    #: Characters of source across one agent run (all tool calls).
    max_chars_per_turn: int = 60_000
    #: Number of separate source reads one run may perform. Bounds a looping
    #: or prompt-injected agent even when each individual read is tiny.
    max_reads_per_turn: int = 40
    #: Candidate files a search may consider reporting.
    max_search_hits: int = 25
    #: Lines of context shown around a search hit.
    context_lines: int = 6

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_files_per_call": self.max_files_per_call,
            "max_chars_per_file": self.max_chars_per_file,
            "max_chars_per_call": self.max_chars_per_call,
            "max_chars_per_turn": self.max_chars_per_turn,
            "max_reads_per_turn": self.max_reads_per_turn,
            "max_search_hits": self.max_search_hits,
            "context_lines": self.context_lines,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SourceLimits:
        data = data or {}
        return cls(
            max_files_per_call=_clamp(data.get("max_files_per_call"), 1, 20, 4),
            max_chars_per_file=_clamp(
                data.get("max_chars_per_file"), 500, 200_000, 12_000
            ),
            max_chars_per_call=_clamp(
                data.get("max_chars_per_call"), 1_000, 400_000, 24_000
            ),
            max_chars_per_turn=_clamp(
                data.get("max_chars_per_turn"), 2_000, 2_000_000, 60_000
            ),
            max_reads_per_turn=_clamp(data.get("max_reads_per_turn"), 1, 500, 40),
            max_search_hits=_clamp(data.get("max_search_hits"), 1, 200, 25),
            context_lines=_clamp(data.get("context_lines"), 0, 60, 6),
        )


def _clamp(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


class SourceBudget:
    """Per-run accounting for how much source has been handed to the model."""

    def __init__(self, limits: SourceLimits | None = None) -> None:
        self.limits = limits or SourceLimits()
        self.spent_chars = 0
        self.reads = 0
        self._lock = threading.Lock()

    def check(self, chars: int) -> None:
        """Raise when one more read would exceed the per-turn budget."""
        with self._lock:
            if self.reads >= self.limits.max_reads_per_turn:
                raise SourceAccessError(
                    "This request has already made as many source reads as one "
                    f"turn allows ({self.limits.max_reads_per_turn}). Send a new "
                    "message to reset the budget, and ask a more specific "
                    "question.",
                    code="SOURCE_BUDGET_EXCEEDED",
                )
            if self.spent_chars + chars > self.limits.max_chars_per_turn:
                raise SourceAccessError(
                    "This request has already retrieved as much source as one "
                    f"turn is allowed ({self.limits.max_chars_per_turn} "
                    "characters). Ask a narrower question, or send a new "
                    "message to reset the budget.",
                    code="SOURCE_BUDGET_EXCEEDED",
                )

    def spend(self, chars: int) -> None:
        with self._lock:
            self.spent_chars += chars
            self.reads += 1

    def state(self) -> dict[str, Any]:
        return {
            "spent_chars": self.spent_chars,
            "limit": self.limits.max_chars_per_turn,
            "reads": self.reads,
            "read_limit": self.limits.max_reads_per_turn,
        }


__all__ = ["SourceBudget", "SourceLimits"]
