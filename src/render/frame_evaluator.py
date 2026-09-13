"""Background frame evaluation with generation-guarded latest-wins delivery.

The worker exists to answer one question well: *which frame should the
viewport be showing right now?* Everything else is secondary.

Design goals
------------
* **Latest request always wins.** Requests carry a monotonic id; a result
  whose id is no longer current is never presented while paused/scrubbing.
* **Stale frames are worthless.** Results carry the project *generation*
  they were produced for. Switching projects, seeking, or scrubbing all
  bump the generation, so a slow job from the old state can never paint
  over the new one.
* **Adaptive dropping.** While playing, if measured frame cost exceeds the
  playback budget the worker stops emitting late frames and races ahead to
  the frame the clock actually wants. Export never uses this path.
* **Prefetch must earn its keep.** Prefetched frames that are later
  requested count as hits; frames discarded by a seek/scrub count as
  wasted. The ratio is exposed for the overlay and benchmarks.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import numpy as np
from config.constants import DEFAULT_MAX_PREFETCH_FRAMES
from core.audio import FrameWithAudio
from core.perf.frame_drop import FrameDropMode, FrameDropPolicy
from core.perf.profiler import profiler
from core.playback.clock import ClockSource, MediaClock
from core.playback.deadline import DeadlineQueue, FrameDeadline
from core.playback.governor import CostEstimator, QualityGovernor
from core.playback.trace import get_frame_trace
from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from core.project import Project

#: Fraction of the frame budget a frame may overrun by and still be shown.
#: Beyond this it is cheaper (and sharper) to race to the current frame.
_LATE_GRACE_FRACTION: float = 0.5


class FrameEvaluationWorker(QThread):
    """
    Background frame evaluator built around frame *deadlines*.

    The worker answers one question: which frame belongs on screen right now?
    Everything else follows from that.

    Architecture
    ------------
    ``MediaClock``
        Owns the timeline position. Deadlines are derived from it, never
        from how long rendering took, so a slow frame cannot push later
        deadlines further away — playback skips instead of slowing down.
    ``DeadlineQueue``
        Shallow, deadline-ordered request window. Playback keeps an
        earliest-deadline-first window so decode and graph evaluation can
        overlap; scrubbing collapses it to "newest request only".
    ``QualityGovernor``
        Turns measured deadline misses into one preview-scale decision with
        hysteresis, so quality adapts *before* the user notices a stall.
    ``FrameTrace``
        Per-frame stage timings, used by the overlay and the trace dump.

    Design goals:
    - Latest request always wins.
    - Stale work is abandoned, not finished.
    - Avoid unnecessary locking in the hot path.
    - Avoid unnecessary ndarray copies.
    - Prefetch sequentially while the UI is idle.
    - Never allow stale prefetch work to starve a newer request.
    """

    #: ``(node_id, frame_num, frame_or_none)``
    frame_ready = pyqtSignal(str, int, object)
    #: ``(node_id, frame_num)`` — emitted when work was discarded as stale.
    frame_discarded = pyqtSignal(str, int)
    #: ``(scale_percent,)`` — the governor's suggestion for preview scale.
    quality_suggested = pyqtSignal(int)

    def __init__(self, project: Project) -> None:
        super().__init__()

        self._project = project

        # Guards ``_pending``, ``_generation`` and the request id counter.
        # Held only for a few attribute writes on every request.
        self._request_lock = threading.Lock()

        self._pending: tuple[str, int, int, int] | None = None
        self._request_id = 0
        self._generation = 0

        # Deadline-oriented playback state.
        self._clock = MediaClock(
            fps=float(getattr(project, "fps", 30.0) or 30.0))
        self._queue = DeadlineQueue(capacity=DEFAULT_MAX_PREFETCH_FRAMES + 1)
        self._cost = CostEstimator(enabled=False)
        self._governor = QualityGovernor()
        self._last_suggested_scale = self._governor.scale_percent
        self._frames_behind: int = 2

        # Prefetch accounting: hits are frames the user later asked for,
        # wasted are frames discarded by a seek/scrub before use.
        self._prefetched: set[int] = set()
        self._prefetch_hits = 0
        self._prefetch_wasted = 0
        self._prefetch_enabled = True
        self._prefetch_direction = 1
        self._adaptive_prefetch = True
        self._scrubbing = False

        # These are only written by the controlling/UI thread and read by
        # the worker. CPython's simple bool/int reads are atomic enough here.
        self._running = True
        self._playing = False
        self._max_prefetch = DEFAULT_MAX_PREFETCH_FRAMES

        self._drop_policy = FrameDropPolicy(FrameDropMode.ADAPTIVE, 30.0)
        self._stale_discarded = 0
        self._frames_presented = 0
        self._drop_events = 0
        self._late_discarded = 0
        self._dropped_pending = 0

        # Written by the worker, read by the UI thread for adaptive quality.
        self.last_render_seconds = 0.0
        self.last_evaluated_frame = -1

        self._wake = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_max_prefetch(self, frame_count: int) -> None:
        """Set the maximum number of frames prefetched ahead.

        The deadline queue's capacity follows, so "prefetch 0" really does
        mean a pipeline one frame deep rather than a queue that quietly
        keeps filling.
        """
        self._max_prefetch = max(0, int(frame_count))
        self._queue.set_capacity(max(1, self._max_prefetch + 1))

    def set_prefetch_enabled(self, enabled: bool) -> None:
        """Enable or disable speculative prefetch entirely."""
        self._prefetch_enabled = bool(enabled)
        if not enabled:
            self.clear_prefetch_tracking()

    def set_adaptive_prefetch(self, enabled: bool) -> None:
        """Allow prefetch to be suppressed during scrubs/random access."""
        self._adaptive_prefetch = bool(enabled)

    def set_scrubbing(self, scrubbing: bool) -> None:
        """Tell the worker the user is dragging the timeline.

        While scrubbing, prefetch is pointless: the next request invalidates
        it almost immediately. Suppressing it keeps decode capacity on the
        frame under the playhead.
        """
        was_scrubbing = self._scrubbing
        self._scrubbing = bool(scrubbing)
        if scrubbing and not was_scrubbing:
            self.clear_prefetch_tracking(wasted=True)
        elif not scrubbing:
            self._wake.set()

    def set_playback_direction(self, direction: int) -> None:
        """Set the prefetch direction (``1`` forward, ``-1`` reverse)."""
        self._prefetch_direction = -1 if int(direction) < 0 else 1

    def set_drop_mode(self, mode: FrameDropMode | str) -> None:
        """Apply the configured frame-dropping mode."""
        if isinstance(mode, str):
            mode = FrameDropMode.from_name(mode)
        self._drop_policy.set_mode(mode)

    def set_target_fps(self, fps: float) -> None:
        """Update the playback budget used by the dropping policy."""
        self._drop_policy.set_target_fps(fps)

    def set_quality_range(self, minimum: int, maximum: int) -> None:
        """Constrain the preview scales the governor may choose between."""
        self._governor.set_range(minimum, maximum)
        self._last_suggested_scale = self._governor.scale_percent

    def set_adaptive_quality(self, enabled: bool) -> None:
        """Enable or disable governor-driven preview scaling."""
        self._governor.set_enabled(enabled)
        if not enabled:
            self._governor.reset()
            self._last_suggested_scale = self._governor.scale_percent

    def set_frames_behind(self, count: int) -> None:
        """Frames retained behind the playhead for step-back access."""
        self._frames_behind = max(0, int(count))

    def request_frame(self, node_id: str, frame_num: int) -> None:
        """Request a frame.

        The request is stamped with the time by which it stops being useful:
        during playback that is the media clock's deadline for the frame;
        while paused or scrubbing it is "now", because a delayed answer to a
        position the user has already left is worth nothing.

        Scrub/seek requests collapse the queue: when the playhead jumps, the
        newest position is the only one that matters, so pending work is
        dropped rather than rendered late.
        """
        now = time.monotonic()
        playing = self._playing
        scrubbing = self._scrubbing

        with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
            generation = self._generation

        if playing and not scrubbing:
            due_at = self._clock.due_time(frame_num)
        else:
            due_at = now

        queue_changed = False
        if not playing or scrubbing:
            # Interactive: only the newest position is meaningful.
            self._dropped_pending += self._queue.clear()

        self._queue.request(
            FrameDeadline(
                frame=int(frame_num),
                due_at=due_at,
                requested_at=now,
                request_id=request_id,
                generation=generation,
                predicted_cost_ms=self._cost.graph_cost_ms,
            ),
            collapse=False,
        )

        # Keep the single-slot fast path in sync for callers that read it.
        with self._request_lock:
            self._pending = (node_id, int(frame_num), request_id, generation)

        self._note_prefetch_use(int(frame_num))
        self._wake.set()

    def invalidate(self) -> None:
        """Discard pending work after a seek, scrub, or project change.

        Bumping the generation makes every in-flight job stale, so its
        result is dropped without waiting for it to finish, and the queue is
        emptied so no obsolete frame is started afterwards.
        """
        with self._request_lock:
            self._generation += 1
            self._pending = None

        self._dropped_pending += self._queue.clear()
        self.clear_prefetch_tracking(wasted=True)
        now = time.monotonic()
        try:
            self._clock.seek(int(self._project.current_frame), now)
        except Exception:  # noqa: BLE001 - project may be mid-teardown
            pass
        self._wake.set()

    def set_playing(self, playing: bool) -> None:
        """Start or stop the media clock and enable playback prefetch.

        Starting the clock anchors it at the current playhead, which is what
        makes *playback start* cheap: frames already evaluated while paused
        satisfy the first deadlines without any additional work.
        """
        self._playing = bool(playing)

        if playing:
            fps = float(self._project.fps)
            self._clock.set_fps(fps)
            self._drop_policy.set_target_fps(fps)
            self._governor.reset(time.monotonic())
            now = time.monotonic()
            try:
                self._clock.start(int(self._project.current_frame), now)
            except Exception:  # noqa: BLE001
                self._clock.start(0, now)
            # A new playback session is a fresh measurement.
            self._governor.reset(now)
            self._wake.set()
        else:
            self._clock.stop()
            self.clear_prefetch_tracking()

    def set_clock_source(self, source: ClockSource) -> None:
        """Select wall-clock or audio-mastered timing."""
        self._clock.set_source(source)

    def resync_clock_to_audio(self, presented_seconds: float) -> None:
        """Align the deadline clock with audio progress."""
        self._clock.resync_to_audio(presented_seconds)

    def set_project(self, project: Project) -> None:
        """Switch the worker to a new project."""
        with self._request_lock:
            self._project = project
            self._generation += 1
            self._pending = None

        self._queue.clear()
        self._clock = MediaClock(
            fps=float(getattr(project, "fps", 30.0) or 30.0))
        self._governor.reset()
        self._cost.reset()
        self.clear_prefetch_tracking(wasted=True)
        self._drop_policy.reset()
        self._wake.set()

    def stop(self) -> None:
        """Stop the worker and wait for the active evaluation."""
        self._running = False
        self.requestInterruption()
        self._wake.set()

        if not self.wait(2000):
            self.terminate()
            self.wait(500)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main worker loop.

        Event-driven: no polling timer, so an idle editor costs nothing.

        Each iteration takes the most urgent live request from the deadline
        queue, evaluates it, and then decides whether the *result* is still
        worth presenting. Three things can invalidate it:

        * a newer request superseded it (the user moved on);
        * its deadline has already passed by more than the grace fraction of
          a frame budget (showing it now would only add latency);
        * the project generation changed (a seek, scrub, or project switch).

        In every case the work is abandoned rather than completed late,
        which is the entire point of a deadline-oriented engine.
        """
        trace = get_frame_trace()

        while self._running and not self.isInterruptionRequested():
            now = time.monotonic()

            # Deadlines only apply while the timeline is moving. A paused or
            # step-frame request never expires: the user is still waiting
            # for exactly that frame, and dropping it would leave the
            # viewport stale for no benefit.
            if self._playing or self._scrubbing:
                grace_ms = self._clock.frame_budget_ms * _LATE_GRACE_FRACTION
            else:
                grace_ms = float("inf")

            dropped = self._queue.discard_expired(now, grace_ms)
            if dropped:
                self._late_discarded += dropped
                trace.note_dropped(dropped)

            deadline = self._queue.poll(now, grace_ms)

            if deadline is None:
                self._wake.wait()
                self._wake.clear()
                continue

            if deadline.generation != self._generation:
                self._stale_discarded += 1
                continue

            node_id = self._active_node_id()
            frame_num = deadline.frame

            record = trace.open_record(
                frame_num,
                deadline.requested_at,
                deadline.due_at,
                generation=deadline.generation,
                scale_percent=self._governor.scale_percent,
            )

            started = time.perf_counter()
            with profiler.scope("graph"):
                frame = self._evaluate(node_id, frame_num)
            elapsed = time.perf_counter() - started

            self.last_render_seconds = elapsed
            self.last_evaluated_frame = frame_num

            self._record_stages(record, elapsed)
            self._cost.observe_graph(elapsed * 1000.0)

            decision = self._drop_policy.decide(
                latency_frames=self._latency_frames(frame_num)
            )
            self._drop_policy.observe(elapsed)

            if not self._running:
                return

            present_at = time.monotonic()
            late_ms = deadline.lateness_ms(present_at)
            superseded = (
                deadline.generation != self._generation
                or deadline.request_id != self._current_request_id()
            )

            if late_ms > grace_ms and (self._playing or self._scrubbing):
                # Too late to be useful: paying for it now would only push
                # the *next* frame further behind.
                self._late_discarded += 1
                trace.note_dropped(1)
                if record is not None:
                    record.tags.append("late")
                continue

            if superseded:
                self._stale_discarded += 1
                if self._playing:
                    if decision.drop:
                        # Skip ahead: loop immediately and pick up the newest
                        # request instead of paying for a frame nobody wants.
                        self._drop_events += 1
                        trace.note_dropped(1)
                        if record is not None:
                            record.tags.append("superseded")
                        continue
                else:
                    # Paused/scrubbing results must match the playhead exactly.
                    if record is not None:
                        record.tags.append("superseded")
                    self.frame_discarded.emit(node_id, frame_num)
                    continue

            self._frames_presented += 1
            trace.close_record(record, present_at)
            self.frame_ready.emit(node_id, frame_num, frame)

            self._update_governor(elapsed, now)

            if self._playing and self._should_prefetch():
                self._prefetch(node_id, frame_num)

    # ------------------------------------------------------------------
    # Instrumentation
    # ------------------------------------------------------------------

    def _active_node_id(self) -> str:
        """Return the node the current requests target."""
        with self._request_lock:
            pending = self._pending
        if pending is not None:
            return pending[0]
        try:
            return str(self._project.active_viewer or "")
        except Exception:  # noqa: BLE001
            return ""

    def _record_stages(self, record: object, elapsed: float) -> None:
        """Split the frame's cost into decode and graph using the profiler.

        The decode and graph scopes already exist in the hot path, so the
        trace reads their most recent samples instead of adding a second
        timing call around the same work.
        """
        if record is None:
            return
        try:
            snapshots = profiler.snapshots()
        except Exception:  # noqa: BLE001
            return

        decode = snapshots.get("decode")
        if decode is not None and decode.count:
            record.decode_ms = decode.last_ms
            record.graph_ms = max(0.0, elapsed * 1000.0 - decode.last_ms)
        else:
            record.graph_ms = elapsed * 1000.0

        if self.project_is_proxied():
            record.tags.append("proxy")

    def project_is_proxied(self) -> bool:
        """Whether the active project is decoding from an editing proxy."""
        try:
            for node in self._project.nodes.values():
                decoder = getattr(node, "_decoder", None)
                if decoder is not None and getattr(decoder, "is_proxy", False):
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _update_governor(self, elapsed: float, now: float) -> None:
        """Feed the frame's cost to the governor and publish scale changes."""
        if not self._governor.enabled:
            return
        budget_ms = self._clock.frame_budget_ms
        self._governor.observe(elapsed * 1000.0, budget_ms, now)

        decision = self._governor.decide(now)
        if decision.changed and decision.scale_percent != self._last_suggested_scale:
            self._last_suggested_scale = decision.scale_percent
            self.quality_suggested.emit(decision.scale_percent)

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def _take_pending(self) -> tuple[str, int, int, int] | None:
        """Return and clear the single-slot mirror of the newest request."""
        with self._request_lock:
            request = self._pending
            self._pending = None
            return request

    def _current_request_id(self) -> int:
        with self._request_lock:
            return self._request_id

    def _has_pending(self) -> bool:
        """
        Cheap "is there newer work waiting" check.

        Called frequently during prefetch, so it must stay tiny: a queued
        entry means someone is waiting and speculative work should stop
        immediately.
        """
        return self._queue.depth > 0

    def _latency_frames(self, frame_num: int) -> float:
        """Return how many frames behind the playhead ``frame_num`` already is."""
        try:
            clock = int(self._project.current_frame)
        except Exception:  # noqa: BLE001 - project may be mid-teardown
            return 0.0
        return float(max(0, clock - frame_num))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        node_id: str,
        frame_num: int,
    ) -> np.ndarray | FrameWithAudio | None:
        """
        Evaluate one frame.

        Avoid copying arrays unless they are actually non-contiguous.
        """
        try:
            result = self._project.evaluate_node(node_id, frame_num)

        except Exception as exc:  # noqa: BLE001
            self._project.log_exception(exc)
            return None

        if isinstance(result, FrameWithAudio):
            frame = result.frame

            if isinstance(frame, np.ndarray) and not frame.flags.c_contiguous:
                frame = np.ascontiguousarray(frame)

            return FrameWithAudio(
                frame=frame,
                audio=result.audio,
            )

        if isinstance(result, np.ndarray):
            if result.flags.c_contiguous:
                return result

            return np.ascontiguousarray(result)

        return None

    # ------------------------------------------------------------------
    # Prefetch
    # ------------------------------------------------------------------

    def _prefetch(self, node_id: str, frame_num: int) -> None:
        """
        Warm frames ahead of playback in the active direction.

        Prefetch is deliberately interruptible: the instant the UI asks
        for another frame, prefetching stops.
        """
        if not self._should_prefetch():
            return

        project = self._project

        # Read settings once rather than once per frame.
        settings = project.get_preview_settings()

        count = min(
            max(0, int(settings.prefetch_frames)),
            self._max_prefetch,
        )

        if count <= 0:
            return

        direction = self._prefetch_direction
        max_frame = project.max_frame

        first = max(0, min(frame_num + direction, max_frame))
        last = max(0, min(frame_num + direction * count, max_frame))

        lo, hi = (first, last) if first <= last else (last, first)

        for next_frame in range(lo, hi + 1, 1):
            # New UI request always wins.
            if self._project is not project or self._has_pending():
                return

            # Don't waste time after shutdown or a play-state change.
            if not self._should_prefetch():
                return

            self._evaluate(node_id, next_frame)
            self._prefetched.add(next_frame)

        self._trim_prefetch_tracking()

    def _should_prefetch(self) -> bool:
        """Whether prefetch is currently worth doing at all."""
        if not self._prefetch_enabled or self._max_prefetch <= 0:
            return False
        if self._adaptive_prefetch and self._scrubbing:
            return False
        if not self._playing or not self._running or self.isInterruptionRequested():
            return False
        return True

    def _trim_prefetch_tracking(self) -> None:
        """Bound the "recently prefetched" set, counting overflow as waste."""
        limit = max(4, self._max_prefetch * 3)
        excess = len(self._prefetched) - limit
        if excess <= 0:
            return
        self._prefetch_wasted += excess
        # Sets are unordered; keeping an arbitrary subset is fine because the
        # metric only needs a ballpark hit/waste ratio.
        self._prefetched = set(list(self._prefetched)[limit:])

    def _note_prefetch_use(self, frame_num: int) -> None:
        """Record that the user actually asked for a prefetched frame."""
        if frame_num in self._prefetched:
            self._prefetched.discard(frame_num)
            self._prefetch_hits += 1

    def clear_prefetch_tracking(self, wasted: bool = False) -> None:
        """Forget prefetched frames, optionally counting them as wasted."""
        if wasted and self._prefetched:
            self._prefetch_wasted += len(self._prefetched)
        self._prefetched.clear()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, float | int | str]:
        """Return worker counters for the overlay and benchmark harness."""
        total_prefetch = self._prefetch_hits + self._prefetch_wasted
        return {
            "presented": self._frames_presented,
            "stale_discarded": self._stale_discarded,
            "dropped": self._drop_events,
            "late_dropped": self._late_discarded,
            "pending": self._queue.depth,
            "pending_dropped": self._dropped_pending,
            "last_ms": round(self.last_render_seconds * 1000.0, 3),
            "smoothed_ms": round(self._drop_policy.smoothed_ms, 3),
            "drop_mode": self._drop_policy.mode.label,
            "frame_budget_ms": round(self._drop_policy.frame_budget_ms, 3),
            "prefetch_hits": self._prefetch_hits,
            "prefetch_wasted": self._prefetch_wasted,
            "prefetch_hit_ratio": round(
                (self._prefetch_hits / total_prefetch) if total_prefetch else 0.0,
                4,
            ),
            "scale_percent": self._governor.scale_percent,
            "governor": self._governor.stats()["downgrades"],
            "clock_source": self._clock.source.name,
            "queue_capacity": self._queue.capacity,
        }
