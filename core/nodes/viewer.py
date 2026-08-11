"""Viewer node that displays an incoming frame stream."""

import numpy as np

from core.nodes.base import Node, NodeSocketType


class ViewerNode(Node):
    """Connects to an input source to view a video stream."""

    node_type = "Viewer"
    node_category = "Input/Output"
    node_description = "Connects to an input source to view a video stream"
    node_color = (200, 50, 50)

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> np.ndarray:
        input_frame = self.get_input_value("frame")
        if input_frame is None:
            return self.blank_frame()
        return input_frame
