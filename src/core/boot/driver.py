"""Staged, loggable editor boot sequence (UI-agnostic)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_io.aph_format import AphFormatError, load_aph
from app_io.node_loader import NodeLoader
from app_io.plugin_loader import PluginLoader
from core.boot.request import BootMode, BootRequest
from core.nodes.base import Node, NodeSocketType
from core.nodes.video_input import VideoInputNode
from core.preferences.models import PluginSettings
from core.preferences.store import PreferencesStore
from core.project import Project
from utils.logging_setup import get_logger

_LOG = get_logger("boot.driver")

_SUPPORTED_APH_VERSION = 1
_EXPECTED_FORMAT = "aphelion-project"

_MAX_NODES = 10_000
_MAX_CONNECTIONS = 100_000


@dataclass(frozen=True, slots=True)
class BootStageResult:
    """Outcome of a single boot stage."""

    ok: bool
    message: str
    detail: str = ""


class EditorBootDriver:
    """Runs ordered init stages and produces a validated ``Project``.

    The driver is intentionally free of Qt. A UI host advances stages one at
    a time (for progressive log display) via ``run_stage``.
    """

    def __init__(self, request: BootRequest) -> None:
        self._request: BootRequest = request
        self._project: Project | None = None
        self._document: dict[str, Any] | None = None
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
        """Return the project produced by a successful boot."""
        if self._project is None:
            raise RuntimeError("Boot has not produced a project yet")
        return self._project

    def stage_title(self, index: int) -> str:
        """Human-readable title for stage ``index``."""
        return self._stages[index][0]

    def run_stage(self, index: int) -> BootStageResult:
        """Execute a single stage by index."""
        if index < 0 or index >= len(self._stages):
            return BootStageResult(False, f"Invalid boot stage index: {index}")

        title, handler = self._stages[index]

        _LOG.info(
            "Running boot stage %s/%s: %s",
            index + 1,
            len(self._stages),
            title,
        )

        try:
            result = handler()
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("Boot stage crashed: %s", title)
            return BootStageResult(
                False,
                f"Stage failed: {exc}",
                detail=repr(exc),
            )

        if result.ok:
            _LOG.info("[%s] %s", title, result.message)
            if result.detail:
                _LOG.debug("[%s] %s", title, result.detail)
        else:
            _LOG.error("[%s] %s", title, result.message)

        return result

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    def _stage_runtime(self) -> BootStageResult:
        mode = (
            "new project"
            if self._request.mode is BootMode.NEW
            else "open project"
        )

        target = self._request.path or "(untitled)"

        from utils.host_publish import publish_editor_host

        publish_editor_host()

        return BootStageResult(
            True,
            f"Boot request accepted ({mode})",
            detail=f"target={target}",
        )

    # ------------------------------------------------------------------
    # Node registry
    # ------------------------------------------------------------------

    def _stage_register_nodes(self) -> BootStageResult:
        if not self._nodes_registered:
            NodeLoader.load_defaults()
            self._nodes_registered = True

        count = len(NodeLoader.default_nodes)

        return BootStageResult(
            True,
            f"Registered {count} built-in node type(s)",
        )

    # ------------------------------------------------------------------
    # Plugins
    # ------------------------------------------------------------------

    def _stage_load_plugins(self) -> BootStageResult:
        settings = _load_plugin_settings()
        count = PluginLoader.load_installed(settings)

        return BootStageResult(
            True,
            f"Registered {count} plugin node type(s)",
        )

    # ------------------------------------------------------------------
    # Project document
    # ------------------------------------------------------------------

    def _stage_load_project(self) -> BootStageResult:
        if self._request.mode is BootMode.NEW:
            self._project = Project("Untitled Project")
            self._document = None

            return BootStageResult(
                True,
                "Created blank project document",
            )

        path = Path(str(self._request.path))

        if not path.exists():
            return BootStageResult(
                False,
                f"Project file does not exist: {path}",
            )

        if not path.is_file():
            return BootStageResult(
                False,
                f"Project path is not a file: {path}",
            )

        # --------------------------------------------------------------
        # First validate the raw document.
        #
        # This happens BEFORE load_aph() so a malformed/corrupt document
        # cannot partially construct a Project.
        # --------------------------------------------------------------

        try:
            document = _read_project_document(path)
        except ProjectValidationError as exc:
            return BootStageResult(
                False,
                f"Invalid project document: {exc}",
            )

        validation_errors = validate_project_document(document)

        if validation_errors:
            return BootStageResult(
                False,
                f"Project validation failed ({len(validation_errors)} error(s))",
                detail="\n".join(validation_errors[:32]),
            )

        self._document = document

        # --------------------------------------------------------------
        # Only load the project after the raw document is known to be
        # structurally valid.
        # --------------------------------------------------------------

        try:
            self._project = load_aph(path)
        except AphFormatError as exc:
            self._project = None

            return BootStageResult(
                False,
                f"Failed to load project: {exc}",
            )

        except Exception as exc:  # noqa: BLE001
            self._project = None

            _LOG.exception(
                "Unexpected exception while loading project: %s",
                path,
            )

            return BootStageResult(
                False,
                f"Project loader rejected document: {exc}",
                detail=repr(exc),
            )

        node_count = len(self._project.nodes)

        return BootStageResult(
            True,
            f"Loaded project '{self._project.name}'",
            detail=f"{node_count} node(s), path={path}",
        )

    # ------------------------------------------------------------------
    # Graph validation
    # ------------------------------------------------------------------

    def _stage_validate_graph(self) -> BootStageResult:
        project = self.project

        errors = validate_loaded_project(project)

        if errors:
            return BootStageResult(
                False,
                f"Loaded graph is invalid ({len(errors)} error(s))",
                detail="\n".join(errors[:32]),
            )

        wire_count = len(project.connections)
        viewer = project.active_viewer or "(none)"

        detail = (
            f"nodes={len(project.nodes)} "
            f"wires={wire_count} "
            f"fps={project.fps} "
            f"frame={project.current_frame} "
            f"viewer={viewer}"
        )

        return BootStageResult(
            True,
            "Validated project graph",
            detail=detail,
        )

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def _stage_probe_media(self) -> BootStageResult:
        project = self.project

        probed = 0
        missing = 0

        for node in project.nodes.values():
            if not isinstance(node, VideoInputNode):
                continue

            path_prop = node.get_property("file_path")
            path_value = str(
                (path_prop.value if path_prop else "") or ""
            )

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


# ============================================================================
# Project document validation
# ============================================================================


class ProjectValidationError(ValueError):
    """Raised when an .aph document cannot be parsed safely."""


def _read_project_document(path: Path) -> dict[str, Any]:
    """Read and minimally validate the JSON container."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectValidationError(
            f"cannot read file: {exc}"
        ) from exc

    if not raw.strip():
        raise ProjectValidationError("file is empty")

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectValidationError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    if not isinstance(document, dict):
        raise ProjectValidationError(
            "root document must be a JSON object"
        )

    return document


