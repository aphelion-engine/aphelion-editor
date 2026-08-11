import time
from collections.abc import Callable
from typing import Any

from config.constants import (
    DEFAULT_DURATION,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    FRAME_CACHE_MAX_MB,
)
from core.cache import FrameCache
from core.events import Connection, ObserverEvent
from core.graph import DependencyGraph
from core.nodes import Node, VideoInputNode, global_node_registry
from core.serialization import APH_FORMAT_ID, APH_FORMAT_VERSION
from render.preview import PreviewSettings


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

        self.active_viewer: str | None = None
        self.file_path: str | None = None
        self.observers: list[Callable[[ObserverEvent, Any], None]] = []
        self.exceptions_log: list[Exception] = []

        self._frame_cache = FrameCache(max_mb=FRAME_CACHE_MAX_MB)
        self.dependency_graph = DependencyGraph(self.nodes, self.connections, self._frame_cache)

    @property
    def max_frame(self) -> int:
        return int(self.duration * self.fps)

    def log_exception(self, e: Exception) -> None:
        """Record ``e`` on the project and emit it to the app logger."""
        from utils.logging_setup import get_logger

        self.exceptions_log.append(e)
        get_logger("project").error("Project error: %s", e, exc_info=e)

    def add_node(self, node: Node, node_id: str | None = None) -> str:
        """Register ``node``. Optional ``node_id`` restores a stable undo id."""
        if node_id is not None and node_id in self.nodes:
            node_id = None
        if node_id is None:
            node_id = f"node_{len(self.nodes)}_{int(time.time() * 1000)}"
        self.nodes[node_id] = node
        self.dependency_graph.update(self.nodes, self.connections)
        self.notify_observers(ObserverEvent.NodeAdded, node_id)
        if node.node_type == "Viewer" and self.active_viewer is None:
            self.set_active_viewer(node_id)
        return node_id

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return

        self.connections = {
            c
            for c in self.connections
            if c.output_node_id != node_id and c.input_node_id != node_id
        }

        if self.active_viewer == node_id:
            self.active_viewer = None

        node = self.nodes[node_id]
        if isinstance(node, VideoInputNode):
            node.close()

        del self.nodes[node_id]
        self.dependency_graph.invalidate_node(node_id)
        self.dependency_graph.update(self.nodes, self.connections)
        self.notify_observers(ObserverEvent.NodeRemoved, node_id)

    def set_node_property(
        self,
        node_id: str,
        prop_name: str,
        value: Any,
    ) -> bool:
        """Set a node property and notify observers (undoable via history)."""
        node = self.nodes.get(node_id)
        if node is None:
            return False
        prop = node.get_property(prop_name)
        if prop is None:
            return False
        # Close the capture before swapping paths so probe/decode never overlap.
        if prop_name == "file_path" and isinstance(node, VideoInputNode):
            node.close()
        prop.value = value
        self.invalidate_cache(node_id)
        self.notify_observers(ObserverEvent.NodeModified, node_id)
        return True

    def set_node_positions(
        self,
        positions: dict[str, tuple[float, float]],
    ) -> None:
        """Batch-update node positions and notify the graph view."""
        changed: dict[str, tuple[float, float]] = {}
        for node_id, (x, y) in positions.items():
            node = self.nodes.get(node_id)
            if node is None:
                continue
            node.x = float(x)
            node.y = float(y)
            changed[node_id] = (node.x, node.y)
        if changed:
            self.notify_observers(ObserverEvent.NodesMoved, changed)

    def connect_nodes(
        self,
        output_node_id: str,
        output_slot: str,
        input_node_id: str,
        input_slot: str,
    ) -> bool:
        if output_node_id not in self.nodes or input_node_id not in self.nodes:
            return False

        output_node = self.nodes[output_node_id]
        input_node = self.nodes[input_node_id]

        if output_slot not in output_node.outputs or input_slot not in input_node.inputs:
            return False

        out_sock = output_node.outputs[output_slot]
        in_sock = input_node.inputs[input_slot]
        if out_sock.socket_type != in_sock.socket_type:
            return False

        if self._would_create_cycle(output_node_id, input_node_id):
            return False

        # One connection per input socket: replace any existing link.
        for existing in list(self.connections):
            if (
                existing.input_node_id == input_node_id
                and existing.input_slot == input_slot
            ):
                self.disconnect_nodes(existing)

        connection = Connection(output_node_id, output_slot, input_node_id, input_slot)
        self.connections.add(connection)
        self.dependency_graph.update(self.nodes, self.connections)
        self.dependency_graph.invalidate_node(input_node_id)
        self.notify_observers(ObserverEvent.ConnectionCreated, connection)

        # Connecting into a Viewer makes it the active preview target.
        if input_node.node_type == "Viewer":
            self.set_active_viewer(input_node_id)
        return True

    def disconnect_nodes(self, connection: Connection) -> bool:
        if connection not in self.connections:
            return False

        self.connections.discard(connection)
        self.dependency_graph.update(self.nodes, self.connections)
        self.dependency_graph.invalidate_node(connection.input_node_id)
        self.notify_observers(ObserverEvent.ConnectionRemoved, connection)
        return True

    def _would_create_cycle(self, output_node_id: str, input_node_id: str) -> bool:
        downstream = self.dependency_graph.get_downstream_nodes(input_node_id)
        return output_node_id in downstream

    def get_preview_settings(self) -> PreviewSettings:
        """Resolve decode/display settings from the active Viewer."""
        viewer = (
            self.nodes.get(self.active_viewer)
            if self.active_viewer is not None
            else None
        )
        return PreviewSettings.from_viewer(viewer)

    def _preview_cache_slot(self, output_slot: str) -> str:
        """Namespace cache entries by proxy width so quality changes stay coherent."""
        return f"{output_slot}@{self.get_preview_settings().max_width}"

    def evaluate_node(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str = "frame",
    ) -> Any | None:
        if node_id not in self.nodes:
            return None

        node = self.nodes[node_id]
        settings = self.get_preview_settings()
        cache_slot = self._preview_cache_slot(output_slot)
        cached = self.dependency_graph.get_cached(node_id, frame_num, cache_slot)
        if cached is not None:
            return cached

        node.prepare_evaluation(
            self.width,
            self.height,
            preview_max_width=settings.max_width,
            project_fps=float(self.fps),
        )

        for conn in self.dependency_graph.get_input_connections(node_id):
            dep_output = self.evaluate_node(
                conn.output_node_id,
                frame_num,
                conn.output_slot,
            )
            node.set_input_value(conn.input_slot, dep_output)

        try:
            result = node.evaluate(frame_num)
            # Viewer is a cheap passthrough — cache producers only to avoid
            # double-counting the same buffer in the LRU budget.
            if node.node_type != "Viewer":
                self.dependency_graph.set_cached(
                    node_id,
                    frame_num,
                    cache_slot,
                    result,
                )
            return result
        except Exception as e:  # noqa: BLE001
            node.log_exception(e)
            return None

    def invalidate_cache(self, node_id: str) -> None:
        self.dependency_graph.invalidate_node(node_id)
        # Viewer playback knobs affect decode size for the whole graph.
        node = self.nodes.get(node_id)
        if node is not None and node.node_type == "Viewer":
            self.clear_cache()
        self.notify_observers(ObserverEvent.NodeModified, node_id)

    def clear_cache(self) -> None:
        self.dependency_graph.clear_cache()

    def set_frame(self, frame_num: int) -> None:
        self.current_frame = max(0, min(frame_num, self.max_frame))
        self.notify_observers(ObserverEvent.FrameChanged, self.current_frame)

    def set_active_viewer(self, node_id: str | None) -> bool:
        if node_id is not None and node_id not in self.nodes:
            return False
        if self.active_viewer == node_id:
            return True
        self.active_viewer = node_id
        self.notify_observers(ObserverEvent.ActiveViewerChanged, node_id)
        return True

    def sync_timeline_from_media(
        self,
        *,
        fps: float,
        duration_sec: float,
        width: int,
        height: int,
    ) -> None:
        """Align project timeline and frame size with loaded media."""
        self.fps = max(1, int(round(fps)))
        self.duration = max(0.1, float(duration_sec))
        self.width = max(1, width)
        self.height = max(1, height)
        self.current_frame = min(self.current_frame, self.max_frame)
        self.clear_cache()
        self.notify_observers(ObserverEvent.ProjectModified, None)
        self.notify_observers(ObserverEvent.FrameChanged, self.current_frame)

    def subscribe(self, observer: Callable[[ObserverEvent, Any], None]) -> None:
        self.observers.append(observer)

    def unsubscribe(self, observer: Callable[[ObserverEvent, Any], None]) -> None:
        if observer in self.observers:
            self.observers.remove(observer)

    def notify_observers(self, event: ObserverEvent, data: Any) -> None:
        for observer in self.observers:
            try:
                observer(event, data)
            except Exception as e:  # noqa: BLE001
                self.log_exception(e)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full project document for ``.aph`` persistence."""
        return {
            "format": APH_FORMAT_ID,
            "version": APH_FORMAT_VERSION,
            "name": self.name,
            "timeline": {
                "fps": int(self.fps),
                "width": int(self.width),
                "height": int(self.height),
                "duration": float(self.duration),
                "current_frame": int(self.current_frame),
            },
            "active_viewer": self.active_viewer,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "connections": [
                {
                    "output_node_id": conn.output_node_id,
                    "output_slot": conn.output_slot,
                    "input_node_id": conn.input_node_id,
                    "input_slot": conn.input_slot,
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
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        """Rebuild a project (nodes, wires, timeline) from a document dict.

        Parameters:
            data: Document produced by ``to_dict`` / a ``.aph`` file.

        Returns:
            A fully populated ``Project`` instance.

        Raises:
            ValueError: When the document format/version is unsupported.
        """
        format_id = data.get("format", APH_FORMAT_ID)
        if format_id != APH_FORMAT_ID:
            raise ValueError(f"Unsupported project format: {format_id!r}")

        version = int(data.get("version", 1))
        if version > APH_FORMAT_VERSION:
            raise ValueError(
                f"Project version {version} is newer than supported "
                f"{APH_FORMAT_VERSION}"
            )

        timeline = data.get("timeline")
        if not isinstance(timeline, dict):
            # Legacy flat layout (pre-.aph).
            timeline = {
                "fps": data.get("fps", DEFAULT_FPS),
                "width": data.get("width", DEFAULT_WIDTH),
                "height": data.get("height", DEFAULT_HEIGHT),
                "duration": data.get("duration", DEFAULT_DURATION),
                "current_frame": data.get("current_frame", 0),
            }

        project = cls(str(data.get("name", "Untitled Project")))
        project.fps = max(1, int(timeline.get("fps", DEFAULT_FPS)))
        project.width = max(1, int(timeline.get("width", DEFAULT_WIDTH)))
        project.height = max(1, int(timeline.get("height", DEFAULT_HEIGHT)))
        project.duration = max(0.1, float(timeline.get("duration", DEFAULT_DURATION)))
        project.current_frame = max(0, int(timeline.get("current_frame", 0)))
        project.current_frame = min(project.current_frame, project.max_frame)

        nodes_data = data.get("nodes", {})
        if isinstance(nodes_data, dict):
            for node_id, node_blob in nodes_data.items():
                if not isinstance(node_blob, dict):
                    continue
                node_type = str(node_blob.get("node_type", ""))
                node_category = str(node_blob.get("node_category", ""))
                if not node_type:
                    continue
                node = global_node_registry.create_node(
                    node_type,
                    category=node_category or None,
                )
                if node is None:
                    project.log_exception(
                        ValueError(f"Unknown node type: {node_category}.{node_type}")
                    )
                    continue
                node.apply_document(node_blob)
                project.add_node(node, node_id=str(node_id))

        connections_data = data.get("connections", [])
        if isinstance(connections_data, list):
            for conn_blob in connections_data:
                if not isinstance(conn_blob, dict):
                    continue
                project.connect_nodes(
                    str(conn_blob.get("output_node_id", "")),
                    str(conn_blob.get("output_slot", "")),
                    str(conn_blob.get("input_node_id", "")),
                    str(conn_blob.get("input_slot", "")),
                )

        active = data.get("active_viewer")
        if isinstance(active, str) and active in project.nodes:
            project.set_active_viewer(active)
        elif project.active_viewer is None:
            for node_id, node in project.nodes.items():
                if node.node_type == "Viewer":
                    project.set_active_viewer(node_id)
                    break

        return project

    def close(self) -> None:
        """Release media handles held by nodes (safe before discarding)."""
        for node in list(self.nodes.values()):
            if isinstance(node, VideoInputNode):
                node.close()
