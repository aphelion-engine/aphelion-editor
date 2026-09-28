"""Playback tools: where the playhead is, and which frames are worth looking at.

An assistant that only sees "the current frame" cannot tell whether a track
held together, so it needs the timeline's shape and a cheap way to choose
representative frames. These tools expose the real project state
(``project.current_frame``, fps, duration, the timeline's in/out points) and a
sampling helper that returns frames worth inspecting rather than every frame.

Moving the playhead is a viewing action, not a document edit: it creates no
undo step and changes no node, property, or connection.
"""

from __future__ import annotations

from ai.errors import ToolError
from ai.graph_model import project_summary
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.types import Permission, ToolResult


def register_tools(registry: ToolRegistry) -> None:
    """Register the playback.* tools."""

    registry.register(
        ToolSpec(
            name="playback.get_state",
            description=(
                "Report the timeline's real state: current frame, frame rate, "
                "duration, frame count, the timeline in/out points, and which "
                "viewer is active. Check this before animating or sampling "
                "frames so frame numbers are in range."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_get_state,
            mutates=False,
            category="Playback",
        )
    )

    registry.register(
        ToolSpec(
            name="playback.seek",
            description=(
                "Move the playhead to a frame so the viewer (and any vision "
                "tool) shows that moment. This does not edit the project and "
                "creates no undo step."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "frame": {"type": "integer", "description": "Frame to seek to."},
                },
                "required": ["frame"],
                "additionalProperties": False,
            },
            permission=Permission.READ_PROJECT,
            handler=_seek,
            mutates=False,
            category="Playback",
        )
    )

    registry.register(
        ToolSpec(
            name="playback.sample_frames",
            description=(
                "Choose representative frames across the timeline instead of "
                "inspecting every frame: evenly spaced samples between the "
                "in/out points, plus the first and last frame. Use the result "
                "with the vision tools to check a tracking or effect result, "
                "then compare what you actually saw across those frames."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "How many frames to sample (default 5).",
                        "minimum": 2,
                        "maximum": 24,
                    },
                    "from_frame": {
                        "type": "integer",
                        "description": "Override the first frame to sample.",
                    },
                    "to_frame": {
                        "type": "integer",
                        "description": "Override the last frame to sample.",
                    },
                },
            },
            permission=Permission.READ_PROJECT,
            handler=_sample_frames,
            mutates=False,
            category="Playback",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _frame_bounds(ctx: ToolContext) -> tuple[int, int, str]:
    """Return ``(first, last, source)`` for the frames worth sampling."""
    project = ctx.project
    last_frame = int(getattr(project, "max_frame", 0) or 0)
    start, end = None, None
    try:
        start, end = ctx.host.timeline_range()
    except Exception:  # noqa: BLE001 - a host without a timeline is fine
        start, end = None, None
    if start is not None and end is not None and int(end) > int(start):
        return int(start), int(end), "timeline in/out"
    return 0, last_frame, "full clip"


def _get_state(ctx: ToolContext) -> ToolResult:
    project = ctx.project
    summary = project_summary(project)
    # Media paths are gated behind ACCESS_MEDIA elsewhere; keep this payload
    # about timing only.
    summary.pop("media", None)

    first, last, source = _frame_bounds(ctx)
    active_viewer = summary.get("active_viewer")
    summary.update(
        {
            "sample_range": {"first": first, "last": last, "source": source},
            "playhead_is_within_range": first <= int(project.current_frame) <= last,
            "active_viewer": active_viewer,
            "can_step_frames": hasattr(ctx.host, "set_current_frame"),
            "can_render_frames": hasattr(ctx.host, "render_preview_frame"),
        }
    )
    return ToolResult(
        ok=True,
        summary=(
            f"Frame {summary['current_frame']} of {summary['frame_count']} "
            f"at {summary['fps']} fps; sampling range {first}–{last} ({source})."
        ),
        data=summary,
    )


def _seek(ctx: ToolContext) -> ToolResult:
    project = ctx.project
    frame = int(ctx.args["frame"])
    last = int(getattr(project, "max_frame", 0) or 0)
    if frame < 0 or frame > last:
        raise ToolError(
            "FRAME_OUT_OF_RANGE",
            f"Frame {frame} is outside the project's range (0–{last}).",
        )
    if not hasattr(ctx.host, "set_current_frame"):
        raise ToolError(
            "FEATURE_UNAVAILABLE",
            "This host cannot move the playhead.",
        )
    ctx.host.set_current_frame(frame)
    previous = int(getattr(project, "current_frame", frame))
    return ToolResult(
        ok=True,
        summary=f"Moved the playhead to frame {frame}.",
        data={"frame": frame, "previous_frame": previous},
    )


def _sample_frames(ctx: ToolContext) -> ToolResult:
    project = ctx.project
    count = int(ctx.args.get("count", 5) or 5)
    count = max(2, min(count, 24))

    first = ctx.args.get("from_frame")
    last = ctx.args.get("to_frame")
    source = "explicit range"
    if first is None or last is None:
        first, last, source = _frame_bounds(ctx)
    first, last = int(first), int(last)
    if last < first:
        raise ToolError(
            "INVALID_ARGUMENT",
            f"to_frame ({last}) must not be before from_frame ({first}).",
        )

    if last == first:
        frames = [first]
    else:
        span = last - first
        frames = sorted({
            first + round(span * index / (count - 1)) for index in range(count)
        })

    return ToolResult(
        ok=True,
        summary=(
            f"Sampled {len(frames)} frame(s) across {first}–{last} ({source})."
        ),
        data={
            "frames": frames,
            "first": first,
            "last": last,
            "source": source,
            "current_frame": int(getattr(project, "current_frame", 0)),
            "note": (
                "Inspect these frames with a vision tool and report only what "
                "the results actually show."
            ),
        },
    )


__all__ = ["register_tools"]
