"""Image helpers for vision-capable models.

Both helpers return a ``data:image/png;base64,...`` URL, or ``None`` when the
image cannot be produced. They are deliberately defensive: a headless test, a
missing Qt platform plugin, or an unevaluated graph must degrade to "vision is
unavailable" rather than raising into the agent loop.
"""

from __future__ import annotations

import base64
from typing import Any


def graph_snapshot_data_url(
    project: Any,
    *,
    node_ids: list[str] | None = None,
    max_width: int = 1400,
) -> str | None:
    """Render the project graph to a PNG data URL."""
    try:
        from core.graph_exchange import project_to_graph
        from core.graph_renderer import GraphRenderOptions, render_graph_image
    except Exception:  # noqa: BLE001 - Qt or the renderer may be unavailable
        return None

    try:
        document = project_to_graph(
            project,
            node_ids=set(node_ids) if node_ids else None,
        )
        options = GraphRenderOptions(
            scale=1.0,
            highlight_ids=tuple(node_ids or ()),
            max_width=max_width,
        )
        image = render_graph_image(document, options)
    except Exception:  # noqa: BLE001
        return None
    return _qimage_to_data_url(image)


def preview_frame_data_url(
    project: Any,
    *,
    frame: int | None = None,
    max_width: int = 640,
) -> str | None:
    """Render the current evaluated preview to a PNG data URL."""
    try:
        import numpy as np
        from PyQt6.QtGui import QImage
    except Exception:  # noqa: BLE001
        return None

    viewer_id = getattr(project, "active_viewer", None)
    if not viewer_id:
        return None
    frame_num = int(project.current_frame if frame is None else frame)
    try:
        result = project.evaluate_node(viewer_id, frame_num, "frame")
    except Exception:  # noqa: BLE001 - a broken graph must not break the tool
        return None
    if result is None:
        return None

    pixels = getattr(result, "frame", result)
    if not isinstance(pixels, np.ndarray) or pixels.ndim < 3:
        return None

    try:
        rgb = np.ascontiguousarray(pixels[:, :, :3])
        if rgb.dtype != np.uint8:
            rgb = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
        height, width = rgb.shape[:2]
        if width > max_width > 0:
            step = max(1, width // max_width)
            rgb = rgb[::step, ::step]
            height, width = rgb.shape[:2]
        image = QImage(
            rgb.data,
            width,
            height,
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
    except Exception:  # noqa: BLE001
        return None
    return _qimage_to_data_url(image)


def _qimage_to_data_url(image: Any) -> str | None:
    """Encode a ``QImage`` as a base64 PNG data URL."""
    try:
        from PyQt6.QtCore import QBuffer, QByteArray
    except Exception:  # noqa: BLE001
        return None
    if image is None:
        return None
    try:
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            return None
        payload = bytes(buffer.data())
    except Exception:  # noqa: BLE001
        return None
    if not payload:
        return None
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


__all__ = ["graph_snapshot_data_url", "preview_frame_data_url"]
