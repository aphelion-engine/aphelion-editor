"""Optional, near-free timing scopes with rolling statistics.

Design goals
------------
* **Disabled is essentially free.** ``Profiler.scope`` returns a shared
  no-op singleton when profiling is off — no generator, no allocation, no
  timestamp call.
* **Enabled is cheap enough for per-frame use.** Each scope records one
  ``perf_counter`` pair into a fixed-size ring buffer. Percentiles are
  computed lazily, only when a snapshot is requested.
* **No global state surprises.** The module exposes one process-wide
  ``profiler`` used by the editor, but :class:`Profiler` can be
  instantiated freely (benchmarks and tests do exactly that).

Usage
-----
::

    from core.perf import profiler

    with profiler.scope("decode"):
        frame = decoder.read_rgb(index, width)

    for snapshot in profiler.snapshots().values():
        print(snapshot.format_line())
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterator

__all__ = [
    "MetricSnapshot",
    "Profiler",
    "get_profiler",
    "is_profiling_enabled",
    "profiler",
    "set_profiling_enabled",
]

_MS_PER_SECOND: float = 1000.0

#: Rolling window length per metric. 240 samples at 30 FPS is ~8 seconds,
#: which is long enough to be stable and short enough to react to changes.
DEFAULT_WINDOW: int = 240


class _NoOpScope:
    """Shared singleton returned by :meth:`Profiler.scope` when disabled."""

    __slots__ = ()

    def __enter__(self) -> "_NoOpScope":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


_NO_OP_SCOPE = _NoOpScope()


class _Scope:
    """Active timing scope; records elapsed seconds on exit."""

    __slots__ = ("_profiler", "_name", "_start")

    def __init__(self, profiler: "Profiler", name: str) -> None:
        self._profiler = profiler
        self._name = name
        self._start = 0.0

    def __enter__(self) -> "_Scope":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._profiler.record(self._name, time.perf_counter() - self._start)
        return False


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    """Immutable view of one metric's rolling statistics (all in ms)."""

    name: str
    count: int
    total_ms: float
    average_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    last_ms: float

    @property
    def samples(self) -> int:
        """Number of recorded samples inside the rolling window."""
        return self.count

    def format_line(self) -> str:
        """Return a fixed-width diagnostic line for logs and benchmarks."""
        return (
            f"{self.name:<20} avg {self.average_ms:8.3f}  "
            f"p50 {self.median_ms:8.3f}  p95 {self.p95_ms:8.3f}  "
            f"max {self.max_ms:8.3f}  n={self.count}"
        )

    def to_dict(self) -> dict[str, float | int | str]:
        """Return a JSON-friendly representation."""
        return {
            "name": self.name,
            "count": self.count,
            "total_ms": round(self.total_ms, 4),
            "average_ms": round(self.average_ms, 4),
            "median_ms": round(self.median_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "last_ms": round(self.last_ms, 4),
        }


class _Metric:
    """Thread-confined rolling sample buffer plus lazily sorted statistics."""

    __slots__ = (
        "name",
        "_samples",
        "_last_ms",
        "_percentile_cache",
        "_dirty",
    )

    def __init__(self, name: str, window: int) -> None:
        self.name = name
        self._samples: deque[float] = deque(maxlen=window)
        self._last_ms: float = 0.0
        self._percentile_cache: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._dirty: bool = True

    def record(self, seconds: float) -> None:
        milliseconds = seconds * _MS_PER_SECOND
        self._samples.append(milliseconds)
        self._last_ms = milliseconds
        self._dirty = True

    def reset(self) -> None:
        self._samples.clear()
        self._last_ms = 0.0
        self._percentile_cache = (0.0, 0.0, 0.0)
        self._dirty = True

    def _summarize(self) -> tuple[float, float, float]:
        """Return ``(median_ms, p95_ms, max_ms)`` for the current window.

        Sorting happens only when new samples have arrived, never on the
        recording path.
        """
        if not self._dirty:
            return self._percentile_cache

        ordered = sorted(self._samples)
        size = len(ordered)
        if size == 0:
            self._percentile_cache = (0.0, 0.0, 0.0)
        else:
            middle = size // 2
            if size % 2:
                median = ordered[middle]
            else:
                median = (ordered[middle - 1] + ordered[middle]) * 0.5
            p95_index = min(size - 1, int(round(0.95 * (size - 1))))
            self._percentile_cache = (median, ordered[p95_index], ordered[-1])

        self._dirty = False
        return self._percentile_cache

    def snapshot(self) -> MetricSnapshot:
        median, p95, peak = self._summarize()
        count = len(self._samples)
        total = sum(self._samples)
        return MetricSnapshot(
            name=self.name,
            count=count,
            total_ms=total,
            average_ms=(total / count) if count else 0.0,
            median_ms=median,
            p95_ms=p95,
            max_ms=peak,
            last_ms=self._last_ms,
        )


class Profiler:
    """Registry of named metrics with an on/off switch.

    Parameters:
        enabled: Whether scopes record timings.
        window: Rolling sample count retained per metric.

    Thread safety:
        Metrics are created under a lock; the sample deques themselves are
        only appended to from the owning thread of a given scope. Snapshot
        collection takes the same lock so a concurrent ``record`` cannot
        mutate a deque mid-iteration.
    """

    __slots__ = ("_metrics", "_enabled", "_lock", "_window")

    def __init__(self, enabled: bool = False, window: int = DEFAULT_WINDOW) -> None:
        self._metrics: dict[str, _Metric] = {}
        self._enabled: bool = bool(enabled)
        self._lock = threading.Lock()
        self._window: int = max(8, int(window))

    # ------------------------------------------------------------------
    # Enablement
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether scopes currently record timings."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Turn sampling on or off without discarding existing samples."""
        self._enabled = bool(enabled)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def scope(self, name: str) -> _Scope | _NoOpScope:
        """Return a context manager timing the enclosed block under ``name``."""
        if not self._enabled:
            return _NO_OP_SCOPE
        return _Scope(self, name)

    def record(self, name: str, seconds: float) -> None:
        """Record an already-measured duration (seconds) under ``name``."""
        if seconds < 0.0:
            return
        metric = self._metrics.get(name)
        if metric is None:
            with self._lock:
                metric = self._metrics.get(name)
                if metric is None:
                    metric = _Metric(name, self._window)
                    self._metrics[name] = metric
        metric.record(seconds)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def snapshots(self) -> dict[str, MetricSnapshot]:
        """Return a snapshot per metric, ordered by descending p95 cost."""
        with self._lock:
            metrics = list(self._metrics.values())
        snapshots = [metric.snapshot() for metric in metrics]
        snapshots.sort(key=lambda item: item.p95_ms, reverse=True)
        return {snapshot.name: snapshot for snapshot in snapshots}

    def hot_spots(self, limit: int = 8) -> list[MetricSnapshot]:
        """Return the ``limit`` most expensive metrics by p95."""
        ordered = list(self.snapshots().values())
        return ordered[: max(1, int(limit))]

    def report(self, limit: int = 16) -> str:
        """Return a human-readable multi-line report of all metrics."""
        lines = ["metric                     avg(ms)     p50     p95     max   samples"]
        for snapshot in list(self.snapshots().values())[: max(1, int(limit))]:
            lines.append(snapshot.format_line())
        if len(lines) == 1:
            lines.append("(no samples recorded)")
        return "\n".join(lines)

    def reset(self) -> None:
        """Discard all recorded samples."""
        with self._lock:
            for metric in self._metrics.values():
                metric.reset()


#: Process-wide profiler used by the editor. Disabled unless the user
#: turns on Performance Diagnostics in Preferences.
profiler = Profiler()


def get_profiler() -> Profiler:
    """Return the process-wide :data:`profiler`."""
    return profiler


def set_profiling_enabled(enabled: bool) -> None:
    """Enable or disable the process-wide profiler."""
    profiler.set_enabled(enabled)


def is_profiling_enabled() -> bool:
    """Return whether the process-wide profiler is recording."""
    return profiler.enabled


def scoped(name: str) -> Iterator[None]:  # pragma: no cover - convenience only
    """Deprecated generator alias kept for ad-hoc debugging sessions."""
    with profiler.scope(name):
        yield
