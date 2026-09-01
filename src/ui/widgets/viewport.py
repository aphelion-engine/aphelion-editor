"""Video preview viewport — aspect-aware display, async evaluation only."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QCloseEvent, QImage, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.audio import AudioData, FrameWithAudio
from core.events import ObserverEvent
from core.nodes.base import FRAME_DTYPE
from core.preferences.models import PerformanceSettings
from core.project import Project

from effects.frame_ops import to_display_u8
from render.audio_playback import get_audio_engine
from render.frame_evaluator import FrameEvaluationWorker
from render.preview import ViewportFitMode
from ui.widgets.roto_overlay import RotoOverlayWidget
from ui.widgets.tracker_overlay import TrackerOverlayWidget

if TYPE_CHECKING:
    from core.history import HistoryStack

# Exponential moving-average smoothing for the displayed FPS readout.
# Lower values react faster to changes; higher values reduce jitter.
_FPS_SMOOTHING: float = 0.85


def _qt_image_buffer(frame: np.ndarray) -> bytes:
    """Expose an ndarray buffer to Qt without allocating a second copy."""
    # PyQt accepts the Python buffer protocol, but its stub declares only bytes.
    return cast(bytes, frame.data)


class ViewportWidget(QWidget):
    """Shows the active Viewer output without blocking the UI thread."""

    def __init__(self, project: Project, history: "HistoryStack | None" = None) -> None:
        super().__init__()
        self.project = project
        self._history = history
        self._pending_request: tuple[str, int] | None = None
        self._image_buffer: np.ndarray | None = None
        self._playback_active: bool = False
        self._performance: PerformanceSettings = PerformanceSettings()
        self._displayed_fps: float = 0.0
        self._last_display_time: float | None = None
        self._audio_engine = get_audio_engine()
        self._queued_audio_until_frame: int | None = None
        self._audio_prefetch_frames: int = 4

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setObjectName("ViewportLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(200, 100)
        layout.addWidget(self.label)
        self.setLayout(layout)
        self._apply_background()

        self._overlay = QLabel(self.label)
        self._overlay.setObjectName("ViewportPerfOverlay")
        self._overlay.setStyleSheet(
            "QLabel#ViewportPerfOverlay {"
            " color: #e0e0e0; background-color: rgba(0, 0, 0, 160);"
            " padding: 3px 6px; font-family: 'JetBrains Mono', Consolas, monospace;"
            " font-size: 11px; border-radius: 3px; }"
        )
        self._overlay.move(6, 6)
        self._overlay.hide()

        self._roto_overlay = RotoOverlayWidget(
            project, self._history, self.displayed_image_rect, self.label
        )
        self._roto_overlay.setGeometry(self.label.rect())
        self._roto_overlay.raise_()

        self._tracker_overlay = TrackerOverlayWidget(
            project, self._history, self.displayed_image_rect, self.label
        )
        self._tracker_overlay.setGeometry(self.label.rect())
        self._tracker_overlay.raise_()

        self._worker = FrameEvaluationWorker(project)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.start()

        self.project.subscribe(self.on_project_changed)
        self.request_update()

    def apply_performance_settings(self, performance: PerformanceSettings) -> None:
        """Apply Performance preferences: prefetch cap, proxy override, overlay.

        Parameters:
            performance: Resolved global performance preferences.

        Side effects:
            Updates the prefetch worker's cap, clears/re-applies the playback
            proxy override to match the current play state, and toggles the
            on-screen performance overlay.
        """
        self._performance = performance
        self._worker.set_max_prefetch(performance.max_prefetch_frames)
        self._sync_playback_proxy_override()
        self._overlay.setVisible(performance.show_performance_overlay)
        if performance.show_performance_overlay:
            self._refresh_overlay_text()

    def _sync_playback_proxy_override(self) -> None:
        """Enable the forced playback-proxy width only while actively playing."""
        if self._playback_active and self._performance.playback_proxy_override_enabled:
            self.project.set_playback_proxy_override(
                self._performance.playback_proxy_width
            )
        else:
            self.project.set_playback_proxy_override(None)

    def set_project(self, project: Project) -> None:
        """Retarget this viewport at a newly loaded project."""
        self.project.unsubscribe(self.on_project_changed)
        self.project = project
        self._worker.set_project(project)
        self._pending_request = None
        self._image_buffer = None
        self._last_display_time = None
        self._displayed_fps = 0.0
        self.project.subscribe(self.on_project_changed)
        self._apply_background()
        self._queued_audio_until_frame = None
        self.request_update()

    def on_project_changed(self, event: ObserverEvent, _data: Any) -> None:
        if event in {
            ObserverEvent.FrameChanged,
            ObserverEvent.NodeModified,
            ObserverEvent.ConnectionCreated,
            ObserverEvent.ConnectionRemoved,
            ObserverEvent.NodeAdded,
            ObserverEvent.NodeRemoved,
            ObserverEvent.ActiveViewerChanged,
            ObserverEvent.ProjectModified,
        }:
            if event in {
                ObserverEvent.NodeModified,
                ObserverEvent.ActiveViewerChanged,
                ObserverEvent.ProjectModified,
            }:
                self._apply_background()
            self.request_update()
            self._roto_overlay.update()
            self._tracker_overlay.update()

    def _apply_background(self) -> None:
        """Match letterbox color to the active Viewer background property."""
        hex_color = self.project.get_preview_settings().background_hex
        self.label.setStyleSheet(
            f"QLabel#ViewportLabel {{ background-color: {hex_color}; color: #666666; }}"
        )

    def request_update(self) -> None:
        viewer_id = self.project.active_viewer
        frame_num = self.project.current_frame

        if not viewer_id:
            self._image_buffer = None
            self._apply_background()
            self.label.setText("No active Viewer")
            self.label.setPixmap(QPixmap())
            return

        self._pending_request = (viewer_id, frame_num)
        self._worker.request_frame(viewer_id, frame_num)

    def _on_frame_ready(self, node_id: str, frame_num: int, frame: object) -> None:
        """Display a completed eval, tolerating lag while playing.

        Exact match is required while scrubbing. During playback, slightly
        stale frames are still shown so a heavy effect cannot stall the
        viewport on dropped latest-wins results.
        """
        if not self._result_is_relevant(node_id, frame_num):
            return

        pending: tuple[str, int] | None = self._pending_request
        if pending == (node_id, frame_num):
            self._pending_request = None

        # Handle FrameWithAudio - extract frame and audio
        if isinstance(frame, FrameWithAudio):
            frame_data = frame.frame
            audio_data = frame.audio
            if self._playback_active and audio_data is not None and self._audio_engine.is_enabled():
                self._feed_smoother_preview_audio(frame_num, audio_data)
        elif isinstance(frame, np.ndarray):
            frame_data = frame
        else:
            frame_data = self._blank_frame()

        self.display_frame(frame_data)

    def _result_is_relevant(self, node_id: str, frame_num: int) -> bool:
        """Accept exact requests or safe stale playback results.

        Frame indices are not monotonic: scrubbing and looping legitimately
        move backward. Recency is therefore determined by the pending request,
        never by comparing against the last displayed frame number.
        """
        if node_id != self.project.active_viewer:
            return False
        current_frame: int = self.project.current_frame
        if frame_num > current_frame:
            return False
        request: tuple[str, int] = (node_id, frame_num)
        pending: tuple[str, int] | None = self._pending_request
        if request == pending:
            return True
        if pending is None:
            return frame_num == current_frame
        # "Drop frames during playback" trades a little accuracy for
        # fluidity: disabling it forces every displayed frame to be an
        # exact match for the requested playhead position.
        return self._playback_active and self._performance.drop_frames_during_playback

    def _blank_frame(self) -> np.ndarray:
        settings = self.project.get_preview_settings()
        width = max(16, settings.max_width)
        height = max(16, round(width * 9 / 16))
        return np.zeros((height, width, 3), dtype=FRAME_DTYPE)

    def display_frame(self, frame: np.ndarray) -> None:
        """Present ``frame`` with Viewer fit mode; never stretch by default.

        Pipeline frames arrive as float32 in the ``[0, 1]`` contract and are
        quantized to uint8 here — the last step before handing pixels to Qt.
        """
        if frame.dtype != np.uint8:
            frame = to_display_u8(frame)

        h, w = frame.shape[:2]
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            frame_rgb = np.ascontiguousarray(frame)
            self._image_buffer = frame_rgb
            q_img = QImage(
                _qt_image_buffer(frame_rgb),
                w,
                h,
                3 * w,
                QImage.Format.Format_RGB888,
            )
        else:
            gray = np.ascontiguousarray(frame)
            self._image_buffer = gray
            q_img = QImage(
                _qt_image_buffer(gray),
                w,
                h,
                w,
                QImage.Format.Format_Grayscale8,
            )

        # Copy once into Qt-owned memory so the numpy buffer can be reused.
        pixmap = QPixmap.fromImage(q_img.copy())
        self.label.setText("")
        self.label.setPixmap(self._fit_pixmap(pixmap))
        self._roto_overlay.setGeometry(self.label.rect())
        self._roto_overlay.update()
        self._tracker_overlay.setGeometry(self.label.rect())
        self._tracker_overlay.update()
        self._track_display_fps()
        if self._performance.show_performance_overlay:
            self._refresh_overlay_text()

    def _track_display_fps(self) -> None:
        """Update a smoothed FPS estimate from wall-clock display intervals."""
        now = time.monotonic()
        previous = self._last_display_time
        self._last_display_time = now
        if previous is None:
            return
        elapsed = now - previous
        if elapsed <= 0.0:
            return
        instantaneous = 1.0 / elapsed
        if self._displayed_fps <= 0.0:
            self._displayed_fps = instantaneous
        else:
            self._displayed_fps = (
                _FPS_SMOOTHING * self._displayed_fps
                + (1.0 - _FPS_SMOOTHING) * instantaneous
            )

    def _refresh_overlay_text(self) -> None:
        """Render the performance HUD: display FPS, resolution, and cache use."""
        used_mb, max_mb, entries = self.project.cache_stats()
        width = height = 0
        if self._image_buffer is not None:
            height, width = self._image_buffer.shape[:2]
        proxy_note = (
            " [proxy]"
            if self._playback_active
            and self._performance.playback_proxy_override_enabled
            else ""
        )
        self._overlay.setText(
            f"{self._displayed_fps:5.1f} fps  ·  {width}x{height}{proxy_note}\n"
            f"cache {used_mb:.0f}/{max_mb:.0f} MB  ·  {entries} frames"
        )
        self._overlay.adjustSize()

    def displayed_image_rect(self) -> QRect:
        """Return the rect the current pixmap occupies inside the label.

        ``QLabel`` centers a pixmap smaller than itself (``AlignCenter``);
        this mirrors that centering so overlays can map normalized shape
        coordinates to on-screen pixels and back.
        """
        pixmap = self.label.pixmap()
        label_size = self.label.size()
        if pixmap is None or pixmap.isNull():
            return QRect(0, 0, label_size.width(), label_size.height())
        pixmap_width, pixmap_height = pixmap.width(), pixmap.height()
        x = max(0, (label_size.width() - pixmap_width) // 2)
        y = max(0, (label_size.height() - pixmap_height) // 2)
        return QRect(x, y, pixmap_width, pixmap_height)

    def set_edit_target(self, node_id: str | None) -> None:
        """Arm or disarm interactive editing for ``node_id``.

        Both overlays receive the same call and each independently ignores
        it unless ``node_id`` resolves to their own node type (Roto vs.
        Tracker/Planar Tracker), so exactly one becomes visible.
        """
        self._roto_overlay.set_edit_target(node_id)
        self._tracker_overlay.set_edit_target(node_id)

    def _fit_pixmap(self, pixmap: QPixmap) -> QPixmap:
        target = self.label.size()
        if target.width() <= 1 or target.height() <= 1:
            return pixmap

        fit_mode = self.project.get_preview_settings().fit_mode
        # FastTransformation keeps playback fluid; proxy frames are already small.
        xform = Qt.TransformationMode.FastTransformation

        if fit_mode == ViewportFitMode.Stretch:
            return pixmap.scaled(
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                xform,
            )
        if fit_mode == ViewportFitMode.Fill:
            return pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                xform,
            )
        return pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            xform,
        )

    def _feed_smoother_preview_audio(self, frame_num: int, fallback_audio: AudioData) -> None:
        """Queue contiguous processed viewer audio ahead of the playhead.

        Uses the already-evaluated audio for the displayed frame, then fills a
        short forward window by reusing cached viewer evaluations when possible.
        This keeps preview audio routed through the graph while reducing gaps
        when the viewport drops visual frames during playback.
        """
        start_frame = frame_num
        if self._queued_audio_until_frame is not None:
            start_frame = max(start_frame, self._queued_audio_until_frame)
        end_frame = max(frame_num + 1, frame_num + self._audio_prefetch_frames)
        viewer_id = self.project.active_viewer
        if not viewer_id:
            return

        for queued_frame in range(start_frame, end_frame):
            audio_to_feed: AudioData | None = None
            if queued_frame == frame_num:
                audio_to_feed = fallback_audio
            else:
                result = self.project.evaluate_node(viewer_id, queued_frame)
                if isinstance(result, FrameWithAudio):
                    audio_to_feed = result.audio
            if audio_to_feed is None:
                continue
            self._audio_engine.feed_audio(audio_to_feed)
        self._queued_audio_until_frame = end_frame

    def _prime_audio_playback(self) -> None:
        """Reset audio queue state when playback begins."""
        self._queued_audio_until_frame = None

    def set_playback_active(self, active: bool) -> None:
        """Hint the worker to prefetch; timeline alone drives frame changes."""
        self._playback_active = bool(active)
        self._worker.set_playing(active)
        self._sync_playback_proxy_override()
        self._last_display_time = None
        self._displayed_fps = 0.0
        self._queued_audio_until_frame = None

        # Start/stop audio playback
        self._audio_engine.clear_buffer()
        if active and self._audio_engine.is_enabled():
            self._prime_audio_playback()
            self._audio_engine.start()
        else:
            self._audio_engine.stop()

    def shutdown(self) -> None:
        """Stop background evaluation before the editor window is torn down."""
        self._audio_engine.stop()
        self._worker.stop()

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        if self._image_buffer is not None:
            self.display_frame(self._image_buffer)
        else:
            self._roto_overlay.setGeometry(self.label.rect())
            self._tracker_overlay.setGeometry(self.label.rect())

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.shutdown()
        super().closeEvent(a0)
