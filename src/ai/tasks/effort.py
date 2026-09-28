"""Effort-level abstraction for the AI assistant.

Effort controls how thoroughly the agent inspects, how much it validates, and
how verbose its completion summary is.  It is *not* a speed cap: the agent
still does the same work, it just chooses which checks matter.  Choose a
higher effort when the request is creative, ambiguous, or safety-critical;
choose a lower effort for mechanical edits.

    AUTO     -> classify the request and pick a level automatically.
    FAST     -> minimal source retrieval, minimal visual QA, minimal workflow
                research, quick execution.
    NORMAL   -> default: real project inspection, real node docs, validation,
                basic QA.
    EXPERT   -> deeper professional-workflow analysis, source inspection,
                more frame analysis, stronger visual QA, tracking diagnostics,
                fuller completion summary.
    MAXIMUM  -> extensive inspection, broad real-world research, more source
                retrieval, multiple visual-QA passes, more frames, iterative
                refinement, strongest final validation.

Effort is shown in the AI header/composer as a dropdown chip:

    Effort: Expert ▾
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai.workflows import is_workflow_request

# ---------------------------------------------------------------------------
# Effort levels
# ---------------------------------------------------------------------------

class AgentEffort(str, Enum):
    AUTO = "auto"
    FAST = "fast"
    NORMAL = "normal"
    EXPERT = "expert"
    MAXIMUM = "maximum"

    @property
    def label(self) -> str:
        return {
            AgentEffort.AUTO: "Auto",
            AgentEffort.FAST: "Fast",
            AgentEffort.NORMAL: "Normal",
            AgentEffort.EXPERT: "Expert",
            AgentEffort.MAXIMUM: "Maximum",
        }[self]

    @property
    def description(self) -> str:
        return {
            AgentEffort.AUTO: "Classify the request and pick a level automatically.",
            AgentEffort.FAST: "Minimal inspection, quick execution.",
            AgentEffort.NORMAL: "Default: proper project inspection, real node docs, validation, basic QA.",
            AgentEffort.EXPERT: "Deeper professional-workflow analysis, frame analysis, stronger QA.",
            AgentEffort.MAXIMUM: "Most thorough: extensive inspection, more QA passes, iterative refinement.",
        }[self]

    @property
    def rank(self) -> int:
        return {
            AgentEffort.AUTO: 0,
            AgentEffort.FAST: 1,
            AgentEffort.NORMAL: 2,
            AgentEffort.EXPERT: 3,
            AgentEffort.MAXIMUM: 4,
        }[self]

    @property
    def minimises_worry(self) -> bool:
        return self.rank <= AgentEffort.NORMAL.rank


# ---------------------------------------------------------------------------
# String conversion
# ---------------------------------------------------------------------------

def effort_from_string(text: str) -> AgentEffort:
    """Parse a user-facing effort token into an effort level."""
    cleaned = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    if not cleaned:
        return AgentEffort.AUTO
    for effort in (AgentEffort.AUTO, AgentEffort.FAST, AgentEffort.NORMAL,
                   AgentEffort.EXPERT, AgentEffort.MAXIMUM):
        if effort.value in cleaned or effort.label.lower() in cleaned:
            return effort
    # Last resort: normal.
    return AgentEffort.NORMAL


def effort_rank(text: str) -> int:
    """Numeric rank of a user-facing effort hint (0 = lowest)."""
    return effort_from_string(text).rank


# ---------------------------------------------------------------------------
# Intent classification for effort selection
# ---------------------------------------------------------------------------

_EDIT_HINTS = re.compile(
    r"\b(add|create|insert|build|make|set|change|adjust|increase|decrease|"
    r"connect|wire|rewire|disconnect|delete|remove|move|rename|"
    r"fix|repair|optimize|organize|apply|use|replace|improve)\b",
    re.I,
)
_QUESTION_HINT = re.compile(
    r"^\s*(?:what|why|how|which|who|whose|where|when|explain|describe|tell me|"
    r"does|do|did|is|are|was|were|list|show me)\b",
    re.I,
)
_EFFORT_HINTS = {
    AgentEffort.FAST: [
        "quick", "fast", "simple", "minor", "small", "quickly", "do it",
        "just do it", "delete it", "move it", "rename it",
    ],
    AgentEffort.NORMAL: [
        "normal", "standard", "default", "usual", "typical",
    ],
    AgentEffort.EXPERT: [
        "expert", "professional", "advanced", "thorough", "careful",
        "best quality", "quality", "good", "proper", "serious", "important",
        "must be right", "high quality", "cinematic", "film look", "filmic",
        "track properly", "stabilise", "grade",
    ],
    AgentEffort.MAXIMUM: [
        "maximum", "max", "full", "thoroughly", "most", "complete", "every",
        "all possible", "deep", "rigorous", "highest", "ultimate", "maximal",
        "a lot", "thoroughly inspect", "multiple passes", "iterative",
    ],
}


def _apply_hint_ratings(objective: str, effort: AgentEffort, scores: dict[AgentEffort, int]) -> None:
    text = objective or ""
    lowered = text.lower()
    for hint in _EFFORT_HINTS[effort]:
        if hint in lowered:
            scores[effort] += 2
    # Positive signals: a higher effort is requested by the wording.
    for effort, hints in _EFFORT_HINTS.items():
        for hint in hints:
            if hint in lowered:
                scores[effort] += 1
    # Workflow recognition: creative tasks merit more inspection.
    if is_workflow_request(text):
        scores[AgentEffort.NORMAL] += 1
        scores[AgentEffort.EXPERT] += 1
        scores[AgentEffort.MAXIMUM] += 1


def classify_intent_for_effort(objective: str, *, default: AgentEffort = AgentEffort.NORMAL) -> tuple[AgentEffort, str]:
    """Return ``(effort, rationale)`` for a user request.

    The intent classification is deliberately cheap and interpretable: we
    look for edit verbs, question words, and explicit effort hints, then rank
    the levels with a small set of rules.  The winning level is used unless
    the request explicitly asks for a specific one (in which case we honour
    that level and note it).
    """
    text = objective or ""
    if not text.strip():
        return default, "empty request - using normal effort"

    # Honour an explicit effort hint.
    for hint in re.findall(r"effort\s*[=:]\s*([A-Za-z]+)", text, re.I):
        parsed = effort_from_string(hint)
        if parsed is not AgentEffort.AUTO:
            return parsed, f"explicit effort hint '{hint}'"

    # Harvest a quick score.
    scores: dict[AgentEffort, int] = {effort: 0 for effort in AgentEffort}
    if _QUESTION_HINT.match(text):
        scores[AgentEffort.FAST] = 0
        scores[AgentEffort.NORMAL] = 1
        scores[AgentEffort.EXPERT] = 1
        scores[AgentEffort.MAXIMUM] = 1
        return AgentEffort.NORMAL, "question - default effort"
    if _EDIT_HINTS.search(text):
        scores[AgentEffort.NORMAL] += 2
    for effort in (AgentEffort.FAST, AgentEffort.NORMAL, AgentEffort.EXPERT, AgentEffort.MAXIMUM):
        _apply_hint_ratings(text, effort, scores)

    best = max(scores, key=lambda e: scores[e])
    # Don't upgrade beyond normal for trivial one-word edits.
    if best.rank > AgentEffort.NORMAL.rank and _EDIT_HINTS.search(text) and re.search(r"\b(delete|move|rename|fix)\b", text, re.I):
        if "quick" in text.lower() or "fast" in text.lower() or "minor" in text.lower() or "small" in text.lower():
            best = AgentEffort.FAST
    return best, f"classified intent={scores}"


# ---------------------------------------------------------------------------
# Task tags (machine-readable summary of what effort implies)
# ---------------------------------------------------------------------------

@dataclass
class TaskTags:
    """Structural summary of what this effort will do."""
    effort: AgentEffort
    will_inspect_graph: bool
    will_retrieve_node_docs: bool
    will_validate: bool
    will_run_visual_qa: bool
    will_run_workspace_research: bool
    will_update_tracker_diagnostics: bool
    will_add_completion_summary: bool
    will_retrieve_source: bool
    will_iteratively_refine: bool
    will_check_multiple_frames: bool
    will_check_skin_tones: bool
    will_check_clipping: bool
    will_check_consistency: bool
    will_check_playback: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "effort": self.effort.value,
            "will_inspect_graph": self.will_inspect_graph,
            "will_retrieve_node_docs": self.will_retrieve_node_docs,
            "will_validate": self.will_validate,
            "will_run_visual_qa": self.will_run_visual_qa,
            "will_run_workspace_research": self.will_run_workspace_research,
            "will_update_tracker_diagnostics": self.will_update_tracker_diagnostics,
            "will_add_completion_summary": self.will_add_completion_summary,
            "will_retrieve_source": self.will_retrieve_source,
            "will_iteratively_refine": self.will_iteratively_refine,
            "will_check_multiple_frames": self.will_check_multiple_frames,
            "will_check_skin_tones": self.will_check_skin_tones,
            "will_check_clipping": self.will_check_clipping,
            "will_check_consistency": self.will_check_consistency,
            "will_check_playback": self.will_check_playback,
        }


def compute_task_tags(objective: str, effort: AgentEffort) -> dict[str, Any]:
    """Compute a machine-readable tag set for an effort level."""
    if effort.rank <= AgentEffort.FAST.rank:
        return TaskTags(
            effort=effort,
            will_inspect_graph=False,
            will_retrieve_node_docs=False,
            will_validate=False,
            will_run_visual_qa=False,
            will_run_workspace_research=False,
            will_update_tracker_diagnostics=False,
            will_add_completion_summary=True,
            will_retrieve_source=False,
            will_iteratively_refine=False,
            will_check_multiple_frames=False,
            will_check_skin_tones=False,
            will_check_clipping=False,
            will_check_consistency=False,
            will_check_playback=False,
        ).to_dict()
    if effort.rank <= AgentEffort.NORMAL.rank:
        return TaskTags(
            effort=effort,
            will_inspect_graph=True,
            will_retrieve_node_docs=True,
            will_validate=True,
            will_run_visual_qa=True,
            will_run_workspace_research=False,
            will_update_tracker_diagnostics=False,
            will_add_completion_summary=True,
            will_retrieve_source=False,
            will_iteratively_refine=False,
            will_check_multiple_frames=False,
            will_check_skin_tones=False,
            will_check_clipping=False,
            will_check_consistency=False,
            will_check_playback=False,
        ).to_dict()
    if effort.rank <= AgentEffort.EXPERT.rank:
        return TaskTags(
            effort=effort,
            will_inspect_graph=True,
            will_retrieve_node_docs=True,
            will_validate=True,
            will_run_visual_qa=True,
            will_run_workspace_research=True,
            will_update_tracker_diagnostics=True,
            will_add_completion_summary=True,
            will_retrieve_source=True,
            will_iteratively_refine=True,
            will_check_multiple_frames=True,
            will_check_skin_tones=True,
            will_check_clipping=True,
            will_check_consistency=True,
            will_check_playback=True,
        ).to_dict()
    # MAXIMUM
    return TaskTags(
        effort=effort,
        will_inspect_graph=True,
        will_retrieve_node_docs=True,
        will_validate=True,
        will_run_visual_qa=True,
        will_run_workspace_research=True,
        will_update_tracker_diagnostics=True,
        will_add_completion_summary=True,
        will_retrieve_source=True,
        will_iteratively_refine=True,
        will_check_multiple_frames=True,
        will_check_skin_tones=True,
        will_check_clipping=True,
        will_check_consistency=True,
        will_check_playback=True,
    ).to_dict()


# ---------------------------------------------------------------------------
# Effort-aware tool visibility
# ---------------------------------------------------------------------------

def tool_visibility_for_effort(effort: AgentEffort, *, registry_visible: bool = False) -> dict[str, bool]:
    """Return which tools are shown to the user for a given effort level."""
    if effort.rank <= AgentEffort.FAST.rank:
        return {name: False for name in registry_visible}
    if effort.rank <= AgentEffort.NORMAL.rank:
        return {name: True for name in registry_visible}
    if effort.rank <= AgentEffort.EXPERT.rank:
        return {name: True for name in registry_visible}
    # MAXIMUM
    return {name: True for name in registry_visible}


# ---------------------------------------------------------------------------
# Effort -> confidence classification (auto)
# ---------------------------------------------------------------------------

#: Keywords that strongly push toward a higher effort because the request is
#: creative, ambiguous, or safety-critical.
_CREATIVE_ULTIMATE_HINTS = (
    "cinematic", "film look", "looks better", "beautiful", "stunning", "more",
    "better", "fix it properly", "quality", "grade", "color grade", "exposure",
    "contrast", "saturation", "filmic", "moody", "color correct",
    "track this properly", "stabilise", "make it match", "make it blend",
)
#: Keywords that indicate a mechanical edit worth less inspection.
_MECHANICAL_HINTS = (
    "delete", "remove", "hide", "show", "lock", "unlock", "toggle",
    "toggle visibility", "reorder", "move to", "rename to", "duplicate",
    "turn off", "disable",
)
#: Keywords that indicate a safety-critical visual check.
_VISUAL_SAFETY_HINTS = (
    "clip", "clipping", "blur", "crash", "break", "broken", "stutter",
    "freeze", "black frame", "noise", "banding", "flicker", "glitch",
    "artifact", "distorted", "out of range", "wrong value",
)


def resolve_effort_cv(objective: str) -> AgentEffort:
    """Classify a request and pick an effort level (auto)."""
    text = objective or ""
    if not text.strip():
        return AgentEffort.NORMAL
    lowered = text.lower()

    # Explicit overrides win.
    for effort in (AgentEffort.AUTO, AgentEffort.FAST, AgentEffort.NORMAL, AgentEffort.EXPERT, AgentEffort.MAXIMUM):
        if re.search(rf"effort\s*[=:]?\s*{effort.value}", lowered):
            return effort

    # Safety-critical visual checks -> look harder.
    if any(hint in lowered for hint in _VISUAL_SAFETY_HINTS):
        if any(hint in lowered for hint in _VISUAL_SAFETY_HINTS):
            return AgentEffort.MAXIMUM

    # Creative / filmic requests -> normal to expert.
    if any(hint in lowered for hint in _CREATIVE_ULTIMATE_HINTS):
        return AgentEffort.EXPERT

    # Mechanical edits -> fast.
    if any(hint in lowered for hint in _MECHANICAL_HINTS):
        return AgentEffort.FAST

    # Default for ordinary edits.
    return AgentEffort.NORMAL


# ---------------------------------------------------------------------------
# Effort-aware visual QA gating
# ---------------------------------------------------------------------------

def should_run_visual_qa(effort: AgentEffort) -> bool:
    """True when the effort requires real frame inspection."""
    return effort.rank >= AgentEffort.NORMAL.rank


def should_run_workspace_research(effort: AgentEffort) -> bool:
    """True when the effort warrants deeper source/workflow research."""
    return effort.rank >= AgentEffort.EXPERT.rank


# ---------------------------------------------------------------------------
# Level helpers
# ---------------------------------------------------------------------------

def effort_to_level(effort: AgentEffort) -> str:
    """Return a short level label, e.g. ``Auto • Expert``."""
    if effort is AgentEffort.AUTO:
        return "Auto"
    return effort.label


def level_to_score(level: str) -> int:
    """Map a level name back to a numeric score (0 = fastest)."""
    return effort_from_string(level).rank
