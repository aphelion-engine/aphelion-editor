"""Central bounded priority worker pool.

Before this module, background work created its own short-lived
``ThreadPoolExecutor`` per call site. That made thread counts impossible
to reason about and meant a burst of low-value work (media probing,
cache warming) could compete on equal terms with interactive requests.

The scheduler gives every job a priority band, keeps a bounded number of
worker threads, and can pause low-priority work while playback is active
so decoding/graph evaluation keeps its headroom.

Priorities
----------
=============  =================================================
``REALTIME``   The frame the playhead needs *now*.
``INTERACTIVE``Scrub / latest-wins current-frame requests.
``NORMAL``     Prefetch and other speculative work.
``BACKGROUND``Media probing, thumbnails, cache warming.
``RENDER``     Export and tracking runs (long, must not be starved).
=============  =================================================

``RENDER`` jobs are intentionally the *lowest* priority in the heap but
are never dropped; they represent long sequential runs that should yield
to interactive work rather than be cancelled.
"""

from __future__ import annotations

import heapq
import itertools
import os
import threading
import time
from concurrent.futures import Future
from enum import IntEnum
from typing import Any, Callable

__all__ = [
    "JobPriority",
    "WorkerScheduler",
    "get_scheduler",
    "recommended_worker_count",
    "shutdown_scheduler",
]


class JobPriority(IntEnum):
    """Priority bands, lower value is served first."""

    REALTIME = 0
    INTERACTIVE = 10
    NORMAL = 20
    BACKGROUND = 30
    RENDER = 40


#: Priorities at or below this are paused while playback is active when
#: "Pause Background Jobs During Playback" is enabled.
BACKGROUND_THRESHOLD = JobPriority.BACKGROUND


#: Never spin up more than this many Python worker threads.
MAX_WORKER_THREADS: int = 16


