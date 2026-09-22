"""Baked video input node used by the graph freeze operation."""

from __future__ import annotations

from core.nodes.video_input import VideoInputNode


class FrozenVideoInputNode(VideoInputNode):
    """Read a pre-rendered subgraph result as ordinary timeline media."""

    node_type = "Frozen Video Input"
    node_description = "Read a baked graph section without evaluating its upstream nodes"
    node_color = (62, 154, 190)
