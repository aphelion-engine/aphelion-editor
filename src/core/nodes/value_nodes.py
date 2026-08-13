"""Timeline and project scalar sources for graph modulation."""

from __future__ import annotations

from core.nodes.base import NodeSocketType, NodeValue
from core.nodes.frame_base import FrameNode

VALUES_CATEGORY: str = "Values"


class TimelineFrameNode(FrameNode):
    """Emit the current timeline frame index as a Number."""

    node_type: str = "Frame"
    node_category: str = VALUES_CATEGORY
    node_description: str = "Output the current timeline frame number"
    node_color: tuple[int, int, int] = (88, 164, 148)

    def _setup_sockets(self) -> None:
        """Register the frame Number output."""
        self.add_output("value", NodeSocketType.Number)

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the active evaluation frame."""
        return float(frame_num)


class TimelineTimeNode(FrameNode):
    """Emit the current timeline time in seconds."""

    node_type: str = "Time"
    node_category: str = VALUES_CATEGORY
    node_description: str = "Output the current timeline time in seconds"
    node_color: tuple[int, int, int] = (94, 168, 152)

    def _setup_sockets(self) -> None:
        """Register the time Number output."""
        self.add_output("value", NodeSocketType.Number)

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return ``frame / fps`` using the project frame rate."""
        fps: float = max(1.0, self._project_fps)
        return float(frame_num) / fps


class TimelineFpsNode(FrameNode):
    """Emit the project frame rate."""

    node_type: str = "FPS"
    node_category: str = VALUES_CATEGORY
    node_description: str = "Output the project frames-per-second"
    node_color: tuple[int, int, int] = (100, 172, 156)

    def _setup_sockets(self) -> None:
        """Register the fps Number output."""
        self.add_output("value", NodeSocketType.Number)

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the project fps."""
        del frame_num
        return max(1.0, self._project_fps)


class TimelineMaxFrameNode(FrameNode):
    """Emit the last frame index on the project timeline."""

    node_type: str = "Max Frame"
    node_category: str = VALUES_CATEGORY
    node_description: str = "Output the last frame index on the timeline"
    node_color: tuple[int, int, int] = (106, 176, 160)

    def _setup_sockets(self) -> None:
        """Register the max-frame Number output."""
        self.add_output("value", NodeSocketType.Number)

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return the project max frame index."""
        del frame_num
        return float(self._project_max_frame)


class TimelineNormalizedNode(FrameNode):
    """Emit the playhead position normalized to 0–1 over the timeline."""

    node_type: str = "Normalized Time"
    node_category: str = VALUES_CATEGORY
    node_description: str = "Output the playhead as 0 at frame 0 and 1 at max frame"
    node_color: tuple[int, int, int] = (112, 180, 164)

    def _setup_sockets(self) -> None:
        """Register the normalized Number output."""
        self.add_output("value", NodeSocketType.Number)

    def evaluate(self, frame_num: int) -> NodeValue:
        """Return ``frame / max_frame``, clamped to ``[0, 1]``."""
        max_frame: int = max(0, self._project_max_frame)
        if max_frame <= 0:
            return 0.0
        return max(0.0, min(1.0, float(frame_num) / float(max_frame)))