def recommended_worker_count(logical_cpus: int | None = None) -> int:
    """Return a sensible default worker count for ``logical_cpus``.

    Deliberately *not* ``os.cpu_count()``: the UI thread, the decode
    thread, FFmpeg's own internal threads, OpenCV's internal threads, and
    the OS all need capacity. Oversubscribing shows up as worse frame
    pacing, not better throughput.
    """
    cpus = int(logical_cpus if logical_cpus is not None else (os.cpu_count() or 4))
    if cpus <= 2:
        return 1
    if cpus <= 4:
        return 2
    if cpus <= 8:
        return 3
    if cpus <= 16:
        return max(4, cpus // 3)
    return min(MAX_WORKER_THREADS, max(6, cpus // 4))


class _Job:
    """One queued unit of work."""

    __slots__ = ("priority", "sequence", "future", "name", "fn", "args", "kwargs", "cancelled")

    def __init__(
        self,
        priority: int,
        sequence: int,
        future: Future,
        name: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        self.priority = priority
        self.sequence = sequence
        self.future = future
        self.name = name
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.cancelled = False

    def sort_key(self) -> tuple[int, int]:
        return (self.priority, self.sequence)


class WorkerScheduler:
    """Bounded priority thread pool.

    Parameters:
        workers: Worker thread count. ``None`` selects
            :func:`recommended_worker_count`.
        name: Thread name prefix, useful in profilers/debuggers.

    Example:
        ::

            scheduler = get_scheduler()
            future = scheduler.submit(probe_media, path, priority=JobPriority.BACKGROUND)
            info = future.result(timeout=5.0)
    """

    def __init__(self, workers: int | None = None, name: str = "aphelion-worker") -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        # Guards ``_workers`` only. Kept separate from ``_condition`` because
        # a retiring worker mutates the list from inside the worker loop,
        # which already holds ``_condition`` — the two locks are always
        # acquired in the order condition -> workers, never the reverse.
        self._workers_lock = threading.Lock()
        self._queue: list[tuple[int, int, _Job]] = []
        self._counter = itertools.count()
        self._workers: list[threading.Thread] = []
        self._shutdown = False
        self._paused_background = False
        self._name = name
        self._completed = 0
        self._cancelled = 0
        self._submitted = 0
        self._worker_limit = max(1, min(MAX_WORKER_THREADS, int(workers))) if workers else recommended_worker_count()
        self._spawn_workers(self._worker_limit)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _spawn_workers(self, count: int) -> None:
        for index in range(count):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"{self._name}-{index}",
                daemon=True,
            )
            with self._workers_lock:
                self._workers.append(thread)
            thread.start()

    def _live_workers(self) -> list[threading.Thread]:
        """Return a snapshot of currently registered worker threads."""
        with self._workers_lock:
            return list(self._workers)

    @property
    def worker_count(self) -> int:
        """Number of registered worker threads."""
        with self._workers_lock:
            return len(self._workers)

    def set_worker_count(self, count: int) -> None:
        """Grow or shrink the pool's thread count.

        Shrinking is cooperative: surplus workers notice the reduced limit
        the next time they look for work and retire themselves. Running
        jobs always finish. This must never raise — it is called from a
        preferences-apply path on the UI thread.
        """
        limit = max(1, min(MAX_WORKER_THREADS, int(count)))
        grow = False
        with self._condition:
            if limit == self._worker_limit:
                return
            previous = self._worker_limit
            self._worker_limit = limit
            grow = limit > previous
            if grow:
                self._spawn_workers(limit - previous)
            else:
                # Wake every worker so the surplus ones can retire promptly.
                self._condition.notify_all()
        if not grow:
            self._await_shrink()

    def _await_shrink(self) -> None:
        """Give surplus workers a brief chance to exit; never force-remove.

        The previous implementation removed entries from ``_workers`` while
        the retiring worker also removed itself, which raised ``ValueError``
        and aborted the preferences-apply path. Retiring is now solely the
        worker's responsibility (see :meth:`_retire_self`).
        """
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if self.worker_count <= self._worker_limit:
                return
            for thread in self._live_workers():
                if thread.is_alive():
                    thread.join(timeout=0.02)
            self._reap_dead_workers()

    def _reap_dead_workers(self) -> None:
        """Drop finished threads from the registry."""
        with self._workers_lock:
            self._workers = [thread for thread in self._workers if thread.is_alive()]

    def shutdown(self, wait: bool = True, timeout: float = 2.0) -> None:
        """Stop accepting work and join workers."""
        with self._condition:
            self._shutdown = True
            self._condition.notify_all()
        if not wait:
            return
        deadline = time.monotonic() + max(0.1, float(timeout))
        for thread in self._live_workers():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        self._reap_dead_workers()

    # ------------------------------------------------------------------
    # Background pausing
    # ------------------------------------------------------------------

    def set_background_paused(self, paused: bool) -> None:
        """Pause/resume ``BACKGROUND`` and lower-priority jobs."""
        with self._condition:
            self._paused_background = bool(paused)
            self._condition.notify_all()

    @property
    def background_paused(self) -> bool:
        """Whether background work is currently held back."""
        return self._paused_background

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        priority: JobPriority = JobPriority.NORMAL,
        name: str | None = None,
        **kwargs: Any,
    ) -> Future:
        """Queue ``fn`` and return a :class:`~concurrent.futures.Future`.

        When the scheduler is shut down the call runs inline so callers
        (and shutdown paths) never lose work silently.
        """
        future: Future = Future()
        job = _Job(
            priority=int(priority),
            sequence=next(self._counter),
            future=future,
            name=name or getattr(fn, "__name__", "job"),
            fn=fn,
            args=args,
            kwargs=kwargs,
        )
        with self._condition:
            if self._shutdown:
                pass  # handled below, outside the lock
            else:
                heapq.heappush(self._queue, (job.priority, job.sequence, job))
                self._submitted += 1
                self._condition.notify()
                return future

        # Shutdown path: run inline.
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirrors Future semantics
            future.set_exception(exc)
        return future

    def cancel_background(self) -> int:
        """Drop queued background jobs, returning how many were removed."""
        removed = 0
        with self._condition:
            kept: list[tuple[int, int, _Job]] = []
            for entry in self._queue:
                if entry[0] >= int(BACKGROUND_THRESHOLD):
                    entry[2].cancelled = True
                    entry[2].future.cancel()
                    removed += 1
                else:
                    kept.append(entry)
            self._queue = kept
            heapq.heapify(self._queue)
            self._cancelled += removed
        return removed

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while True:
            job = self._next_job()
            if job is None:
                return
            if job.cancelled or job.future.cancelled():
                continue
            try:
                result = job.fn(*job.args, **job.kwargs)
            except BaseException as exc:  # noqa: BLE001 - surface via Future
                if not job.future.cancelled():
                    job.future.set_exception(exc)
            else:
                if not job.future.cancelled():
                    job.future.set_result(result)
            finally:
                with self._condition:
                    self._completed += 1

    def _next_job(self) -> _Job | None:
        with self._condition:
            while True:
                if self._shutdown and not self._queue:
                    return None
                if not self._queue:
                    if len(self._workers) > self._worker_limit:
                        self._retire_self()
                        return None
                    self._condition.wait(timeout=0.25)
                    continue
                if self._paused_background and self._queue[0][0] >= int(BACKGROUND_THRESHOLD):
                    # Only lower-priority work is queued: wait for a resume
                    # or for interactive work to arrive.
                    self._condition.wait(timeout=0.05)
                    continue
                return heapq.heappop(self._queue)[2]

    def _retire_self(self) -> None:
        """Remove the calling thread from the registry when over limit."""
        current = threading.current_thread()
        with self._workers_lock:
            self._workers = [thread for thread in self._workers if thread is not current]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def queue_depth(self) -> int:
        """Number of jobs waiting for a worker."""
        with self._condition:
            return len(self._queue)

    def stats(self) -> dict[str, Any]:
        """Return queue/throughput counters for the overlay and benchmarks."""
        with self._condition:
            by_priority: dict[str, int] = {}
            for priority, _seq, _job in self._queue:
                key = JobPriority(priority).name
                by_priority[key] = by_priority.get(key, 0) + 1
            return {
                "workers": self.worker_count,
                "worker_limit": self._worker_limit,
                "queue_depth": len(self._queue),
                "by_priority": by_priority,
                "submitted": self._submitted,
                "completed": self._completed,
                "cancelled": self._cancelled,
                "background_paused": self._paused_background,
            }
    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Block until the queue drains, or until ``timeout`` elapses.

        Returns:
            ``True`` when the queue is empty.
        """
        end = time.monotonic() + max(0.0, timeout)
        while True:
            if self.queue_depth == 0:
                return True
            if time.monotonic() >= end:
                return self.queue_depth == 0
            time.sleep(0.005)


_SCHEDULER: WorkerScheduler | None = None
_SCHEDULER_LOCK = threading.Lock()


def get_scheduler() -> WorkerScheduler:
    """Return the process-wide scheduler, creating it on first use."""
    global _SCHEDULER
    if _SCHEDULER is None:
        with _SCHEDULER_LOCK:
            if _SCHEDULER is None:
                _SCHEDULER = WorkerScheduler()
    return _SCHEDULER


def shutdown_scheduler() -> None:
    """Shut the process-wide scheduler down (used by tests and app exit)."""
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        scheduler = _SCHEDULER
        _SCHEDULER = None
    if scheduler is not None:
        scheduler.shutdown(wait=True)