def validate_project_document(
    document: Mapping[str, Any],
) -> list[str]:
    """Validate the raw .aph document before loading it.

    Returns a list of human-readable validation errors.
    """

    errors: list[str] = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    if document.get("format") != _EXPECTED_FORMAT:
        errors.append(
            f"invalid format: expected '{_EXPECTED_FORMAT}', "
            f"got {document.get('format')!r}"
        )

    version = document.get("version")

    if not isinstance(version, int) or isinstance(version, bool):
        errors.append("version must be an integer")
    elif version != _SUPPORTED_APH_VERSION:
        errors.append(
            f"unsupported project version: {version}; "
            f"supported version is {_SUPPORTED_APH_VERSION}"
        )

    name = document.get("name")

    if not isinstance(name, str):
        errors.append("name must be a string")

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    timeline = document.get("timeline")

    if not isinstance(timeline, dict):
        errors.append("timeline must be an object")
    else:
        errors.extend(_validate_timeline(timeline))

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    nodes = document.get("nodes")

    if not isinstance(nodes, dict):
        errors.append("nodes must be an object")
        nodes = {}

    elif len(nodes) > _MAX_NODES:
        errors.append(
            f"too many nodes: {len(nodes)} > {_MAX_NODES}"
        )

    node_ids: set[str] = set()

    for node_id, node_data in nodes.items():
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"invalid node ID: {node_id!r}")
            continue

        node_ids.add(node_id)

        if not isinstance(node_data, dict):
            errors.append(
                f"node '{node_id}' must be an object"
            )
            continue

        errors.extend(
            _validate_raw_node(
                node_id,
                node_data,
            )
        )

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    connections = document.get("connections")

    if not isinstance(connections, list):
        errors.append("connections must be an array")
        connections = []

    elif len(connections) > _MAX_CONNECTIONS:
        errors.append(
            f"too many connections: "
            f"{len(connections)} > {_MAX_CONNECTIONS}"
        )

    errors.extend(
        _validate_raw_connections(
            connections,
            node_ids,
            nodes,
        )
    )

    # ------------------------------------------------------------------
    # Active viewer
    # ------------------------------------------------------------------

    active_viewer = document.get("active_viewer")

    if active_viewer is not None:
        if not isinstance(active_viewer, str):
            errors.append("active_viewer must be a string or null")
        elif active_viewer not in node_ids:
            errors.append(
                f"active_viewer references missing node "
                f"'{active_viewer}'"
            )
        else:
            viewer_node = nodes.get(active_viewer)

            if isinstance(viewer_node, dict):
                if viewer_node.get("node_type") != "Viewer":
                    errors.append(
                        f"active_viewer '{active_viewer}' "
                        f"is not a Viewer node"
                    )

    return errors


