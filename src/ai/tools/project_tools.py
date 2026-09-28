"""Project-level tools: info, settings, save, and media inventory."""

from __future__ import annotations

import os

from ai.graph_model import project_summary
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.types import Permission, ToolResult
from core.history.commands import SetProjectSettingsCommand
from core.project_settings import ProjectSettings


def register_tools(registry: ToolRegistry) -> None:
    """Register every project.* tool."""

    registry.register(
        ToolSpec(
            name="project.get_info",
            description=(
                "Summarise the open project: resolution, frame rate, duration, "
                "node and connection counts, active viewer, and (when the media "
                "permission is granted) the source files in use."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_get_info,
            category="Project",
        )
    )

    registry.register(
        ToolSpec(
            name="project.get_settings",
            description="Return the editable project settings (name, fps, size, duration).",
            parameters={"type": "object", "properties": {}},
            permission=Permission.READ_PROJECT,
            handler=_get_settings,
            category="Project",
        )
    )

    registry.register(
        ToolSpec(
            name="project.set_settings",
            description=(
                "Change project settings. Only the supplied fields are changed; "
                "omit anything the user did not ask to alter."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name."},
                    "fps": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 240,
                        "description": "Frames per second.",
                    },
                    "width": {
                        "type": "integer",
                        "minimum": 16,
                        "maximum": 16384,
                        "description": "Frame width in pixels.",
                    },
                    "height": {
                        "type": "integer",
                        "minimum": 16,
                        "maximum": 16384,
                        "description": "Frame height in pixels.",
                    },
                    "duration": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 360000,
                        "description": "Timeline duration in seconds.",
                    },
                },
            },
            permission=Permission.EDIT_PROJECT,
            handler=_set_settings,
            mutates=True,
            category="Project",
        )
    )

    registry.register(
        ToolSpec(
            name="project.save",
            description=(
                "Save the project to disk. Fails when the document has never "
                "been saved, in which case ask the user to save it once."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.EDIT_PROJECT,
            handler=_save,
            mutates=False,
            category="Project",
        )
    )

    registry.register(
        ToolSpec(
            name="project.list_media",
            description=(
                "List the media files referenced by input nodes. Requires the "
                "local-filenames permission."
            ),
            parameters={"type": "object", "properties": {}},
            permission=Permission.ACCESS_MEDIA,
            handler=_list_media,
            category="Project",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _get_info(ctx: ToolContext) -> ToolResult:
    summary = project_summary(ctx.project)
    if not ctx.permissions.allows(Permission.ACCESS_MEDIA):
        # Filenames never leave the machine without the user opting in.
        summary["media"] = [
            {"node_id": entry["node_id"], "node": entry["node"]}
            for entry in summary.get("media", [])
        ]
        summary["media_filenames_withheld"] = True
    return ToolResult(
        ok=True,
        summary=(
            f"{summary['name']}: {summary['node_count']} nodes, "
            f"{summary['connection_count']} connections, "
            f"{summary['width']}x{summary['height']} @ {summary['fps']} fps"
        ),
        data=summary,
    )


def _get_settings(ctx: ToolContext) -> ToolResult:
    settings = ctx.project.project_settings()
    data = {
        "name": settings.name,
        "fps": settings.fps,
        "width": settings.width,
        "height": settings.height,
        "duration": settings.duration,
        "frame_count": int(ctx.project.max_frame) + 1,
    }
    return ToolResult(
        ok=True,
        summary=f"{settings.name} — {settings.width}x{settings.height} @ {settings.fps} fps",
        data=data,
    )


def _set_settings(ctx: ToolContext) -> ToolResult:
    transaction = ctx.require_transaction("change project settings")
    current = ctx.project.project_settings()
    args = ctx.args

    requested: dict[str, object] = {
        "name": args.get("name", current.name),
        "fps": args.get("fps", current.fps),
        "width": args.get("width", current.width),
        "height": args.get("height", current.height),
        "duration": args.get("duration", current.duration),
    }
    if all(requested[key] == getattr(current, key) for key in requested):
        return ToolResult(
            ok=True,
            summary="Project settings already match the request.",
            data={
                "name": current.name,
                "fps": current.fps,
                "width": current.width,
                "height": current.height,
                "duration": current.duration,
            },
        )

    updated = ProjectSettings(
        name=str(requested["name"]),
        fps=int(requested["fps"]),  # type: ignore[arg-type]
        width=int(requested["width"]),  # type: ignore[arg-type]
        height=int(requested["height"]),  # type: ignore[arg-type]
        duration=float(requested["duration"]),  # type: ignore[arg-type]
    )
    changes = [
        f"{key}: {getattr(current, key)} → {requested[key]}"
        for key in requested
        if getattr(current, key) != requested[key]
    ]
    applied = transaction.apply(
        ctx.project,
        SetProjectSettingsCommand(updated),
        action=f"~ Project settings: {'; '.join(changes)}",
    )
    if not applied:
        return ToolResult.failure(
            "COMMAND_REJECTED", "The project rejected the settings change."
        )
    return ToolResult(
        ok=True,
        summary=f"Updated project settings ({len(changes)} field(s)).",
        details=[f"~ {change}" for change in changes],
        data={"name": updated.name, "fps": updated.fps,
              "width": updated.width, "height": updated.height,
              "duration": updated.duration},
    )


def _save(ctx: ToolContext) -> ToolResult:
    path = getattr(ctx.project, "file_path", None)
    if not path:
        return ToolResult.failure(
            "NOT_SAVED_YET",
            "This project has no file path yet. Ask the user to save it once "
            "from File → Save Project As…, then I can save it for you.",
        )
    saved = bool(ctx.host.save_project())
    if not saved:
        return ToolResult.failure("SAVE_FAILED", f"Could not write {os.path.basename(str(path))}.")
    return ToolResult(
        ok=True,
        summary=f"Saved {os.path.basename(str(path))}",
        data={"path_available": True},
        details=[f"✓ Saved {os.path.basename(str(path))}"],
    )


def _list_media(ctx: ToolContext) -> ToolResult:
    rows: list[dict[str, object]] = []
    for node_id, node in ctx.project.nodes.items():
        prop = node.get_property("file_path")
        if prop is None or not getattr(prop, "value", None):
            continue
        rows.append(
            {
                "node_id": node_id,
                "node": node.name,
                "type": node.node_type,
                "file": str(prop.value),
            }
        )
    return ToolResult(
        ok=True,
        summary=f"{len(rows)} media source(s) in the project.",
        data={"media": rows},
    )
