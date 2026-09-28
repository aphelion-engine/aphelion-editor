"""Effort-aware agent task planning: classifications, effort levels, planning,
visual QA, and workspace research.

This package is pure Python (no Qt) so it can be imported from both the agent
engine and the UI without creating a dependency cycle.
"""

from __future__ import annotations

from .effort import (AgentEffort, classify_intent_for_effort, compute_task_tags,
                     effort_from_string, effort_rank, effort_to_level,
                     resolve_effort_cv, should_run_visual_qa, should_run_workspace_research,
                     tool_visibility_for_effort)
from .plan import (EffortPlan, plan_titles_for_effort, StepStatus, TodoItem,
                   compute_parent_plan, plan_titles, TodoList)
from .visual_qa import (VisualQAOption, compute_visual_qa_strategy,
                        inspect_frames, should_run_visual_qa)

__all__ = [
    # effort
    "AgentEffort",
    "classify_intent_for_effort",
    "compute_task_tags",
    "effort_from_string",
    "effort_rank",
    "effort_to_level",
    "resolve_effort_cv",
    "should_run_visual_qa",
    "should_run_workspace_research",
    "tool_visibility_for_effort",
    # plan
    "EffortPlan",
    "plan_titles_for_effort",
    "StepStatus",
    "TodoItem",
    "compute_parent_plan",
    "plan_titles",
    "TodoList",
    # visual_qa
    "VisualQAOption",
    "compute_visual_qa_strategy",
    "inspect_frames",
    "should_run_visual_qa",
]