def _validate_timeline(
    timeline: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []

    fps = timeline.get("fps")
    width = timeline.get("width")
    height = timeline.get("height")
    duration = timeline.get("duration")
    current_frame = timeline.get("current_frame")

    if not _finite_number(fps) or float(fps) <= 0.0:
        errors.append(
            f"timeline.fps must be finite and > 0, got {fps!r}"
        )

    if not _integer_like(width) or int(width) <= 0:
        errors.append(
            f"timeline.width must be a positive integer, got {width!r}"
        )

    if not _integer_like(height) or int(height) <= 0:
        errors.append(
            f"timeline.height must be a positive integer, got {height!r}"
        )

    if not _finite_number(duration) or float(duration) < 0.0:
        errors.append(
            "timeline.duration must be finite and >= 0"
        )

    if not _integer_like(current_frame) or int(current_frame) < 0:
        errors.append(
            "timeline.current_frame must be a non-negative integer"
        )

    if (
        _finite_number(duration)
        and _finite_number(fps)
        and _integer_like(current_frame)
    ):
        max_frame = max(
            0,
            int(round(float(duration) * float(fps))) - 1,
        )

        if int(current_frame) > max_frame and max_frame >= 0:
            errors.append(
                f"timeline.current_frame {current_frame} "
                f"exceeds timeline frame range 0..{max_frame}"
            )

    return errors


def _validate_raw_node(
    node_id: str,
    node: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []

    node_type = node.get("node_type")

    if not isinstance(node_type, str) or not node_type:
        errors.append(
            f"node '{node_id}' has invalid node_type"
        )
    elif not _node_type_exists(node_type):
        errors.append(
            f"node '{node_id}' references unknown node type "
            f"'{node_type}'"
        )

    name = node.get("name")

    if name is not None and not isinstance(name, str):
        errors.append(
            f"node '{node_id}': name must be a string"
        )

    for coordinate in ("x", "y", "width", "height"):
        value = node.get(coordinate)

        if value is not None and not _finite_number(value):
            errors.append(
                f"node '{node_id}': {coordinate} must be finite"
            )

    properties = node.get("properties", {})

    if not isinstance(properties, dict):
        errors.append(
            f"node '{node_id}': properties must be an object"
        )

    animated = node.get("animated_properties", {})

    if not isinstance(animated, dict):
        errors.append(
            f"node '{node_id}': animated_properties "
            f"must be an object"
        )

    return errors


def _validate_raw_connections(
    connections: list[Any],
    node_ids: set[str],
    nodes: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []

    seen_connections: set[
        tuple[str, str, str, str]
    ] = set()

    seen_inputs: set[tuple[str, str]] = set()

    for index, connection in enumerate(connections):
        prefix = f"connection[{index}]"

        if not isinstance(connection, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        output_node_id = connection.get("output_node_id")
        output_slot = connection.get("output_slot")
        input_node_id = connection.get("input_node_id")
        input_slot = connection.get("input_slot")

        if not isinstance(output_node_id, str):
            errors.append(
                f"{prefix}: output_node_id must be a string"
            )

        if not isinstance(output_slot, str):
            errors.append(
                f"{prefix}: output_slot must be a string"
            )

        if not isinstance(input_node_id, str):
            errors.append(
                f"{prefix}: input_node_id must be a string"
            )

        if not isinstance(input_slot, str):
            errors.append(
                f"{prefix}: input_slot must be a string"
            )

        if not all(
            isinstance(value, str)
            for value in (
                output_node_id,
                output_slot,
                input_node_id,
                input_slot,
            )
        ):
            continue

        if output_node_id not in node_ids:
            errors.append(
                f"{prefix}: output node "
                f"'{output_node_id}' does not exist"
            )
            continue

        if input_node_id not in node_ids:
            errors.append(
                f"{prefix}: input node "
                f"'{input_node_id}' does not exist"
            )
            continue

        key = (
            output_node_id,
            output_slot,
            input_node_id,
            input_slot,
        )

        if key in seen_connections:
            errors.append(
                f"{prefix}: duplicate connection"
            )
        else:
            seen_connections.add(key)

        input_key = (input_node_id, input_slot)

        if input_key in seen_inputs:
            errors.append(
                f"{prefix}: input socket "
                f"'{input_node_id}.{input_slot}' "
                f"is connected more than once"
            )
        else:
            seen_inputs.add(input_key)

        output_node = nodes.get(output_node_id)
        input_node = nodes.get(input_node_id)

        if not isinstance(output_node, dict):
            continue

        if not isinstance(input_node, dict):
            continue

        output_type = output_node.get("node_type")
        input_type = input_node.get("node_type")

        output_cls = _node_class(output_type)
        input_cls = _node_class(input_type)

        if output_cls is None or input_cls is None:
            continue

        # Instantiate temporary nodes only when the registry allows it.
        #
        # This is intentionally best-effort. The actual loader remains
        # authoritative for constructor-specific requirements.
        try:
            output_instance = output_cls()
            input_instance = input_cls()
        except Exception:
            continue

        output_socket = output_instance.outputs.get(output_slot)
        input_socket = input_instance.inputs.get(input_slot)

        if output_socket is None:
            errors.append(
                f"{prefix}: output socket "
                f"'{output_node_id}.{output_slot}' "
                f"does not exist on '{output_type}'"
            )
            continue

        if input_socket is None:
            errors.append(
                f"{prefix}: input socket "
                f"'{input_node_id}.{input_slot}' "
                f"does not exist on '{input_type}'"
            )
            continue

        if not output_socket.is_input:
            pass
        else:
            errors.append(
                f"{prefix}: '{output_node_id}.{output_slot}' "
                f"is not an output socket"
            )

        if input_socket.is_input is not True:
            errors.append(
                f"{prefix}: '{input_node_id}.{input_slot}' "
                f"is not an input socket"
            )

        if output_socket.socket_type != input_socket.socket_type:
            errors.append(
                f"{prefix}: incompatible socket types: "
                f"{output_type}.{output_slot} "
                f"({output_socket.socket_type.name}) -> "
                f"{input_type}.{input_slot} "
                f"({input_socket.socket_type.name})"
            )

    return errors


# ============================================================================
# Loaded-project validation
# ============================================================================


def validate_loaded_project(
    project: Project,
) -> list[str]:
    """Validate the actual instantiated Project graph."""

    errors: list[str] = []

    if not project.nodes:
        return errors

    node_ids = set(project.nodes)

    # ------------------------------------------------------------------
    # Every node must be a Node instance.
    # ------------------------------------------------------------------

    for node_id, node in project.nodes.items():
        if not isinstance(node, Node):
            errors.append(
                f"node '{node_id}' is not a Node instance"
            )

    # ------------------------------------------------------------------
    # Validate every connection against actual sockets.
    # ------------------------------------------------------------------

    seen_inputs: set[tuple[str, str]] = set()
    seen_connections: set[
        tuple[str, str, str, str]
    ] = set()

    for connection in project.connections:
        output_node_id = connection.output_node_id
        output_slot = connection.output_slot
        input_node_id = connection.input_node_id
        input_slot = connection.input_slot

        key = (
            output_node_id,
            output_slot,
            input_node_id,
            input_slot,
        )

        if key in seen_connections:
            errors.append(
                f"duplicate connection: "
                f"{output_node_id}.{output_slot} -> "
                f"{input_node_id}.{input_slot}"
            )
        else:
            seen_connections.add(key)

        output_node = project.nodes.get(output_node_id)
        input_node = project.nodes.get(input_node_id)

        if output_node is None:
            errors.append(
                f"connection references missing output node "
                f"'{output_node_id}'"
            )
            continue

        if input_node is None:
            errors.append(
                f"connection references missing input node "
                f"'{input_node_id}'"
            )
            continue

        output_socket = output_node.outputs.get(output_slot)
        input_socket = input_node.inputs.get(input_slot)

        if output_socket is None:
            errors.append(
                f"missing output socket: "
                f"{output_node_id}.{output_slot}"
            )
            continue

        if input_socket is None:
            errors.append(
                f"missing input socket: "
                f"{input_node_id}.{input_slot}"
            )
            continue

        if output_socket.is_input:
            errors.append(
                f"{output_node_id}.{output_slot} "
                f"is marked as an input socket"
            )

        if not input_socket.is_input:
            errors.append(
                f"{input_node_id}.{input_slot} "
                f"is marked as an output socket"
            )

        if output_socket.socket_type != input_socket.socket_type:
            errors.append(
                f"incompatible connection: "
                f"{output_node_id}.{output_slot} "
                f"({output_socket.socket_type.name}) -> "
                f"{input_node_id}.{input_slot} "
                f"({input_socket.socket_type.name})"
            )

        input_key = (input_node_id, input_slot)

        if input_key in seen_inputs:
            errors.append(
                f"input socket connected multiple times: "
                f"{input_node_id}.{input_slot}"
            )
        else:
            seen_inputs.add(input_key)

    # ------------------------------------------------------------------
    # Viewer validation.
    # ------------------------------------------------------------------

    viewer_id = project.active_viewer

    if viewer_id is not None:
        viewer = project.nodes.get(viewer_id)

        if viewer is None:
            errors.append(
                f"active viewer '{viewer_id}' does not exist"
            )
        elif getattr(viewer, "node_type", None) != "Viewer":
            errors.append(
                f"active viewer '{viewer_id}' is not a Viewer node"
            )

    # ------------------------------------------------------------------
    # Detect cycles.
    #
    # Video/audio graphs should be DAGs. Feedback systems should be
    # represented by explicit stateful nodes rather than raw graph cycles.
    # ------------------------------------------------------------------

    errors.extend(_validate_acyclic_graph(project))

    return errors


def _validate_acyclic_graph(
    project: Project,
) -> list[str]:
    """Detect graph cycles using iterative DFS."""

    adjacency: dict[str, list[str]] = {
        node_id: []
        for node_id in project.nodes
    }

    for connection in project.connections:
        if (
            connection.output_node_id in adjacency
            and connection.input_node_id in adjacency
        ):
            adjacency[
                connection.output_node_id
            ].append(connection.input_node_id)

    # 0 = unseen
    # 1 = currently visiting
    # 2 = completely visited
    state: dict[str, int] = {}

    for start in adjacency:
        if state.get(start, 0) != 0:
            continue

        stack: list[tuple[str, int]] = [(start, 0)]
        state[start] = 1

        while stack:
            node_id, index = stack[-1]
            children = adjacency[node_id]

            if index >= len(children):
                state[node_id] = 2
                stack.pop()
                continue

            child = children[index]
            stack[-1] = (node_id, index + 1)

            child_state = state.get(child, 0)

            if child_state == 1:
                return [
                    f"graph contains a dependency cycle involving "
                    f"'{child}'"
                ]

            if child_state == 0:
                state[child] = 1
                stack.append((child, 0))

    return []


# ============================================================================
# Node registry helpers
# ============================================================================


def _node_registry() -> Mapping[str, Any]:
    """Return the currently registered node mapping.

    NodeLoader implementations sometimes expose the registry as a dict and
    older implementations may expose a list/tuple. Normalize the common
    forms here.
    """

    registry = NodeLoader.default_nodes

    if isinstance(registry, Mapping):
        return registry

    result: dict[str, Any] = {}

    try:
        for item in registry:
            node_type = getattr(item, "node_type", None)

            if isinstance(node_type, str) and node_type:
                result[node_type] = item
    except TypeError:
        pass

    return result


def _node_class(node_type: Any) -> type[Node] | None:
    """Resolve a registered node type to its class."""

    if not isinstance(node_type, str):
        return None

    registry = _node_registry()
    value = registry.get(node_type)

    if value is None:
        return None

    if isinstance(value, type) and issubclass(value, Node):
        return value

    if isinstance(value, Node):
        return type(value)

    return None


def _node_type_exists(node_type: str) -> bool:
    return _node_class(node_type) is not None


# ============================================================================
# Primitive validation helpers
# ============================================================================


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False

    if not isinstance(value, (int, float)):
        return False

    return bool(
        value == value
        and abs(float(value)) != float("inf")
    )


def _integer_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False

    if isinstance(value, int):
        return True

    if isinstance(value, float):
        return (
            value == value
            and abs(value) != float("inf")
            and value.is_integer()
        )

    return False


# ============================================================================
# Preferences
# ============================================================================


def _load_plugin_settings() -> PluginSettings:
    """Load persisted plugin discovery flags, falling back to defaults."""
    store = PreferencesStore()
    store.load()
    return store.preferences.plugins
