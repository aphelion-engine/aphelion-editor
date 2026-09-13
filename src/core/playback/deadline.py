"""Bounded, deadline-ordered frame request queue.

The evaluator used to hold exactly one pending request. That is the right
*correctness* rule (latest wins) but the wrong *throughput* rule: it can
never queue frame N+1 while frame N is being computed, so decode and graph
evaluation cannot overlap.

This queue keeps a deliberately **shallow** window ordered by deadline.
Depth is the point: a queue of fifty obsolete frames is not performance,
it is latency. Everything here is sized so that the work in flight is
never more than a few frames deep.

Two request policies exist because scrubbing and playback are genuinely
different workloads:

``collapse=True`` (scrub / seek)
    The newest request is the only one that matters. Everything already
    queued is discarded on arrival.

``collapse=False`` (playback)
    Requests are served earliest-deadline-first. Entries whose deadline has
    already passed are dropped on the way out rather than rendered late.
"""

from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass

__all__ = ["DeadlineQueue", "FrameDeadline"]


@dataclass(frozen=True, slots=True)
class FrameDeadline:
    """One frame request with the time by which it stops being useful."""

    frame: int
    #: Monotonic time this frame should be on screen.
    due_at: float
    #: Monotonic time the request was issued.
    requested_at: float
    request_id: int
    generation: int
    #: Predicted evaluation cost in milliseconds, from the cost estimator.
    predicted_cost_ms: float = 0.0
    #: Higher wins ties (see ``core.perf.scheduler.JobPriority``).
    priority: int = 0

    def slack_ms(self, now: float) -> float:
        """Milliseconds remaining before this frame is late."""
        return (self.due_at - now) * 1000.0

    def lateness_ms(self, now: float) -> float:
        """Milliseconds this frame is already late (negative when early)."""
        return (now - self.due_at) * 1000.0

    def is_expired(self, now: float, grace_ms: float = 0.0) -> bool:
        """Whether presenting this frame now would be visibly late.

        ``grace_ms`` is the allowance for "still better than nothing" —
        typically a fraction of the frame budget, so a frame that misses by
        a hair is still shown instead of leaving the viewport stale.
        """
        return (now - self.due_at) * 1000.0 > grace_ms

    def is_worth_starting(
        self,
        now: float,
        budget_ms: float,
        pipeline_ms: float | None = None,
    ) -> bool:
        """Whether starting this frame now can still make its deadline.

        Parameters:
            now: Current monotonic time.
            budget_ms: Frame budget at the active rate.
            pipeline_ms: Predicted present latency (convert + upload), used
                so a frame is not started if it would arrive late anyway.
        """
        cost = self.predicted_cost_ms
        if pipeline_ms is not None:
            cost += pipeline_ms
        if cost <= 0.0:
            cost = budget_ms
        return (self.due_at - now) * 1000.0 > cost * 0.5


class DeadlineQueue:
    """Shallow bounded queue of :class:`FrameDeadline` ordered by urgency.

    Parameters:
        capacity: Maximum simultaneous requests. Playback needs only enough
            to overlap decode with evaluation; four is generous.
    """

    __slots__ = ("_lock", "_heap", "_frames", "_capacity", "_counter", "_discarded")

    def __init__(self, capacity: int = 4) -> None:
        self._lock = threading.Lock()
        self._heap: list[tuple[float, int, FrameDeadline]] = []
        self._frames: set[int] = set()
        self._capacity = max(1, int(capacity))
        self._counter = itertools.count()
        self._discarded = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        """Maximum simultaneous requests."""
        return self._capacity

    def set_capacity(self, capacity: int) -> None:
        """Resize the window, trimming the least urgent entries."""
        with self._lock:
            self._capacity = max(1, int(capacity))
            self._trim_unlocked()

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def request(self, deadline: FrameDeadline, *, collapse: bool = False) -> int:
        """Queue ``deadline``; returns how many requests were discarded.

        Parameters:
            deadline: The request to enqueue.
            collapse: When True, discard everything already queued first.
                Used for scrubs and seeks, where only the newest position
                is meaningful.
        """
        discarded = 0
        with self._lock:
            if collapse:
                discarded += len(self._heap)
                self._heap.clear()
                self._frames.clear()
            elif deadline.frame in self._frames:
                # Already queued; the existing entry keeps its earlier
                # deadline. Re-requesting a frame is not new work.
                return 0

            heapq.heappush(
                self._heap,
                (deadline.due_at, next(self._counter), deadline),
            )
            self._frames.add(deadline.frame)
            discarded += self._trim_unlocked()

        self._discarded += discarded
        return discarded

    def _trim_unlocked(self) -> int:
        """Drop the least urgent entries until within capacity."""
        discarded = 0
        while len(self._heap) > self._capacity:
            # Largest due time = least urgent.
            worst = max(self._heap, key=lambda entry: entry[0])
            self._heap.remove(worst)
            self._frames.discard(worst[2].frame)
            heapq.heapify(self._heap)
            discarded += 1
        return discarded

    # ------------------------------------------------------------------
    # Consumption
    # ------------------------------------------------------------------

    def poll(self, now: float, grace_ms: float = 0.0) -> FrameDeadline | None:
        """Return the most urgent live request, discarding expired ones."""
        with self._lock:
            while self._heap:
                _due, _seq, deadline = heapq.heappop(self._heap)
                self._frames.discard(deadline.frame)
                if deadline.is_expired(now, grace_ms):
                    self._discarded += 1
                    continue
                return deadline
        return None

    def peek(self) -> FrameDeadline | None:
        """Return the most urgent queued request without removing it."""
        with self._lock:
            return self._heap[0][2] if self._heap else None

    def discard_expired(self, now: float, grace_ms: float = 0.0) -> int:
        """Drop every request that is already too late; returns the count."""
        removed = 0
        with self._lock:
            keep: list[tuple[float, int, FrameDeadline]] = []
            for entry in self._heap:
                if entry[2].is_expired(now, grace_ms):
                    self._frames.discard(entry[2].frame)
                    removed += 1
                else:
                    keep.append(entry)
            self._heap = keep
            heapq.heapify(self._heap)
        self._discarded += removed
        return removed

    def discard_before(self, frame: int) -> int:
        """Drop every request at or below ``frame``; returns the count.

        Used when the playhead jumps forward: anything behind the new
        position can never be presented.
        """
        removed = 0
        with self._lock:
            keep: list[tuple[float, int, FrameDeadline]] = []
            for entry in self._heap:
                if entry[2].frame <= frame:
                    self._frames.discard(entry[2].frame)
                    removed += 1
                else:
                    keep.append(entry)
            self._heap = keep
            heapq.heapify(self._heap)
        self._discarded += removed
        return removed

    def clear(self) -> int:
        """Empty the queue; returns how many requests were dropped."""
        with self._lock:
            removed = len(self._heap)
            self._heap.clear()
            self._frames.clear()
        self._discarded += removed
        return removed

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Number of queued requests."""
        with self._lock:
            return len(self._heap)

    def __len__(self) -> int:
        return self.depth

    def frames(self) -> tuple[int, ...]:
        """Return the queued frame numbers, most urgent first."""
        with self._lock:
            return tuple(
                entry[2].frame for entry in sorted(self._heap, key=lambda e: e[0])
            )

    def stats(self) -> dict[str, int]:
        """Return counters for the overlay and benchmarks."""
        with self._lock:
            return {
                "depth": len(self._heap),
                "capacity": self._capacity,
                "discarded": self._discarded,
            }
