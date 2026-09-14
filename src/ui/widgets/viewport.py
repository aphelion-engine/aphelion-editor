"""Video preview viewport — aspect-aware display, async evaluation only."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from config.constants import PERF_OVERLAY_REFRESH_MS
from core.audio import AudioData, FrameWithAudio
from core.events import ObserverEvent
from core.perf.profiler import profiler, set_profiling_enabled
from core.playback.clock import ClockSource
from core.preferences.models import PerformanceSettings
from core.project import Project
from effects.frame_ops import to_display_u8
from PyQt6.QtCore import QEvent, QRect, Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QImage, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
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


class _NullTrace:
    """Stand-in used when the frame-trace module is unavailable."""

    __slots__ = ()

    def set_enabled(self, _enabled: bool) -> None:
        """Accept and ignore the enable request."""

    def note_dropped(self, _count: int = 1) -> None:
        """Accept and ignore a drop notification."""


_NULL_TRACE = _NullTrace()


def _viewer_preview_width(project: Project) -> int:
    """Return the Viewer's own preview width, ignoring active overrides.

    Reading the already-overridden value back would ratchet the proxy width
    down on every re-application, so the Viewer property is read directly.
    """
    viewer_id = getattr(project, "active_viewer", None)
    nodes = getattr(project, "nodes", None)
    if viewer_id and nodes is not None:
        viewer = nodes.get(viewer_id)
        if viewer is not None:
            prop = viewer.get_property("preview_max_width")
            value = getattr(prop, "value", None)
            if value is not None:
                try:
                    width = int(value)
                except (TypeError, ValueError):
                    width = 0
                if width > 0:
                    return width
    return max(16, int(getattr(project, "width", 1920) or 1920))


class ViewportWidget(QWidget):
    """Shows the active Viewer output without blocking the UI thread."""

    def __init__(self, project: Project, history: "HistoryStack | None" = None) -> None:
        super().__init__()
        self.project = project
        self._history = history
        self._pending_request: tuple[str, int] | None = None
        self._image_buffer: np.ndarray | None = None
        self._adaptive_width: int | None = None
        self._last_adaptation = 0.0
        self._playback_active: bool = False
        self._performance: PerformanceSettings = PerformanceSettings()
        self._displayed_fps: float = 0.0
        self._last_display_time: float | None = None
        self._audio_engine = get_audio_engine()
        self._queued_audio_until_frame: int | None = None
        self._audio_prefetch_frames: int = 4

        # Scrub / paused-quality state.
        self._scrubbing: bool = False
        self._displayed_frame_ms: float = 0.0
        self._overlay_last_refresh: float = 0.0
        #: Cached ``native``/``python`` kernel-backend label for the HUD.
        self._frame_backend_cache: str | None = None

        # Audio-master clock: a low-rate timer samples how much audio the
        # device has actually consumed and corrects video timing to match.
        # 10 Hz is plenty when corrections are slew-limited rather than
        # applied as jumps.
        self._audio_clock_timer = QTimer(self)
        self._audio_clock_timer.setInterval(100)
        self._audio_clock_timer.timeout.connect(self._sync_audio_clock)

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
        # Keep controls in layout space, outside both the image and its HUD.
        tracker_toolbar = self._tracker_overlay._toolbar
        tracker_toolbar.setParent(self)
        layout.insertWidget(0, tracker_toolbar)
        tracker_toolbar.hide()
        self._tracker_overlay.setGeometry(self.label.rect())
        self._tracker_overlay.raise_()
        self.label.installEventFilter(self)

        self._worker = FrameEvaluationWorker(project)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.frame_discarded.connect(self._on_frame_discarded)
        self._worker.quality_suggested.connect(self._on_quality_suggested)
        self._worker.start()

        self.project.subscribe(self.on_project_changed)
        self.request_update()

    def _sync_audio_clock(self) -> None:
        """Correct the playback clock against the audio device's progress.

        Audio is the only clock the user actually hears, so video timing is
        slaved to it. ``presented_seconds`` counts from playback start, which
        is exactly the elapsed-timeline-seconds value the clock wants.
        """
        if not self._playback_active or self._scrubbing:
            return
        if not self._audio_engine.is_enabled():
            return
        presented = self._audio_engine.presented_seconds()
        if presented <= 0.0:
            return
        self._worker.resync_clock_to_audio(presented)

    def _on_quality_suggested(self, scale_percent: int) -> None:
        """Apply a preview-scale decision from the quality governor.

        The governor only emits when it has actually stepped, and it already
        applies hysteresis, so this never fires frame-to-frame. The scale is
        resolved against the Viewer's own width (not the currently
        overridden one) so repeated steps cannot ratchet the proxy down.
        """
        base_width = _viewer_preview_width(self.project)
        target = max(160, int(base_width * max(1, scale_percent) / 100))
        if target >= base_width:
            self._adaptive_width = None
        else:
            self._adaptive_width = target
        self._sync_playback_proxy_override()

    def apply_performance_settings(self, performance: PerformanceSettings) -> None:
        """Apply Performance preferences: prefetch, dropping, proxies, overlay.

        Parameters:
            performance: Resolved global performance preferences.

        Side effects:
            Updates the evaluation worker's prefetch/drop policy and
            governor range, clears and re-applies the playback proxy
            override, toggles the on-screen performance overlay, and enables
            profiling/tracing when diagnostics are requested.
        """
        self._adaptive_width = None
        self._performance = performance
        self._worker.set_max_prefetch(performance.max_prefetch_frames)
        self._worker.set_prefetch_enabled(performance.prefetch_enabled)
        self._worker.set_adaptive_prefetch(performance.adaptive_prefetch)
        self._worker.set_drop_mode(performance.effective_drop_mode)
        self._worker.set_frames_behind(performance.frames_behind)
        self._worker.set_realtime_priority(performance.realtime_priority)
        # Render-ahead is only meaningful when the playhead can sit still and
        # there is something to warm; it is bounded by the same "frames ahead"
        # budget the playback prefetch uses.
        self._worker.set_render_ahead(
            performance.prefetch_enabled and performance.frames_ahead > 0,
            performance.frames_ahead,
        )
        self._worker.set_target_fps(
            performance.target_preview_fps or self.project.fps
        )

        # The governor and the legacy fixed-step adapter are two answers to
        # the same question; only one may be active at a time.
        self._worker.set_adaptive_quality(performance.adaptive_preview_enabled)
        self._worker.set_quality_range(
            performance.min_preview_scale_percent,
            performance.max_preview_scale_percent,
        )

        set_profiling_enabled(
            performance.performance_diagnostics
            or performance.show_performance_overlay
        )
        self._trace().set_enabled(
            performance.performance_trace_enabled
            or performance.performance_diagnostics
            or performance.show_performance_overlay
        )
        self._sync_playback_proxy_override()
        self._overlay.setVisible(performance.show_performance_overlay)
        if performance.show_performance_overlay:
            self._refresh_overlay_text(force=True)

    @staticmethod
    def _trace():
        """Return the process-wide frame trace, or a no-op stub."""
        try:
            from core.playback.trace import get_frame_trace

            return get_frame_trace()
        except Exception:  # noqa: BLE001 - tracing is strictly optional
            return _NULL_TRACE

    # ------------------------------------------------------------------
    # Preview quality resolution
    # ------------------------------------------------------------------

    def _scrub_width(self, base_width: int) -> int:
        """Preview width to use while the playhead is being dragged."""
        percent = self._performance.scrub_quality_percent
        if not self._performance.auto_scrub_quality:
            percent = 100
        percent = max(
            percent,
            self._performance.min_preview_scale_percent,
        )
        return max(160, min(base_width, int(base_width * percent / 100)))

    def _sync_playback_proxy_override(self) -> None:
        """Enable a forced proxy width while playing or scrubbing."""
        width: int | None = None
        base_width = _viewer_preview_width(self.project)

        if self._scrubbing and self._performance.auto_scrub_quality:
            width = self._scrub_width(base_width)
        elif self._playback_active:
            if self._performance.playback_proxy_override_enabled:
                width = self._performance.playback_proxy_width
            if (
                self._performance.adaptive_preview_enabled
                and self._adaptive_width is not None
            ):
                width = (
                    min(width, self._adaptive_width)
                    if width
                    else self._adaptive_width
                )

        self.project.set_playback_proxy_override(width)

    def begin_scrub(self) -> None:
        """Enter fast scrub mode: drop resolution and cancel in-flight work."""
        if self._scrubbing:
            return
        self._scrubbing = True
        self._worker.set_scrubbing(True)
        self._worker.invalidate()
        self._sync_playback_proxy_override()
        if self._performance.show_performance_overlay:
            self._refresh_overlay_text(force=True)

    def end_scrub(self) -> None:
        """Leave scrub mode and re-render the playhead at full quality."""
        if not self._scrubbing:
            return
        self._scrubbing = False
        self._worker.set_scrubbing(False)
        self._sync_playback_proxy_override()
        self._render_high_quality_if_idle(after_scrub=True)
        if self._performance.show_performance_overlay:
            self._refresh_overlay_text(force=True)

    def _render_high_quality_if_idle(self, after_scrub: bool = False) -> None:
        """Re-render the current frame sharply once interaction stops.

        Parameters:
            after_scrub: Selects the ``High Quality After Scrub`` policy
                instead of ``High Quality When Paused``.
        """
        if self._playback_active or self._scrubbing:
            return
        enabled = (
            self._performance.high_quality_after_scrub
            if after_scrub
            else self._performance.high_quality_when_paused
        )
        if not enabled:
            return
        self.request_update()

    def _adapt_preview(self) -> None:
        """Reduce overloaded playback resolution, with hysteresis.

        Adaptation is deliberately slow in both directions: bouncing the
        proxy width every few frames is more distracting (and more
        expensive) than playing slightly below target for a moment.
        """
        if not self._playback_active or not self._performance.adaptive_preview_enabled:
            return
        now = time.monotonic()
        if now - self._last_adaptation < 2.0:
            return
        if self._worker.last_render_seconds <= 1.25 / max(1, self.project.fps):
            return
        base_width = self.project.get_preview_settings().max_width or self.project.width
        min_width = max(
            160,
            int(base_width * self._performance.min_preview_scale_percent / 100),
        )
        width = self._adaptive_width or base_width
        if width <= min_width:
            return
        self._adaptive_width = max(min_width, int(width * 0.75))
        self._last_adaptation = now
        self._sync_playback_proxy_override()

    def set_project(self, project: Project) -> None:
        """Retarget this viewport at a newly loaded project."""
        self.project.unsubscribe(self.on_project_changed)
        self.project = project
        self._adaptive_width = None
        self._scrubbing = False
        self._worker.set_scrubbing(False)
        self._sync_playback_proxy_override()
        # ``set_project`` bumps the worker generation, so any job still
        # running for the previous project can never paint into this one.
        self._worker.set_project(project)
        self._pending_request = None
        self._image_buffer = None
        self._last_display_time = None
        self._displayed_fps = 0.0
        self._overlay_last_refresh = 0.0
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
        self._adapt_preview()

    def _on_frame_discarded(self, _node_id: str, _frame_num: int) -> None:
        """A stale result was dropped; keep the HUD counters honest."""
        if self._performance.show_performance_overlay:
            self._refresh_overlay_text()

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
        # A scrub drag invalidates everything that is not the newest request:
        # showing an older frame while the playhead has moved on reads as lag.
        request: tuple[str, int] = (node_id, frame_num)
        pending: tuple[str, int] | None = self._pending_request
        if request == pending:
            return True
        if pending is None:
            return frame_num == current_frame
        if self._scrubbing:
            return False
        # "Drop frames during playback" trades a little accuracy for
        # fluidity: disabling it forces every displayed frame to be an
        # exact match for the requested playhead position.
        return self._playback_active and self._performance.drop_frames_during_playback

    def _frame_backend(self) -> str:
        """Return ``native`` or ``python`` for the HUD's kernel readout.

        Cached after the first call: the probe does an import attempt, and
        the overlay must not pay for that on every refresh.
        """
        if self._frame_backend_cache is None:
            try:
                from core.native import probe

                self._frame_backend_cache = probe().backend
            except Exception:  # noqa: BLE001
                self._frame_backend_cache = "python"
        return self._frame_backend_cache

    def _blank_frame(self) -> np.ndarray:
        """Return a display-ready black frame (dense representation)."""
        settings = self.project.get_preview_settings()
        width = max(16, settings.max_width)
        height = max(16, round(width * 9 / 16))
        return np.zeros((height, width, 3), dtype=np.uint8)

    def display_frame(self, frame: np.ndarray) -> None:
        """Present ``frame`` with Viewer fit mode; never stretch by default.

        Two representations are accepted and the cheaper one is taken by
        preference:

        * **uint8 RGB** — a frame that never needed float precision reaches
          here exactly as the decoder produced it. No quantization, no
          clamp pass, no float round trip. This is the bare-playback path.
        * **float32** — a frame that went through effects is clamped and
          quantized exactly once, here, at the display boundary.

        Ownership: the QImage is constructed *over* the numpy buffer, so a
        reference is retained in ``self._image_buffer`` for as long as the
        buffer may be read. The previous implementation additionally copied
        the QImage before handing it to ``QPixmap.fromImage`` — which itself
        deep-copies into Qt-owned memory — costing a second full-frame
        memcpy on every single presented frame.
        """
        if frame.dtype != np.uint8:
            with profiler.scope("display_convert"):
                frame = to_display_u8(frame)
        else:
            # Already display-ready; make sure scanlines are contiguous but
            # never copy a buffer that already is.
            if not frame.flags.c_contiguous:
                frame = np.ascontiguousarray(frame)

        h, w = frame.shape[:2]
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            self._image_buffer = frame
            q_img = QImage(
                _qt_image_buffer(frame),
                w,
                h,
                3 * w,
                QImage.Format.Format_RGB888,
            )
        else:
            self._image_buffer = frame
            q_img = QImage(
                _qt_image_buffer(frame),
                w,
                h,
                w,
                QImage.Format.Format_Grayscale8,
            )

        # QPixmap.fromImage performs its own deep copy into Qt-owned (and,
        # where available, GPU-resident) memory, so the source QImage does
        # not need a defensive .copy() first.
        with profiler.scope("qt_upload"):
            pixmap = QPixmap.fromImage(q_img)
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
        self._displayed_frame_ms = elapsed * 1000.0
        instantaneous = 1.0 / elapsed
        if self._displayed_fps <= 0.0:
            self._displayed_fps = instantaneous
        else:
            self._displayed_fps = (
                _FPS_SMOOTHING * self._displayed_fps
                + (1.0 - _FPS_SMOOTHING) * instantaneous
            )

    def _refresh_overlay_text(self, force: bool = False) -> None:
        """Render the performance HUD.

        Repainting diagnostic text on every presented frame is itself
        measurable work (layout + relayout of a ``QLabel``), so updates are
        throttled unless explicitly forced. The values shown are the real
        counters used by the benchmark harness — not estimates.
        """
        now = time.monotonic()
        if not force and (now - self._overlay_last_refresh) * 1000.0 < PERF_OVERLAY_REFRESH_MS:
            return
        self._overlay_last_refresh = now

        cache = self.project.cache_detailed_stats()
        worker = self._worker.stats()

        width = height = 0
        if self._image_buffer is not None:
            height, width = self._image_buffer.shape[:2]

        if self._scrubbing:
            mode = "scrub"
        elif self._playback_active:
            mode = "play"
        else:
            mode = "paused"

        target_fps = self._performance.target_preview_fps or self.project.fps
        budget_ms = 1000.0 / max(1.0, float(target_fps))

        # Per-stage timings come from the profiler's rolling samples. They
        # are process-wide "most recent" values rather than being attributed
        # to one specific frame, which is the honest reading for a live HUD.
        snapshots = profiler.snapshots()

        def stage_ms(name: str) -> float:
            snapshot = snapshots.get(name)
            return snapshot.last_ms if snapshot is not None and snapshot.count else 0.0

        decode_ms = stage_ms("decode")
        graph_ms = stage_ms("graph")
        convert_ms = stage_ms("display_convert")
        upload_ms = stage_ms("qt_upload")
        total_ms = decode_ms + graph_ms + convert_ms + upload_ms

        trace = self._trace()
        try:
            summary = trace.summary()
        except Exception:  # noqa: BLE001
            summary = {}

        lines = [
            f"{self._displayed_fps:5.1f} / {target_fps:.0f} fps   "
            f"budget {budget_ms:5.1f} ms",
            f"{width}x{height}  {mode}  scale {worker.get('scale_percent', 100)}%",
            f"decode {decode_ms:5.1f}  graph {graph_ms:5.1f}  "
            f"convert {convert_ms:5.1f}  upload {upload_ms:5.1f}  "
            f"= {total_ms:5.1f} ms",
            f"dropped {worker['dropped']}  late {worker['late_dropped']}  "
            f"stale {worker['stale_discarded']}  ahead {worker['pending']}",
            f"cache {cache['size_mb']:.0f}/{cache['max_mb']:.0f} MB  "
            f"hit {cache['hit_rate'] * 100:.0f}%   "
            f"raw8 {'yes' if self.project.render_plan().u8_source_ids else 'no'}  "
            f"kern {self._frame_backend()}",
            f"prefetch {worker['prefetch_hits']}/"
            f"{worker['prefetch_hits'] + worker['prefetch_wasted']} "
            f"({worker['prefetch_hit_ratio'] * 100:.0f}%)",
        ]

        if summary.get("frames"):
            lines.append(
                f"trace {summary['frames']}f  p95 {summary['p95_ms']:.1f} ms  "
                f"miss {summary['miss_rate'] * 100:.1f}%  "
                f"reused {summary['reused']}"
            )

        if self._performance.performance_diagnostics:
            hot = profiler.hot_spots(3)
            if hot:
                lines.append(
                    " · ".join(
                        f"{snapshot.name} {snapshot.p95_ms:.1f}ms" for snapshot in hot
                    )
                )

        self._overlay.setText("\n".join(lines))
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
                result = self.project.cached_preview_frame(viewer_id, queued_frame)
                if isinstance(result, FrameWithAudio):
                    audio_to_feed = result.audio
            if audio_to_feed is None:
                break
            self._audio_engine.feed_audio(audio_to_feed)
            self._queued_audio_until_frame = queued_frame + 1

    def _prime_audio_playback(self) -> None:
        """Reset audio queue state when playback begins."""
        self._queued_audio_until_frame = None

    def set_playback_active(self, active: bool) -> None:
        """Hint the worker to prefetch; timeline alone drives frame changes.

        Starting playback invalidates any in-flight paused/scrub evaluation
        so the first played frame is not queued behind a high-quality render
        that is about to be replaced. Stopping playback does the opposite:
        it drops the playback proxy and re-renders the current frame sharply
        once the fast preview has already been shown.
        """
        self._adaptive_width = None
        self._last_adaptation = time.monotonic()
        self._playback_active = bool(active)

        if active:
            self._worker.set_target_fps(
                self._performance.target_preview_fps or self.project.fps
            )
            self._worker.invalidate()
        else:
            self._worker.clear_prefetch_tracking()

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

            # Audio becomes the master clock as soon as the device is
            # actually consuming samples; until the first resync lands, the
            # clock free-runs on wall time so playback still starts
            # immediately rather than waiting for audio to spin up.
            self._worker.set_clock_source(ClockSource.AUDIO_MASTER)
            self._audio_clock_timer.start()
        else:
            self._audio_engine.stop()
            self._audio_clock_timer.stop()
            self._worker.set_clock_source(ClockSource.FREE_RUNNING)
            if not active:
                # Show the existing fast preview immediately, then asynchronously
                # replace it with a full-quality render.
                self._render_high_quality_if_idle()

        # Garbage collection is coordinated around the playback session only.
        # A full collection landing mid-playback is a multi-millisecond spike
        # that has nothing to do with media work, which makes it the single
        # hardest stutter to attribute from frame timings alone.
        try:
            from core.perf.gc_policy import get_gc_policy

            policy = get_gc_policy()
            if active:
                policy.begin_playback()
            else:
                policy.end_playback()
        except Exception:  # noqa: BLE001 - GC tuning is strictly advisory
            pass

        if self._performance.show_performance_overlay:
            self._refresh_overlay_text(force=True)

    def shutdown(self) -> None:
        """Stop background evaluation before the editor window is torn down."""
        self._audio_clock_timer.stop()
        self._audio_engine.stop()
        self._worker.stop()
        # Never leave the collector in a playback-scoped state: the editor
        # may outlive this viewport (project switch, dock re-creation).
        try:
            from core.perf.gc_policy import get_gc_policy

            get_gc_policy().end_playback()
        except Exception:  # noqa: BLE001
            pass

    def eventFilter(self, watched, event):
        if watched is self.label and event.type() == QEvent.Type.Resize:
            self._roto_overlay.setGeometry(self.label.rect())
            self._tracker_overlay.setGeometry(self.label.rect())
        return super().eventFilter(watched, event)

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
