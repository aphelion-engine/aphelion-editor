"""Editor dock layout presets and reset helpers."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QMainWindow

if TYPE_CHECKING:
    pass


class LayoutMode(Enum):
    """Named workspace arrangements for the main editor."""

    DEFAULT = "default"
    EDITING = "editing"
    PREVIEW = "preview"
    COMPACT = "compact"


LAYOUT_LABELS: dict[LayoutMode, str] = {
    LayoutMode.DEFAULT: "Default",
    LayoutMode.EDITING: "Editing (Graph Focus)",
    LayoutMode.PREVIEW: "Preview (Viewport Focus)",
    LayoutMode.COMPACT: "Compact",
}


class EditorDocks:
    """Typed handle to the editor's dock widgets."""

    def __init__(
        self,
        *,
        viewport: QDockWidget,
        node_graph: QDockWidget,
        timeline: QDockWidget,
        properties: QDockWidget,
        keyframes: QDockWidget,
        logs: QDockWidget,
        media_pool: QDockWidget,
    ) -> None:
        self.viewport = viewport
        self.node_graph = node_graph
        self.timeline = timeline
        self.properties = properties
        self.keyframes = keyframes
        self.logs = logs
        self.media_pool = media_pool

    def all(self) -> tuple[QDockWidget, ...]:
        return (
            self.viewport,
            self.node_graph,
            self.timeline,
            self.properties,
        )

    def optional(self) -> tuple[QDockWidget, ...]:
        """Panels excluded from layout presets but togglable from the Window menu."""
        return (self.logs, self.media_pool, self.keyframes)


def _show_all(docks: EditorDocks) -> None:
    for dock in docks.all():
        dock.show()
        dock.setFloating(False)


def apply_layout(
    window: QMainWindow,
    docks: EditorDocks,
    mode: LayoutMode,
) -> None:
    """Rearrange docks into a named workspace preset."""
    _show_all(docks)

    # Detach from current areas so addDockWidget places are deterministic.
    for dock in docks.all():
        window.removeDockWidget(dock)
        dock.setVisible(True)

    left = Qt.DockWidgetArea.LeftDockWidgetArea
    right = Qt.DockWidgetArea.RightDockWidgetArea
    bottom = Qt.DockWidgetArea.BottomDockWidgetArea

    if mode == LayoutMode.DEFAULT:
        window.addDockWidget(left, docks.viewport)
        window.addDockWidget(left, docks.node_graph)
        window.splitDockWidget(docks.viewport, docks.node_graph, Qt.Orientation.Vertical)
        window.addDockWidget(bottom, docks.timeline)
        window.addDockWidget(right, docks.properties)
        window.resizeDocks(
            [docks.viewport, docks.node_graph],
            [420, 360],
            Qt.Orientation.Vertical,
        )
        window.resizeDocks([docks.timeline], [108], Qt.Orientation.Vertical)
        window.resizeDocks([docks.properties], [260], Qt.Orientation.Horizontal)
        _set_timeline_limits(docks.timeline, minimum=96, maximum=132)
        _set_properties_limits(docks.properties, minimum=240, maximum=360)

    elif mode == LayoutMode.EDITING:
        window.addDockWidget(left, docks.node_graph)
        window.addDockWidget(left, docks.viewport)
        window.splitDockWidget(docks.node_graph, docks.viewport, Qt.Orientation.Vertical)
        window.addDockWidget(bottom, docks.timeline)
        window.addDockWidget(right, docks.properties)
        window.resizeDocks(
            [docks.node_graph, docks.viewport],
            [560, 220],
            Qt.Orientation.Vertical,
        )
        window.resizeDocks([docks.timeline], [100], Qt.Orientation.Vertical)
        window.resizeDocks([docks.properties], [280], Qt.Orientation.Horizontal)
        _set_timeline_limits(docks.timeline, minimum=90, maximum=120)
        _set_properties_limits(docks.properties, minimum=250, maximum=380)

    elif mode == LayoutMode.PREVIEW:
        window.addDockWidget(left, docks.viewport)
        window.addDockWidget(left, docks.node_graph)
        window.splitDockWidget(docks.viewport, docks.node_graph, Qt.Orientation.Vertical)
        window.addDockWidget(bottom, docks.timeline)
        window.addDockWidget(right, docks.properties)
        window.resizeDocks(
            [docks.viewport, docks.node_graph],
            [620, 180],
            Qt.Orientation.Vertical,
        )
        window.resizeDocks([docks.timeline], [96], Qt.Orientation.Vertical)
        window.resizeDocks([docks.properties], [240], Qt.Orientation.Horizontal)
        _set_timeline_limits(docks.timeline, minimum=90, maximum=120)
        _set_properties_limits(docks.properties, minimum=220, maximum=320)

    elif mode == LayoutMode.COMPACT:
        window.addDockWidget(left, docks.viewport)
        window.addDockWidget(left, docks.node_graph)
        window.splitDockWidget(docks.viewport, docks.node_graph, Qt.Orientation.Vertical)
        window.addDockWidget(bottom, docks.timeline)
        window.addDockWidget(right, docks.properties)
        window.resizeDocks(
            [docks.viewport, docks.node_graph],
            [340, 340],
            Qt.Orientation.Vertical,
        )
        window.resizeDocks([docks.timeline], [92], Qt.Orientation.Vertical)
        window.resizeDocks([docks.properties], [220], Qt.Orientation.Horizontal)
        _set_timeline_limits(docks.timeline, minimum=88, maximum=110)
        _set_properties_limits(docks.properties, minimum=200, maximum=280)


def reset_layout(window: QMainWindow, docks: EditorDocks) -> None:
    """Restore the default workspace layout."""
    apply_layout(window, docks, LayoutMode.DEFAULT)


def _set_timeline_limits(dock: QDockWidget, *, minimum: int, maximum: int) -> None:
    dock.setMinimumHeight(minimum)
    dock.setMaximumHeight(maximum)


def _set_properties_limits(dock: QDockWidget, *, minimum: int, maximum: int) -> None:
    dock.setMinimumWidth(minimum)
    dock.setMaximumWidth(maximum)
