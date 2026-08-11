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
from core.nodes import Node


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
        self.observers: list[Callable[[ObserverEvent, Any], None]] = []
        self.exceptions_log: list[Exception] = []

        self._frame_cache = FrameCache(max_mb=FRAME_CACHE_MAX_MB)
        self.dependency_graph = DependencyGraph(self.nodes, self.connections, self._frame_cache)

    @property
    def max_frame(self) -> int:
        return int(self.duration * self.fps)

    def log_exception(self, e: Exception) -> None:
        self.exceptions_log.append(e)

    def add_node(self, node: Node) -> str:
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

        del self.nodes[node_id]
        self.dependency_graph.invalidate_node(node_id)
        self.dependency_graph.update(self.nodes, self.connections)
        self.notify_observers(ObserverEvent.NodeRemoved, node_id)

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

    def evaluate_node(
        self,
        node_id: str,
        frame_num: int,
        output_slot: str = "frame",
    ) -> Any | None:
        if node_id not in self.nodes:
            return None

        node = self.nodes[node_id]
        cached = self.dependency_graph.get_cached(node_id, frame_num, output_slot)
        if cached is not None:
            return cached

        node.prepare_evaluation(self.width, self.height)

        for conn in self.dependency_graph.get_input_connections(node_id):
            dep_output = self.evaluate_node(
                conn.output_node_id,
                frame_num,
                conn.output_slot,
            )
            node.set_input_value(conn.input_slot, dep_output)

        try:
            result = node.evaluate(frame_num)
            self.dependency_graph.set_cached(node_id, frame_num, output_slot, result)
            return result
        except Exception as e:  # noqa: BLE001
            node.log_exception(e)
            return None

    def invalidate_cache(self, node_id: str) -> None:
        self.dependency_graph.invalidate_node(node_id)
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
        return {
            "name": self.name,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "connections": [
                {
                    "output_node_id": c.output_node_id,
                    "output_slot": c.output_slot,
                    "input_node_id": c.input_node_id,
                    "input_slot": c.input_slot,
                }
                for c in self.connections
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        project = cls(data.get("name", "Untitled"))
        project.fps = data.get("fps", DEFAULT_FPS)
        project.width = data.get("width", DEFAULT_WIDTH)
        project.height = data.get("height", DEFAULT_HEIGHT)
        project.duration = data.get("duration", DEFAULT_DURATION)
        return project
