"""Central project state: nodes, connections, timeline, and evaluation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from config.constants import (DEFAULT_DURATION, DEFAULT_FPS, DEFAULT_HEIGHT,
                              DEFAULT_WIDTH, FRAME_CACHE_MAX_MB)
from core.audio import FrameWithAudio
from core.cache import FrameCache
from core.events import Connection, ObserverEvent
from core.graph import DependencyGraph
from core.nodes import Node, VideoInputNode, global_node_registry
from core.nodes.base import NodePropertyInputType, NodeSocketType
from core.nodes.property_link import (PROPERTY_DRIVE_PROPERTY_KEY,
                                      PROPERTY_DRIVE_VALUE_SLOT,
                                      property_drive_target_id,
                                      sockets_compatible)
from core.project_settings import ProjectSettings
from core.serialization import APH_FORMAT_ID, APH_FORMAT_VERSION
from render.preview import PreviewSettings

#: Distinct "not in dict" marker so an export-cache hit of ``None`` is not
#: confused with a miss.
_CACHE_MISS: object = object()


class _NodeDriveLookup:
    """Reusable per-node property-drive lookup.

    The evaluator used to allocate a fresh closure for every node on every
    frame just to capture ``(node_id, overrides)``. Exports evaluate the
    same node thousands of times, so that allocation churn is replaced by
    one long-lived callable that the node keeps for its lifetime.
    """

    __slots__ = ("owner", "node_id", "_overrides")

    def __init__(
        self,
        owner: Project,
        overrides: dict[tuple[str, str], float],
        node_id: str,
    ) -> None:
        self.owner = owner
        self.node_id = node_id
        self._overrides = overrides

    def __call__(self, key: str) -> float | None:
        return self._overrides.get((self.node_id, key))


class _TimeResampler:
    """Reusable upstream-frame resampler for one node input socket.

    Replaces the per-frame ``lambda`` the evaluator used to build for every
    frame-socket connection.
    """

    __slots__ = ("owner", "_evaluate", "_node_id", "_slot")

    def __init__(
        self,
        owner: Project,
        evaluate: Callable[[str, int, str], Any],
    ) -> None:
        self.owner = owner
        self._evaluate = evaluate
        self._node_id = ""
        self._slot = "frame"

    def bind(self, node_id: str, slot: str) -> None:
        self._node_id = node_id
        self._slot = slot

    def __call__(self, frame_num: int) -> Any:
        return self._evaluate(self._node_id, int(frame_num), self._slot)


class Project:
    """Central project state: nodes, connections, timeline, and evaluation."""

    def __init__(self, name: str | None = None) -> None:
        self.name = name or "Untitled Project"

        self.nodes: dict[str, Node] = {}
        self.connections: set[Connection] = set()

        self.fps = DEFAULT_FPS
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.duration = DEFAULT_DURATION
        self.current_frame = 0
        self._timeline_frame_count: int | None = None

        self.active_viewer: str | None = None
        self.file_path: str | None = None

        self.observers: list[
            Callable[[ObserverEvent, Any], None]
        ] = []

        self.exceptions_log: list[Exception] = []

        self._frame_cache = FrameCache(
            max_mb=FRAME_CACHE_MAX_MB
        )

        self.dependency_graph = DependencyGraph(
            self.nodes,
            self.connections,
            self._frame_cache,
        )

        self._playback_proxy_override_width: int | None = None
        self._full_resolution_override = False

        # Explicit preview-width override. Used by nested subgraph evaluation
        # (custom nodes) so an embedded graph renders at exactly the same
        # resolution as the parent graph instead of the viewer-less default.
        self._preview_width_override: int | None = None

        # Evaluation is deliberately serialized because Node instances
        # contain mutable per-evaluation state.
        self._eval_lock = threading.RLock()

        # --------------------------------------------------------------
        # Export-mode evaluation
        #
        # Interactive evaluation keeps a large cross-frame LRU because a
        # user scrubs back and forth over the same frames. A sequential
        # export never revisits a frame, so that cache degenerates into
        # pure overhead: every node result is inserted, byte-counted and
        # immediately evicted, and the process holds hundreds of
        # megabytes of float32 intermediates that are never read again.
        #
        # Export mode swaps the LRU for a tiny dict that is cleared at the
        # start of every frame. Within-frame fan-out dedup is preserved
        # (diamond graphs still evaluate a shared node once), but nothing
        # survives to the next frame, so memory stays flat and CPU cache
        # locality improves dramatically.
        # --------------------------------------------------------------

        self._export_mode = False
        self._export_frame_cache: dict[
            tuple[str, int, str],
            Any,
        ] = {}

        # Pre-bound resolvers: created once here instead of allocating a
        # lambda for every node on every evaluated frame.
        self._named_resolver_bound = self._resolve_named_property_for_frame
        self._node_resolver_bound = self._resolve_node_property_for_frame

        # --------------------------------------------------------------
        # Property-drive state
        # --------------------------------------------------------------

        self._drive_overrides_frame: int | None = None
        self._drive_overrides: dict[
            tuple[str, str],
            float,
        ] = {}

        # --------------------------------------------------------------
        # Fast node indexes
        #
        # PropertyLinkNode previously searched self.nodes.values()
        # whenever it needed to resolve a named node. That is O(N) for
        # every property lookup.
        # --------------------------------------------------------------

        self._nodes_by_name: dict[str, list[Node]] = {}

        self._property_drive_ids: set[str] = set()

        # --------------------------------------------------------------
        # Evaluation context
        #
        # These values are populated once for the current top-level
        # evaluate_node() call and reused by all recursive calls.
        # --------------------------------------------------------------

        self._eval_context_depth = 0
        self._eval_context_frame: int | None = None
        self._eval_context_settings: PreviewSettings | None = None
        self._eval_context_cache_width: int | None = None

    # ==================================================================
    # Timeline
    # ==================================================================

    @property
    def max_frame(self) -> int:
        frame_count = self._timeline_frame_count

        if frame_count is not None and frame_count > 0:
            return max(0, frame_count - 1)

        return max(
            0,
            int(round(self.duration * self.fps)) - 1,
        )

    def project_settings(self) -> ProjectSettings:
        """Return the current editable project settings snapshot."""

        return ProjectSettings(
            name=self.name,
            fps=int(self.fps),
            width=int(self.width),
            height=int(self.height),
            duration=float(self.duration),
        )

    def apply_project_settings(
        self,
        settings: ProjectSettings,
    ) -> None:
        """Apply timeline and format settings."""

        self.name = (
            settings.name.strip()
            or "Untitled Project"
        )

        self.fps = max(
            1,
            int(settings.fps),
        )

        self.width = max(
            16,
            int(settings.width),
        )

        self.height = max(
            16,
            int(settings.height),
        )

        self.duration = max(
            0.1,
            float(settings.duration),
        )

        self._timeline_frame_count = None

        self.current_frame = min(
            self.current_frame,
            self.max_frame,
        )

        self.clear_cache()

        self.notify_observers(
            ObserverEvent.ProjectModified,
            None,
        )

        self.notify_observers(
            ObserverEvent.FrameChanged,
            self.current_frame,
        )

    # ==================================================================
    # Cache
    # ==================================================================

    def cache_stats(self) -> tuple[float, float, int]:
        cache = self._frame_cache

        return (
            cache.size_mb,
            cache.max_mb,
            cache.entry_count,
        )

    def set_frame_cache_budget_mb(
        self,
        max_mb: int,
    ) -> None:
        self._frame_cache.set_max_mb(max_mb)

    def clear_cache(self) -> None:
        self.dependency_graph.clear_cache()

    def invalidate_cache(
        self,
        node_id: str,
    ) -> None:
        self.dependency_graph.invalidate_node(
            node_id
        )

        node = self.nodes.get(node_id)

        if (
            node is not None
            and node.node_type == "Viewer"
        ):
            self.clear_cache()

        self.notify_observers(
            ObserverEvent.NodeModified,
            node_id,
        )

    # ==================================================================
    # Resolution settings
    # ==================================================================

    def set_full_resolution_override(
        self,
        enabled: bool,
    ) -> None:
        self._full_resolution_override = bool(
            enabled
        )

        # Existing cached frames may have been generated at proxy
        # resolution. The cache namespace prevents incorrect reuse.
        #
        # No clear_cache() here: switching back and forth can reuse
        # already-valid proxy/full-resolution buckets.

    def set_playback_proxy_override(
        self,
        max_width: int | None,
    ) -> None:
        self._playback_proxy_override_width = (
            None
            if max_width is None
            else max(1, int(max_width))
        )

    def set_preview_width_override(
        self,
        max_width: int | None,
    ) -> None:
        """Force an exact preview width regardless of viewer settings.

        ``0`` means full resolution. ``None`` restores normal viewer-driven
        resolution. Used by custom-node subgraph evaluation.
        """
        self._preview_width_override = (
            None
            if max_width is None
            else max(0, int(max_width))
        )

    def get_preview_settings(self) -> PreviewSettings:
        viewer = (
            self.nodes.get(self.active_viewer)
            if self.active_viewer is not None
            else None
        )

        settings = PreviewSettings.from_viewer(
            viewer
        )

        override_width = self._preview_width_override

        if override_width is not None:
            return replace(
                settings,
                max_width=override_width,
            )

        if self._full_resolution_override:
            return replace(
                settings,
                max_width=0,
            )

        override = (
            self._playback_proxy_override_width
        )

        if (
            override is not None
            and override < settings.max_width
        ):
            return replace(
                settings,
                max_width=override,
            )

        return settings

    def _get_evaluation_settings(
        self,
    ) -> PreviewSettings:
        """Return settings cached for the current evaluation tree."""

        settings = self._eval_context_settings

        if settings is None:
            settings = self.get_preview_settings()
            self._eval_context_settings = settings

        return settings

    def _preview_cache_slot(
        self,
        output_slot: str,
    ) -> str:
        settings = self._get_evaluation_settings()

        return (
            f"{output_slot}@"
            f"{settings.max_width}"
        )

    # ==================================================================
    # Node indexing
    # ==================================================================

    def _index_node(
        self,
        node_id: str,
        node: Node,
    ) -> None:
        name = node.name

        if name:
            bucket = self._nodes_by_name.setdefault(
                name,
                [],
            )

            if node not in bucket:
                bucket.append(node)

        if node.node_type == "Property Drive":
            self._property_drive_ids.add(
                node_id
            )

    def _unindex_node(
        self,
        node_id: str,
        node: Node,
    ) -> None:
        name = node.name

        if name:
            bucket = self._nodes_by_name.get(
                name
            )

            if bucket is not None:
                try:
                    bucket.remove(node)
                except ValueError:
                    pass

                if not bucket:
                    del self._nodes_by_name[
                        name
                    ]

        self._property_drive_ids.discard(
            node_id
        )

    # ==================================================================
    # Node management
    # ==================================================================

    def add_node(
        self,
        node: Node,
        node_id: str | None = None,
    ) -> str:
        if (
            node_id is not None
            and node_id in self.nodes
        ):
            node_id = None

        if node_id is None:
            node_id = (
                f"node_{len(self.nodes)}_"
                f"{int(time.time() * 1000)}"
            )

        self.nodes[node_id] = node

        self._index_node(
            node_id,
            node,
        )

        self.dependency_graph.update(
            self.nodes,
            self.connections,
        )

        self.notify_observers(
            ObserverEvent.NodeAdded,
            node_id,
        )

        if (
            node.node_type == "Viewer"
            and self.active_viewer is None
        ):
            self.set_active_viewer(
                node_id
            )

        return node_id

    def remove_node(
        self,
        node_id: str,
    ) -> None:
        node = self.nodes.get(node_id)

        if node is None:
            return

        self.connections = {
            connection
            for connection in self.connections
            if (
                connection.output_node_id
                != node_id
                and connection.input_node_id
                != node_id
            )
        }

        if self.active_viewer == node_id:
            self.active_viewer = None

        if isinstance(node, VideoInputNode):
            node.close()

        self._unindex_node(
            node_id,
            node,
        )

        del self.nodes[node_id]

        self.dependency_graph.invalidate_node(
            node_id
        )

        self.dependency_graph.update(
            self.nodes,
            self.connections,
        )

        self.notify_observers(
            ObserverEvent.NodeRemoved,
            node_id,
        )

    def set_node_property(
        self,
        node_id: str,
        prop_name: str,
        value: Any,
    ) -> bool:
        node = self.nodes.get(node_id)

        if node is None:
            return False

        prop = node.get_property(
            prop_name
        )

        if prop is None:
            return False

        if (
            prop_name == "file_path"
            and isinstance(node, VideoInputNode)
        ):
            node.close()

        prop.value = value

        self.invalidate_cache(
            node_id
        )

        self.notify_observers(
            ObserverEvent.NodeModified,
            node_id,
        )

        return True

    def set_node_positions(
        self,
        positions: dict[
            str,
            tuple[float, float],
        ],
    ) -> None:
        changed: dict[
            str,
            tuple[float, float],
        ] = {}

        for node_id, (x, y) in positions.items():
            node = self.nodes.get(node_id)

            if node is None:
                continue

            node.x = float(x)
            node.y = float(y)

            changed[node_id] = (
                node.x,
                node.y,
            )

        if changed:
            self.notify_observers(
                ObserverEvent.NodesMoved,
                changed,
            )

    # ==================================================================
    # Connections
    # ==================================================================

    def connect_nodes(
        self,
        output_node_id: str,
        output_slot: str,
        input_node_id: str,
        input_slot: str,
    ) -> bool:
        if (
            output_node_id not in self.nodes
            or input_node_id not in self.nodes
        ):
            return False

        output_node = self.nodes[
            output_node_id
        ]

        input_node = self.nodes[
            input_node_id
        ]

        if (
            output_slot not in output_node.outputs
            or input_slot not in input_node.inputs
        ):
            return False

        out_sock = output_node.outputs[
            output_slot
        ]

        in_sock = input_node.inputs[
            input_slot
        ]

        if not sockets_compatible(
            out_sock.socket_type,
            in_sock.socket_type,
        ):
            return False

        if self._would_create_cycle(
            output_node_id,
            input_node_id,
        ):
            return False

        for existing in list(
            self.connections
        ):
            if (
                existing.input_node_id
                == input_node_id
                and existing.input_slot
                == input_slot
            ):
                self.disconnect_nodes(
                    existing
                )

        connection = Connection(
            output_node_id,
            output_slot,
            input_node_id,
            input_slot,
        )

        self.connections.add(connection)

        self.dependency_graph.update(
            self.nodes,
            self.connections,
        )

        self.dependency_graph.invalidate_node(
            input_node_id
        )

        self.notify_observers(
            ObserverEvent.ConnectionCreated,
            connection,
        )

        if (
            input_node.node_type == "Viewer"
        ):
            self.set_active_viewer(
                input_node_id
            )

        return True

    def disconnect_nodes(
        self,
        connection: Connection,
    ) -> bool:
        if connection not in self.connections:
            return False

        self.connections.discard(
            connection
        )

        self.dependency_graph.update(
            self.nodes,
            self.connections,
        )

        self.dependency_graph.invalidate_node(
            connection.input_node_id
        )

        self.notify_observers(
            ObserverEvent.ConnectionRemoved,
            connection,
        )

        return True

    def _would_create_cycle(
        self,
        output_node_id: str,
        input_node_id: str,
    ) -> bool:
        downstream = (
            self.dependency_graph
            .get_downstream_nodes(
                input_node_id
            )
        )

        return output_node_id in downstream

    # ==================================================================
    # Evaluation
    # ==================================================================

    def evaluate_node(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str = "frame",
    ) -> Any | None:
        """Evaluate a node and its dependencies.

        Evaluation is serialized because Node instances are stateful.

        The important optimization here is that project-level evaluation
        state is initialized once per top-level evaluation instead of once
        per recursive node.
        """

        with self._eval_lock:
            root = (
                self._eval_context_depth == 0
            )

            if root:
                self._begin_eval_context(
                    frame_num
                )

            self._eval_context_depth += 1

            try:
                return self._evaluate_node_locked(
                    node_id,
                    frame_num,
                    output_slot,
                )

            finally:
                self._eval_context_depth -= 1

                if (
                    root
                    and self._eval_context_depth == 0
                ):
                    self._end_eval_context()

    def _begin_eval_context(
        self,
        frame_num: int,
    ) -> None:
        self._eval_context_frame = (
            frame_num
        )

        # Export evaluation is strictly sequential and never revisits a
        # frame, so drop the previous frame's intermediates before this
        # tree starts. This bounds peak memory to a single frame's result
        # set instead of the multi-gigabyte interactive LRU budget.
        if self._export_mode:
            self._export_frame_cache.clear()

        # Resolve preview settings once.
        self._eval_context_settings = (
            self.get_preview_settings()
        )

        self._eval_context_cache_width = (
            self._eval_context_settings.max_width
        )

        # Resolve property drives once.
        self._prepare_property_drive_overrides(
            frame_num
        )

    def _end_eval_context(self) -> None:
        self._eval_context_frame = None
        self._eval_context_settings = None
        self._eval_context_cache_width = None

    def set_export_mode(
        self,
        enabled: bool,
    ) -> None:
        """Select the evaluation cache strategy for sequential rendering.

        ``enabled=False`` (the interactive default) keeps the large
        cross-frame LRU, which is what makes scrubbing and playback cheap.

        ``enabled=True`` switches to a per-frame scratch cache. A linear
        export never re-reads an earlier frame, so the LRU only adds
        bookkeeping, memory pressure, and allocator churn while providing
        no cache hits. The scratch cache still deduplicates a node that is
        fanned out to several consumers *within* one frame.

        Callers must reset this to ``False`` when the export finishes.
        """

        enabled = bool(enabled)

        if self._export_mode == enabled:
            return

        self._export_mode = enabled
        self._export_frame_cache.clear()

    def _resolve_named_property_for_frame(
        self,
        node_name: str,
        property_key: str,
    ) -> float | None:
        """Bound resolver variant that reads the active evaluation frame.

        Bound once per project and handed to every node, which removes one
        closure allocation per node per evaluated frame.
        """

        frame_num = self._eval_context_frame

        if frame_num is None:
            return None

        return self._resolve_named_property_value(
            node_name,
            property_key,
            frame_num,
        )

    def _resolve_node_property_for_frame(
        self,
        node_id: str,
        property_key: str,
    ) -> float | None:
        """Bound resolver variant that reads the active evaluation frame."""

        frame_num = self._eval_context_frame

        if frame_num is None:
            return None

        return self._resolve_node_property_value(
            node_id,
            property_key,
            frame_num,
        )

    def _evaluate_node_locked(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str,
    ) -> Any | None:
        """Recursive evaluator.

        Called only while _eval_lock is held.
        """

        if node_id not in self.nodes:
            return None

        node = self.nodes[node_id]

        # --------------------------------------------------------------
        # Cache lookup
        # --------------------------------------------------------------
        #
        # Export mode uses a flat per-frame dict: no cache-slot string is
        # built, no LRU bookkeeping runs, and no byte-size estimation is
        # performed. The interactive path keeps the keyed LRU so proxy and
        # full-resolution results stay in separate namespaces.
        # --------------------------------------------------------------

        export_cache = self._export_frame_cache if self._export_mode else None

        if export_cache is not None:
            cache_key = (node_id, frame_num, output_slot)
            cached = export_cache.get(cache_key, _CACHE_MISS)
            if cached is not _CACHE_MISS:
                return cached
            settings = self._get_evaluation_settings()
            cache_slot = None
        else:
            settings = self._get_evaluation_settings()

            cache_slot = (
                f"{output_slot}@"
                f"{settings.max_width}"
            )

            cache_key = (
                node_id,
                frame_num,
                cache_slot,
            )

            cached = self._frame_cache.get_fast(cache_key)

            if cached is not None:
                return cached

        # --------------------------------------------------------------
        # Prepare node
        # --------------------------------------------------------------

        node.prepare_evaluation(
            self.width,
            self.height,
            preview_max_width=settings.max_width,
            project_fps=float(self.fps),
            frame_num=frame_num,
            project_max_frame=self.max_frame,
        )

        # --------------------------------------------------------------
        # Resolver setup
        # --------------------------------------------------------------
        #
        # The project owns one bound resolver pair and one reusable
        # drive-lookup / time-resampler per node. Assigning them is a
        # plain attribute store; nothing is allocated per frame.
        # --------------------------------------------------------------

        node.set_property_resolver(
            self._named_resolver_bound
        )

        node.set_node_property_resolver(
            self._node_resolver_bound
        )

        drive_lookup = node._drive_lookup

        if (
            drive_lookup is None
            or drive_lookup.owner is not self
            or drive_lookup.node_id != node_id
        ):
            drive_lookup = _NodeDriveLookup(
                self,
                self._drive_overrides,
                node_id,
            )
            node._drive_lookup = drive_lookup

        node.set_property_drive_lookup(
            drive_lookup
        )

        # --------------------------------------------------------------
        # Inputs
        # --------------------------------------------------------------

        node.clear_input_values()
        node.set_time_resampler(None)

        input_connections = (
            self.dependency_graph
            .get_input_connections(
                node_id
            )
        )

        for conn in input_connections:
            input_slot = conn.input_slot

            in_sock = node.inputs[
                input_slot
            ]

            # Node sockets pass the node ID rather than evaluating it.
            if (
                in_sock.socket_type
                == NodeSocketType.Node
            ):
                node.set_input_value(
                    input_slot,
                    conn.output_node_id,
                )
                continue

            dep_output = (
                self._evaluate_node_locked(
                    conn.output_node_id,
                    frame_num,
                    conn.output_slot,
                )
            )

            node.set_input_value(
                input_slot,
                dep_output,
            )

            if input_slot == "frame":
                resampler = node._eval_resampler

                if resampler is None or resampler.owner is not self:
                    resampler = _TimeResampler(
                        self,
                        self.evaluate_node,
                    )
                    node._eval_resampler = resampler

                resampler.bind(
                    conn.output_node_id,
                    conn.output_slot,
                )

                node.set_time_resampler(
                    resampler
                )

        # --------------------------------------------------------------
        # Evaluate
        # --------------------------------------------------------------

        try:
            raw_result = node.evaluate(
                frame_num
            )

            if isinstance(
                raw_result,
                dict,
            ):
                result = raw_result.get(
                    output_slot
                )
            else:
                result = raw_result

            # Viewer is intentionally not cached because it is just a
            # passthrough endpoint.
            if node.node_type != "Viewer":
                if export_cache is not None:
                    export_cache[cache_key] = result
                else:
                    self._frame_cache.set_fast(
                        cache_key,
                        result,
                    )

            return result

        except Exception as exc:  # noqa: BLE001
            node.log_exception(exc)
            return None

    # ==================================================================
    # Property Drive
    # ==================================================================

    def _prepare_property_drive_overrides(
        self,
        frame_num: int,
    ) -> None:
        """Resolve all active Property Drive nodes once per frame."""

        if (
            self._drive_overrides_frame
            == frame_num
        ):
            return

        self._drive_overrides_frame = (
            frame_num
        )

        overrides = self._drive_overrides
        overrides.clear()

        # Previously this scanned ALL nodes. We now only visit nodes that
        # were indexed as Property Drive nodes.
        for drive_id in tuple(
            self._property_drive_ids
        ):
            drive = self.nodes.get(
                drive_id
            )

            if drive is None:
                continue

            if not drive.bool_value(
                "enabled",
                True,
            ):
                continue

            target_id = (
                property_drive_target_id(
                    self,
                    drive_id,
                )
            )

            if target_id is None:
                continue

            property_key = (
                drive.string_value(
                    PROPERTY_DRIVE_PROPERTY_KEY,
                    "",
                ).strip()
            )

            if not property_key:
                continue

            resolved = (
                self._resolve_drive_input_value(
                    drive_id,
                    frame_num,
                )
            )

            overrides[
                (
                    target_id,
                    property_key,
                )
            ] = resolved

    def _ensure_property_drive_overrides(
        self,
        frame_num: int,
    ) -> None:
        """Compatibility wrapper."""

        self._prepare_property_drive_overrides(
            frame_num
        )

    def _resolve_drive_input_value(
        self,
        drive_id: str,
        frame_num: int,
    ) -> float:
        drive = self.nodes.get(
            drive_id
        )

        if drive is None:
            return 0.0

        for connection in (
            self.dependency_graph
            .get_input_connections(
                drive_id
            )
        ):
            if (
                connection.input_slot
                != PROPERTY_DRIVE_VALUE_SLOT
            ):
                continue

            result = (
                self._evaluate_node_locked(
                    connection.output_node_id,
                    frame_num,
                    connection.output_slot,
                )
            )

            if (
                isinstance(
                    result,
                    (int, float),
                )
                and not isinstance(
                    result,
                    bool,
                )
            ):
                return float(result)

        fallback = drive.get_property(
            "fallback"
        )

        if (
            fallback is None
            or not isinstance(
                fallback.value,
                (int, float),
            )
        ):
            return 0.0

        return float(
            fallback.value
        )

    # ==================================================================
    # Property links
    # ==================================================================

    def _resolve_named_property_value(
        self,
        node_name: str,
        property_key: str,
        frame_num: int,
    ) -> float | None:
        """Resolve a property without scanning every project node."""

        candidates = (
            self._nodes_by_name.get(
                node_name
            )
        )

        if not candidates:
            return None

        for node in candidates:
            prop = node.get_property(
                property_key
            )

            if prop is None:
                return None

            curve = node.animated_properties.get(
                property_key
            )

            if (
                curve is not None
                and not curve.is_empty
                and isinstance(
                    prop.value,
                    (int, float),
                )
                and not isinstance(
                    prop.value,
                    bool,
                )
            ):
                return curve.value_at(
                    frame_num
                )

            if (
                isinstance(
                    prop.value,
                    (int, float),
                )
                and not isinstance(
                    prop.value,
                    bool,
                )
            ):
                return float(
                    prop.value
                )

            return None

        return None

    def _resolve_node_property_value(
        self,
        node_id: str,
        property_key: str,
        frame_num: int,
    ) -> float | None:
        """Resolve a numeric property directly by node ID."""

        driven = self._drive_overrides.get(
            (
                node_id,
                property_key,
            )
        )

        if driven is not None:
            return driven

        node = self.nodes.get(
            node_id
        )

        if node is None:
            return None

        prop = node.get_property(
            property_key
        )

        if prop is None:
            return None

        curve = node.animated_properties.get(
            property_key
        )

        if (
            curve is not None
            and not curve.is_empty
            and isinstance(
                prop.value,
                (int, float),
            )
            and not isinstance(
                prop.value,
                bool,
            )
        ):
            return curve.value_at(
                frame_num
            )

        if (
            prop.input_type
            == NodePropertyInputType.Checkbox
        ):
            return (
                1.0
                if bool(prop.value)
                else 0.0
            )

        if (
            isinstance(
                prop.value,
                (int, float),
            )
            and not isinstance(
                prop.value,
                bool,
            )
        ):
            return float(
                prop.value
            )

        return None

    # ==================================================================
    # Timeline / playback
    # ==================================================================

    def set_frame(
        self,
        frame_num: int,
    ) -> None:
        self.current_frame = max(
            0,
            min(
                frame_num,
                self.max_frame,
            ),
        )

        self.notify_observers(
            ObserverEvent.FrameChanged,
            self.current_frame,
        )

    def set_active_viewer(
        self,
        node_id: str | None,
    ) -> bool:
        if (
            node_id is not None
            and node_id not in self.nodes
        ):
            return False

        if self.active_viewer == node_id:
            return True

        self.active_viewer = node_id

        self.notify_observers(
            ObserverEvent.ActiveViewerChanged,
            node_id,
        )

        return True

    def sync_timeline_from_media(
        self,
        *,
        fps: float,
        duration_sec: float,
        width: int,
        height: int,
        frame_count: int | None = None,
    ) -> None:
        """Align project timeline and frame size with loaded media."""

        resolved_fps = max(
            1,
            round(fps),
        )

        resolved_duration = max(
            0.1,
            float(duration_sec),
        )

        resolved_frame_count = (
            int(frame_count)
            if frame_count is not None
            else 0
        )

        if resolved_frame_count <= 0:
            resolved_frame_count = max(
                1,
                int(
                    round(
                        resolved_duration
                        * resolved_fps
                    )
                ),
            )

        self.fps = resolved_fps

        self.duration = max(
            resolved_duration,
            resolved_frame_count
            / float(resolved_fps),
        )

        self._timeline_frame_count = (
            resolved_frame_count
        )

        self.width = max(
            1,
            width,
        )

        self.height = max(
            1,
            height,
        )

        self.current_frame = min(
            self.current_frame,
            self.max_frame,
        )

        self.clear_cache()

        self.notify_observers(
            ObserverEvent.ProjectModified,
            None,
        )

        self.notify_observers(
            ObserverEvent.FrameChanged,
            self.current_frame,
        )

    # ==================================================================
    # Logging / observers
    # ==================================================================

    def log_exception(
        self,
        e: Exception,
    ) -> None:
        from utils.logging_setup import get_logger

        self.exceptions_log.append(e)

        get_logger(
            "project"
        ).error(
            "Project error: %s",
            e,
            exc_info=e,
        )

    def subscribe(
        self,
        observer: Callable[
            [ObserverEvent, Any],
            None,
        ],
    ) -> None:
        self.observers.append(
            observer
        )

    def unsubscribe(
        self,
        observer: Callable[
            [ObserverEvent, Any],
            None,
        ],
    ) -> None:
        try:
            self.observers.remove(
                observer
            )
        except ValueError:
            pass

    def notify_observers(
        self,
        event: ObserverEvent,
        data: Any,
    ) -> None:
        for observer in self.observers:
            try:
                observer(
                    event,
                    data,
                )
            except Exception as exc:  # noqa: BLE001
                self.log_exception(
                    exc
                )

    # ==================================================================
    # Serialization
    # ==================================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": APH_FORMAT_ID,
            "version": APH_FORMAT_VERSION,
            "name": self.name,
            "timeline": {
                "fps": int(self.fps),
                "width": int(self.width),
                "height": int(self.height),
                "duration": float(
                    self.duration
                ),
                "current_frame": int(
                    self.current_frame
                ),
            },
            "active_viewer": self.active_viewer,
            "nodes": {
                node_id: node.to_dict()
                for node_id, node in self.nodes.items()
            },
            "connections": [
                {
                    "output_node_id":
                        conn.output_node_id,
                    "output_slot":
                        conn.output_slot,
                    "input_node_id":
                        conn.input_node_id,
                    "input_slot":
                        conn.input_slot,
                }
                for conn in sorted(
                    self.connections,
                    key=lambda item: (
                        item.output_node_id,
                        item.output_slot,
                        item.input_node_id,
                        item.input_slot,
                    ),
                )
            ],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "Project":
        format_id = data.get(
            "format",
            APH_FORMAT_ID,
        )

        if format_id != APH_FORMAT_ID:
            raise ValueError(
                f"Unsupported project format: {format_id!r}"
            )

        version = int(
            data.get(
                "version",
                1,
            )
        )

        if version > APH_FORMAT_VERSION:
            raise ValueError(
                f"Project version {version} is newer "
                f"than supported {APH_FORMAT_VERSION}"
            )

        timeline = data.get(
            "timeline"
        )

        if not isinstance(
            timeline,
            dict,
        ):
            timeline = {
                "fps": data.get(
                    "fps",
                    DEFAULT_FPS,
                ),
                "width": data.get(
                    "width",
                    DEFAULT_WIDTH,
                ),
                "height": data.get(
                    "height",
                    DEFAULT_HEIGHT,
                ),
                "duration": data.get(
                    "duration",
                    DEFAULT_DURATION,
                ),
                "current_frame": data.get(
                    "current_frame",
                    0,
                ),
            }

        project = cls(
            str(
                data.get(
                    "name",
                    "Untitled Project",
                )
            )
        )

        project.fps = max(
            1,
            int(
                timeline.get(
                    "fps",
                    DEFAULT_FPS,
                )
            ),
        )

        project.width = max(
            1,
            int(
                timeline.get(
                    "width",
                    DEFAULT_WIDTH,
                )
            ),
        )

        project.height = max(
            1,
            int(
                timeline.get(
                    "height",
                    DEFAULT_HEIGHT,
                )
            ),
        )

        project.duration = max(
            0.1,
            float(
                timeline.get(
                    "duration",
                    DEFAULT_DURATION,
                )
            ),
        )

        project._timeline_frame_count = max(
            0,
            int(
                round(
                    project.duration
                    * project.fps
                )
            ),
        )

        project.current_frame = max(
            0,
            int(
                timeline.get(
                    "current_frame",
                    0,
                )
            ),
        )

        project.current_frame = min(
            project.current_frame,
            project.max_frame,
        )

        nodes_data = data.get(
            "nodes",
            {},
        )

        if isinstance(
            nodes_data,
            dict,
        ):
            for node_id, node_blob in nodes_data.items():
                if not isinstance(
                    node_blob,
                    dict,
                ):
                    continue

                node_type = str(
                    node_blob.get(
                        "node_type",
                        "",
                    )
                )

                node_category = str(
                    node_blob.get(
                        "node_category",
                        "",
                    )
                )

                if not node_type:
                    continue

                node = (
                    global_node_registry.create_node(
                        node_type,
                        category=(
                            node_category
                            or None
                        ),
                    )
                )

                if node is None:
                    # Custom nodes embed their own subgraph definition, so a
                    # project stays portable even when the definition was
                    # never saved to this machine's global store.
                    from core.nodes.custom_nodes import \
                        create_custom_node_from_document

                    node = create_custom_node_from_document(
                        node_blob
                    )

                if node is None:
                    project.log_exception(
                        ValueError(
                            "Unknown node type: "
                            f"{node_category}.{node_type}"
                        )
                    )
                    continue

                node.apply_document(
                    node_blob
                )

                project.add_node(
                    node,
                    node_id=str(node_id),
                )

        connections_data = data.get(
            "connections",
            [],
        )

        if isinstance(
            connections_data,
            list,
        ):
            for conn_blob in connections_data:
                if not isinstance(
                    conn_blob,
                    dict,
                ):
                    continue

                project.connect_nodes(
                    str(
                        conn_blob.get(
                            "output_node_id",
                            "",
                        )
                    ),
                    str(
                        conn_blob.get(
                            "output_slot",
                            "",
                        )
                    ),
                    str(
                        conn_blob.get(
                            "input_node_id",
                            "",
                        )
                    ),
                    str(
                        conn_blob.get(
                            "input_slot",
                            "",
                        )
                    ),
                )

        active = data.get(
            "active_viewer"
        )

        if (
            isinstance(active, str)
            and active in project.nodes
        ):
            project.set_active_viewer(
                active
            )

        elif project.active_viewer is None:
            for node_id, node in (
                project.nodes.items()
            ):
                if node.node_type == "Viewer":
                    project.set_active_viewer(
                        node_id
                    )
                    break

        return project

    # ==================================================================
    # Cleanup
    # ==================================================================

    def close(self) -> None:
        """Release media handles."""

        for node in list(
            self.nodes.values()
        ):
            if isinstance(
                node,
                VideoInputNode,
            ):
                node.close()
