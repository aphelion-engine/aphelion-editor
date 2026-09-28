"""Visual QA support for the AI assistant.

The engine must not claim visual QA occurred unless frames were actually
provided to a vision-capable model or tool.  This module is the policy layer:

* :func:`should_run_visual_qa` decides whether the effort level warrants
  frame inspection.
* :func:`compute_visual_qa_strategy` decides which checks to run and which
  frames to inspect.
* :func:`inspect_frames` performs the actual work and returns structured
  findings (often consumed by a vision tool that answers a scored question).

The engine itself is thread-safe: workers may call these helpers, but the
*worker thread* is the only one that holds the frame data and the vision
model.  All Qt UI updates happen on the main thread through the event bus.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai.tasks import AgentEffort

_LOG = logging.getLogger("aphelion.tasks.visual_qa")


class VisualQAAspect(Enum):
    """One thing that can be checked when grading a shot."""
    SHADOWS = "shadows"
    HIGHLIGHTS = "highlights"
    CONTRAST = "contrast"
    CLIPPING = "clipping"
    SATURATION = "saturation"
    SKIN_TONES = "skin_tones"
    CONSISTENCY = "consistency"
    EXPOSURE = "exposure"
    COLOR_TEMPERATURE = "color_temperature"
    LOCAL_CONTRAST = "local_contrast"

    def label(self) -> str:
        return {
            VisualQAAspect.SHADOWS: "Shadows",
            VisualQAAspect.HIGHLIGHTS: "Highlights",
            VisualQAAspect.CONTRAST: "Contrast",
            VisualQAAspect.CLIPPING: "Clipping",
            VisualQAAspect.SATURATION: "Saturation",
            VisualQAAspect.SKIN_TONES: "Skin tones",
            VisualQAAspect.CONSISTENCY: "Consistency across clip",
            VisualQAAspect.EXPOSURE: "Exposure",
            VisualQAAspect.COLOR_TEMPERATURE: "Color temperature",
            VisualQAAspect.LOCAL_CONTRAST: "Local contrast",
        }[self]


@dataclass(frozen=True)
class VisualQAFrame:
    """One representative frame inspected by the engine or a vision tool."""
    frame: int
    reason: str
    aspect: VisualQAAspect
    score: float = 0.0   # -1.0 (bad) -> 1.0 (good), confidence in the score
    note: str = ""


@dataclass(frozen=True)
class VisualQAStrategy:
    """What the engine will inspect, given the job and the effort."""
    aspects: tuple[VisualQAAspect, ...]
    frames: tuple[int, ...]
    require_vision_model: bool
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspects": [a.value for a in self.aspects],
            "frames": list(self.frames),
            "require_vision_model": self.require_vision_model,
            "purpose": self.purpose,
        }


def compute_visual_qa_strategy(objective: str, effort: AgentEffort) -> VisualQAStrategy:
    """Choose a visual QA plan based on the request and the effort level."""
    text = objective or ""
    low = text.lower()

    is_grading = any(word in low for word in (
        "cinematic", "color grade", "grade", "film look", "look more",
        "exposure", "contrast", "saturation", "clip", "overall look",
    ))
    is_tracking = any(word in low for word in (
        "track", "motion", "follow", "stabilise", "stabilize", "drift",
        "jitter", "freeze", "match move", "planar",
    ))
    is_composite_replace = any(word in low for word in (
        "replace", "composite", "remove", "key", "green screen", "background",
    ))
    is_trivial = any(word in low for word in (
        "delete", "remove", "hide", "show", "toggle", "lock", "rename", "move",
        "duplicate", "reorder",
    ))

    # Trivial edits need no visual QA.
    if is_trivial:
        return VisualQAStrategy(
            aspects=(),
            frames=(),
            require_vision_model=False,
            purpose="not needed - mechanical edit",
        )

    if effort.rank <= AgentEffort.FAST.rank:
        return VisualQAStrategy(
            aspects=(),
            frames=(),
            require_vision_model=False,
            purpose="skipped - fast effort",
        )

    # Grading: check the classic chain plus skin tones where visible.
    if is_grading:
        aspects = (
            VisualQAAspect.CONTRAST,
            VisualQAAspect.SHADOWS,
            VisualQAAspect.HIGHLIGHTS,
            VisualQAAspect.CLIPPING,
            VisualQAAspect.SATURATION,
            VisualQAAspect.SKIN_TONES,
            VisualQAAspect.CONSISTENCY,
        )
        frames = (0, len(text) // 2, len(text) - 1) if len(text) > 2 else (0,)
        return VisualQAStrategy(
            aspects=aspects,
            frames=frames,
            require_vision_model=True,
            purpose="grade visual QA",
        )

    # Tracking: verify the track stayed locked through the frame range.
    if is_tracking:
        aspects = (VisualQAAspect.CONSISTENCY, VisualQAAspect.SHADOWS, VisualQAAspect.HIGHLIGHTS)
        frames = (0, len(text) // 2, len(text) - 1) if len(text) > 2 else (0,)
        return VisualQAStrategy(
            aspects=aspects,
            frames=frames,
            require_vision_model=True,
            purpose="tracking visual QA",
        )

    # General creative edits look at the whole clip.
    aspects = (
        VisualQAAspect.SHADOWS,
        VisualQAAspect.HIGHLIGHTS,
        VisualQAAspect.CONTRAST,
        VisualQAAspect.CLIPPING,
        VisualQAAspect.SATURATION,
        VisualQAAspect.CONSISTENCY,
    )
    frames = (0, len(text) // 2, len(text) - 1) if len(text) > 2 else (0,)
    return VisualQAStrategy(
        aspects=aspects,
        frames=frames,
        require_vision_model=True,
        purpose="creative edit visual QA",
    )


def should_run_visual_qa(effort: AgentEffort, objective: str) -> bool:
    """True when the combination of effort and objective warrants visual QA."""
    if effort.rank <= AgentEffort.FAST.rank:
        return False
    return True


# ---------------------------------------------------------------------------
# Frame inspection
# ---------------------------------------------------------------------------

def inspect_frames(
    *,
    frames: list[VisualQAFrame] | None = None,
    strategy: VisualQAStrategy | None = None,
    vision_model: Any | None = None,
    project: Any | None = None,
) -> dict[str, Any]:
    """Run visual QA and return structured findings.

    The most common usage is::

        findings = inspect_frames(
            project=project,
            strategy=compute_visual_qa_strategy(objective, effort),
            vision_model=vision_model,
        )

    The ``vision_model`` is a callable that accepts one or more frames and a
    question, and returns a plain-text answer.  If it is ``None``, the call
    degrades to a summary that only reports which frames *would* have been
    inspected.  The function never raises: it logs and returns a ``ok``
    result.

    The return value can be fed straight into the engine's event bus as a
    ``VISUAL_QA_RESULT`` event.
    """
    if strategy is None:
        strategy = compute_visual_qa_strategy("", AgentEffort.NORMAL)

    frames_to_inspect = frames or []
    findings = {
        "strategy": strategy.to_dict(),
        "frames_inspected": [f.frame for f in frames_to_inspect],
        "aspects": [a.value for a in strategy.aspects],
        "results": {},
        "overall": "not run - no vision model",
        "ok": False,
    }

    if vision_model is None or not frames_to_inspect:
        _LOG.info(
            "Visual QA skipped: strategy=%r frames=%r vision_model=%r",
            strategy, frames_to_inspect, vision_model is not None,
        )
        findings["overall"] = "not run - no frames or no vision model"
        return findings

    # Collect the frames the strategy wants to inspect, in order.
    requested_frames = set(strategy.frames)
    visited: list[VisualQAFrame] = []
    for frame in requested_frames:
        hit = next((f for f in frames_to_inspect if f.frame == frame), None)
        if hit is not None:
            visited.append(hit)

    if not visited:
        _LOG.warning(
            "No frames supplied that match strategy frames %r", list(requested_frames)
        )
        findings["results"] = {"note": "No supplied frames matched the requested frames."}
        return findings

    # Build a compact inspection target per frame (the actual data lives on
    # the vision model's side; we only pass what it needs).
    inspection_requests = []
    for frame in visited:
        question = (
            f"Frame {frame.frame}: report {', '.join(a.label().lower() for a in strategy.aspects)}. "
            f"Note any clipping, skin-tone problems, or inconsistency."
        )
        inspection_requests.append((frame, question))

    try:
        results = vision_model(inspection_requests)
        if results is None:
            results = {}
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("Visual QA vision model raised: %s", exc)
        results = {"error": f"Vision model failed: {exc}"}

    findings["results"] = results
    findings["frames_inspected"] = [f.frame for f in visited]

    if isinstance(results, dict) and results.get("error"):
        findings["overall"] = results["error"]
        return findings

    # Score the inspection: an aggregate of the individual frame answers.
    overall = _summarise_findings(results, strategy.aspects, visited)
    findings["overall"] = overall
    findings["ok"] = overall.get("pass", False)
    return findings


def _summarise_findings(
    results: dict[str, Any],
    aspects: tuple[VisualQAAspect, ...],
    frames: list[VisualQAFrame],
) -> dict[str, Any]:
    """Turn raw vision-model answers into a concise, machine-readable summary."""
    per_aspect: dict[str, dict[str, Any]] = {}
    for aspect in aspects:
        per_aspect[aspect.value] = {"pass": True, "score": 0.0, "note": []}

    if not isinstance(results, dict):
        return {"pass": False, "note": "Vision result was not a dict."}

    for aspect in aspects:
        answer = results.get(aspect.value, "")
        if not answer:
            per_aspect[aspect.value]["pass"] = False
            per_aspect[aspect.value]["note"].append("no answer provided")
        else:
            combined = " ".join(str(answer).lower().split())
            clipping = any(word in combined for word in ("clip", "clipping", "blown", "overexposed"))
            if clipping:
                per_aspect[aspect.value]["pass"] = False
                per_aspect[aspect.value]["note"].append("clipping reported")

    total_aspect = len(aspects)
    passed = sum(1 for a in aspects if per_aspect[a.value]["pass"])
    overall = {
        "pass": passed == total_aspect,
        "checked": total_aspect,
        "passed": passed,
        "failed": total_aspect - passed,
        "per_aspect": per_aspect,
        "frames_inspected": [f.frame for f in frames],
        "note": f"Checked {passed}/{total_aspect} aspect(s)." if total_aspect else "No aspects checked.",
    }
    return overall
