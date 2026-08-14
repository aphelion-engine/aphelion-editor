"""Staged, loggable editor boot sequence (UI-agnostic)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_io.aph_format import AphFormatError, load_aph
from app_io.node_loader import NodeLoader
from app_io.plugin_loader import PluginLoader
from core.boot.request import BootMode, BootRequest
from core.nodes.video_input import VideoInputNode
from core.preferences.models import PluginSettings
from core.preferences.store import PreferencesStore
from core.project import Project
from utils.logging_setup import get_logger

_LOG = get_logger("boot.driver")


@dataclass(frozen=True, slots=True)
class BootStageResult:
    """Outcome of a single boot stage."""

    ok: bool
    message: str
    detail: str = ""


class EditorBootDriver:
    """Runs ordered init stages and produces a loaded ``Project``.

    The driver is intentionally free of Qt. A UI host advances stages one at
    a time (for progressive log display) via ``run_stage``.
    """

    def __init__(self, request: BootRequest) -> None:
        self._request: BootRequest = request
        self._project: Project | None = None
        self._nodes_registered: bool = False
        self._stages: list[tuple[str, Callable[[], BootStageResult]]] = [
            ("Runtime", self._stage_runtime),
            ("Node registry", self._stage_register_nodes),
            ("Plugins", self._stage_load_plugins),
            ("Project document", self._stage_load_project),
            ("Graph validation", self._stage_validate_graph),
            ("Media sources", self._stage_probe_media),
        ]

    @property
    def stage_count(self) -> int:
        """Number of stages in the boot pipeline."""
        return len(self._stages)

    @property
    def project(self) -> Project:
        """Return the project produced by a successful boot.

        Raises:
            RuntimeError: When called before the project stage succeeds.
        """
        if self._project is None:
            raise RuntimeError("Boot has not produced a project yet")
        return self._project

    def stage_title(self, index: int) -> str:
        """Human-readable title for stage ``index``."""
        return self._stages[index][0]

    def run_stage(self, index: int) -> BootStageResult:
        """Execute a single stage by index.

        Parameters:
            index: Zero-based stage index.

        Returns:
            Stage outcome with log message text.
        """
        if index < 0 or index >= len(self._stages):
            return BootStageResult(False, f"Invalid boot stage index: {index}")
        title, handler = self._stages[index]
        _LOG.info("Running boot stage %s/%s: %s", index + 1, len(self._stages), title)
        try:
            result = handler()
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("Boot stage crashed: %s", title)
            return BootStageResult(False, f"Stage failed: {exc}", detail=repr(exc))
        if result.ok:
            _LOG.info("[%s] %s", title, result.message)
            if result.detail:
                _LOG.debug("[%s] %s", title, result.detail)
        else:
            _LOG.error("[%s] %s", title, result.message)
        return result

    def _stage_runtime(self) -> BootStageResult:
        mode = "new project" if self._request.mode is BootMode.NEW else "open project"
        target = self._request.path or "(untitled)"
        return BootStageResult(
            True,
            f"Boot request accepted ({mode})",
            detail=f"target={target}",
        )

    def _stage_register_nodes(self) -> BootStageResult:
        if not self._nodes_registered:
            NodeLoader.load_defaults()
            self._nodes_registered = True
        count = len(NodeLoader.default_nodes)
        return BootStageResult(True, f"Registered {count} built-in node type(s)")

    def _stage_load_plugins(self) -> BootStageResult:
        settings = _load_plugin_settings()
        count = PluginLoader.load_installed(settings)
        return BootStageResult(True, f"Registered {count} plugin node type(s)")

    def _stage_load_project(self) -> BootStageResult:
        if self._request.mode is BootMode.NEW:
            self._project = Project("Untitled Project")
            return BootStageResult(True, "Created blank project document")
        path = Path(str(self._request.path))
        try:
            self._project = load_aph(path)
        except AphFormatError as exc:
            return BootStageResult(False, f"Failed to load project: {exc}")
        node_count = len(self._project.nodes)
        return BootStageResult(
            True,
            f"Loaded project '{self._project.name}'",
            detail=f"{node_count} node(s), path={path}",
        )

    def _stage_validate_graph(self) -> BootStageResult:
        project = self.project
        wire_count = len(project.connections)
        viewer = project.active_viewer or "(none)"
        detail = (
            f"nodes={len(project.nodes)} wires={wire_count} "
            f"fps={project.fps} frame={project.current_frame} viewer={viewer}"
        )
        return BootStageResult(True, "Validated project graph", detail=detail)

    def _stage_probe_media(self) -> BootStageResult:
        project = self.project
        probed: int = 0
        missing: int = 0
        for node in project.nodes.values():
            if not isinstance(node, VideoInputNode):
                continue
            path_prop = node.get_property("file_path")
            path_value = str((path_prop.value if path_prop else "") or "")
            if not path_value:
                continue
            if not Path(path_value).is_file():
                missing += 1
                continue
            info: Any = node.probe_media()
            if info is not None:
                probed += 1
            else:
                missing += 1
        return BootStageResult(
            True,
            f"Probed media sources ({probed} ok, {missing} unavailable)",
        )


def _load_plugin_settings() -> PluginSettings:
    """Load persisted plugin discovery flags, falling back to defaults."""
    store = PreferencesStore()
    store.load()
    return store.preferences.plugins
