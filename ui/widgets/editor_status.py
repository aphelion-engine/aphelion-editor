"""Permanent status-bar widgets for project, playhead, and cache metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel

from config.theme import STATUS_BAR_STYLE
from core.events import ObserverEvent
from timeline.controller import PlaybackController

if TYPE_CHECKING:
    from ui.windows.editor import Editor


class EditorStatusBar:
    """Owns status-bar labels and keeps them synced with project state."""

    def __init__(self, editor: Editor) -> None:
        self._editor = editor
        self._controller = PlaybackController(editor.project.max_frame)
        self._project_label = QLabel()
        self._project_label.setObjectName("StatusProjectInfo")
        self._playhead_label = QLabel()
        self._playhead_label.setObjectName("StatusPlayhead")
        self._cache_label = QLabel()
        self._cache_label.setObjectName("StatusCacheInfo")
        self._refresh_timer = QTimer(editor)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_cache)
        self._attach()
        self.refresh_all()

    def attach_to_project(self) -> None:
        """Retarget labels after the active document is replaced."""
        self._editor.project.unsubscribe(self._on_project_event)
        self._editor.project.subscribe(self._on_project_event)
        self._controller.set_max_frame(self._editor.project.max_frame)
        self.refresh_all()

    def refresh_all(self) -> None:
        """Update every status label from the current project."""
        project = self._editor.project
        settings = project.project_settings()
        node_count = len(project.nodes)
        self._project_label.setText(
            f"{settings.summary()}  ·  {node_count} node{'s' if node_count != 1 else ''}"
        )
        self._sync_playhead(project.current_frame, project.fps)
        self._refresh_cache()

    def _attach(self) -> None:
        status = self._editor.statusBar()
        assert status is not None
        status.setStyleSheet(STATUS_BAR_STYLE)
        status.addWidget(self._project_label)
        status.addPermanentWidget(self._playhead_label)
        status.addPermanentWidget(self._cache_label)
        self._editor.project.subscribe(self._on_project_event)
        self._refresh_timer.start()

    def _on_project_event(self, event: ObserverEvent, data: object) -> None:
        if event == ObserverEvent.FrameChanged and isinstance(data, int):
            self._sync_playhead(data, self._editor.project.fps)
            return
        if event in {
            ObserverEvent.ProjectModified,
            ObserverEvent.NodeAdded,
            ObserverEvent.NodeRemoved,
        }:
            self.refresh_all()

    def _sync_playhead(self, frame_num: int, fps: float) -> None:
        timecode = self._controller.format_timecode(frame_num, fps)
        self._playhead_label.setText(f"{timecode}  ·  Frame {frame_num}")

    def _refresh_cache(self) -> None:
        used_mb, max_mb, entries = self._editor.project.cache_stats()
        self._cache_label.setText(
            f"Cache {used_mb:.0f}/{max_mb:.0f} MB  ·  {entries} frames"
        )

    def shutdown(self) -> None:
        """Stop timers and unsubscribe from project events."""
        self._refresh_timer.stop()
        self._editor.project.unsubscribe(self._on_project_event)
