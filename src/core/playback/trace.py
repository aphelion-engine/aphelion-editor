"""Per-frame stage timing, stall detection, and trace export.

This is the instrumentation the rest of the playback work is justified by.
Without it, "playback feels laggy" is unfalsifiable; with it, a specific
frame is a specific number of milliseconds in a specific stage.

A record is opened when a frame is requested and closed when it is
presented, so every derived latency is measured end to end rather than
inferred:

===================  ====================================================
``requested_at``     When the playhead asked for the frame.
``due_at``           When it should have been on screen (from the clock).
``decode_ms``        Media decode + any decode-time proxy scaling.
``graph_ms``         Full node-graph evaluation for that frame.
``convert_ms``       Pipeline → display representation.
``upload_ms``        QImage/QPixmap hand-off to Qt.
``presented_at``     When the viewport actually painted it.
===================  ====================================================

The recorder is a bounded ring, so a long session cannot grow memory, and
it is cheap enough to leave on: appends are guarded by a single boolean.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = ["FrameRecord", "FrameTrace", "StallReport", "get_frame_trace"]

#: Stages tracked per frame, in pipeline order.
STAGES: tuple[str, ...] = ("decode_ms", "graph_ms", "convert_ms", "upload_ms")


@dataclass(slots=True)
class FrameRecord:
    """One frame's journey from request to presentation."""

    frame: int
    requested_at: float
    due_at: float
    generation: int = 0
    scale_percent: int = 100
    decode_ms: float = 0.0
    graph_ms: float = 0.0
    convert_ms: float = 0.0
    upload_ms: float = 0.0
    presented_at: float = 0.0
    #: True once :meth:`FrameTrace.close_record` has finalized the record.
    #: Liveness is tracked explicitly rather than inferred from
    #: ``presented_at > 0.0``: ``0.0`` is a perfectly legal monotonic
    #: timestamp (it is what a freshly started clock reads), so using it as
    #: the "not yet presented" sentinel silently discards real frames.
    closed: bool = False
    #: True when the frame was served without re-evaluating the graph.
    reused: bool = False
    #: Free-form annotations ("cache-miss", "gop-seek", "proxy", ...).
    tags: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived timings
    # ------------------------------------------------------------------

    @property
    def total_ms(self) -> float:
        """Sum of the tracked pipeline stages."""
        return self.decode_ms + self.graph_ms + self.convert_ms + self.upload_ms

    @property
    def end_to_end_ms(self) -> float:
        """Wall-clock latency from request to presentation."""
        if not self.closed or self.requested_at <= 0.0:
            return self.total_ms
        return (self.presented_at - self.requested_at) * 1000.0

    @property
    def lead_ms(self) -> float:
        """Milliseconds early (positive) or late (negative) vs. the deadline."""
        if not self.closed:
            return 0.0
        return (self.due_at - self.presented_at) * 1000.0

    @property
    def late_ms(self) -> float:
        """Milliseconds late; zero when on time."""
        return max(0.0, -self.lead_ms)

    @property
    def missed(self) -> bool:
        """Whether the frame reached the viewport after its deadline."""
        return self.closed and self.lead_ms < 0.0

    def stage_ms(self, stage: str) -> float:
        """Return one stage's duration by attribute name."""
        return float(getattr(self, stage, 0.0))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "frame": self.frame,
            "requested_at": round(self.requested_at, 6),
            "due_at": round(self.due_at, 6),
            "presented_at": round(self.presented_at, 6),
            "generation": self.generation,
            "scale_percent": self.scale_percent,
            "decode_ms": round(self.decode_ms, 4),
            "graph_ms": round(self.graph_ms, 4),
            "convert_ms": round(self.convert_ms, 4),
            "upload_ms": round(self.upload_ms, 4),
            "total_ms": round(self.total_ms, 4),
            "end_to_end_ms": round(self.end_to_end_ms, 4),
            "lead_ms": round(self.lead_ms, 4),
            "missed": self.missed,
            "reused": self.reused,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class StallReport:
    """A frame that took far longer than the session's typical frame."""

    frame: int
    total_ms: float
    median_ms: float
    ratio: float
    likely_cause: str
    stages: dict[str, float]

    def format(self) -> str:
        """Return a one-line human-readable explanation."""
        return (
            f"frame {self.frame}: {self.total_ms:.1f} ms "
            f"({self.ratio:.1f}x median {self.median_ms:.1f} ms) "
            f"→ {self.likely_cause}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "frame": self.frame,
            "total_ms": round(self.total_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "ratio": round(self.ratio, 3),
            "likely_cause": self.likely_cause,
            "stages": {key: round(value, 3) for key, value in self.stages.items()},
        }


def _percentile(values: list[float], fraction: float) -> float:
    """Return the nearest-rank percentile of ``values``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


class FrameTrace:
    """Bounded per-frame trace with derived statistics.

    Parameters:
        capacity: Ring size. 600 frames is ~20 seconds at 30 FPS — enough
            to diagnose a stutter without unbounded growth.
        enabled: When False, ``open_record`` returns ``None`` and callers
            skip all instrumentation.
    """

    __slots__ = ("_records", "_capacity", "_enabled", "_opened", "_dropped", "_reused")

    def __init__(self, capacity: int = 600, enabled: bool = False) -> None:
        self._records: deque[FrameRecord] = deque(maxlen=max(16, int(capacity)))
        self._capacity = max(16, int(capacity))
        self._enabled = bool(enabled)
        self._opened = 0
        self._dropped = 0
        self._reused = 0

    # ------------------------------------------------------------------
    # Enablement
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether records are being collected."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Turn collection on or off."""
        self._enabled = bool(enabled)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def open_record(
        self,
        frame: int,
        requested_at: float,
        due_at: float,
        *,
        generation: int = 0,
        scale_percent: int = 100,
    ) -> FrameRecord | None:
        """Begin a record; returns ``None`` when tracing is disabled."""
        if not self._enabled:
            return None
        self._opened += 1
        return FrameRecord(
            frame=int(frame),
            requested_at=float(requested_at),
            due_at=float(due_at),
            generation=int(generation),
            scale_percent=int(scale_percent),
        )

    def close_record(self, record: FrameRecord | None, now: float | None = None) -> None:
        """Finalize and store a record."""
        if record is None or not self._enabled:
            return
        record.presented_at = time.monotonic() if now is None else float(now)
        record.closed = True
        if record.reused:
            self._reused += 1
        self._records.append(record)

    def note_dropped(self, count: int = 1) -> None:
        """Record frames that were never presented."""
        if self._enabled:
            self._dropped += int(count)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @property
    def records(self) -> tuple[FrameRecord, ...]:
        """Return the retained records, oldest first."""
        return tuple(self._records)

    @property
    def capacity(self) -> int:
        """Ring size."""
        return self._capacity

    def reset(self) -> None:
        """Discard all records and counters."""
        self._records.clear()
        self._opened = 0
        self._dropped = 0
        self._reused = 0

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def _presented(self) -> list[FrameRecord]:
        return [record for record in self._records if record.closed]

    def summary(self) -> dict[str, Any]:
        """Return the numbers the developer HUD and benchmarks display."""
        presented = self._presented()
        count = len(presented)

        if count == 0:
            return {
                "frames": 0,
                "fps": 0.0,
                "budget_ms": 0.0,
                "decode_ms": 0.0,
                "graph_ms": 0.0,
                "convert_ms": 0.0,
                "upload_ms": 0.0,
                "total_ms": 0.0,
                "p95_ms": 0.0,
                "end_to_end_ms": 0.0,
                "late": 0,
                "miss_rate": 0.0,
                "dropped": self._dropped,
                "reused": self._reused,
            }

        totals = [record.total_ms for record in presented]
        decode = [record.decode_ms for record in presented]
        graph = [record.graph_ms for record in presented]
        convert = [record.convert_ms for record in presented]
        upload = [record.upload_ms for record in presented]
        e2e = [record.end_to_end_ms for record in presented]

        span = presented[-1].presented_at - presented[0].presented_at
        fps = (count - 1) / span if span > 0.0 and count > 1 else 0.0
        late = sum(1 for record in presented if record.missed)

        return {
            "frames": count,
            "fps": round(fps, 3),
            "budget_ms": round(
                statistics.fmean(
                    [(record.due_at - record.requested_at) * 1000.0 for record in presented]
                ),
                3,
            ),
            "decode_ms": round(statistics.fmean(decode), 3),
            "graph_ms": round(statistics.fmean(graph), 3),
            "convert_ms": round(statistics.fmean(convert), 3),
            "upload_ms": round(statistics.fmean(upload), 3),
            "total_ms": round(statistics.fmean(totals), 3),
            "p95_ms": round(_percentile(totals, 0.95), 3),
            "end_to_end_ms": round(statistics.fmean(e2e), 3),
            "late": late,
            "miss_rate": round(late / count, 4),
            "dropped": self._dropped,
            "reused": self._reused,
        }

    def median_frame_ms(self) -> float:
        """Return the median total frame cost."""
        totals = [record.total_ms for record in self._presented()]
        return statistics.median(totals) if totals else 0.0

    def stalls(self, ratio: float = 3.0, limit: int = 10) -> list[StallReport]:
        """Explain the frames that blew past the typical frame cost.

        Cause attribution compares each stall's stage profile against the
        median frame: whichever stage grew most in absolute terms is named
        as the likely cause, and any recorded tags are appended. This turns
        "it stuttered" into "frame 483 spent 96 ms in decode", which is what
        actually makes a stutter fixable.
        """
        presented = self._presented()
        if len(presented) < 4:
            return []

        median_ms = self.median_frame_ms()
        if median_ms <= 0.0:
            return []

        threshold = median_ms * max(1.1, float(ratio))

        baseline: dict[str, float] = {}
        for stage in STAGES:
            samples = [record.stage_ms(stage) for record in presented]
            baseline[stage] = statistics.median(samples) if samples else 0.0

        reports: list[StallReport] = []
        for record in presented:
            if record.total_ms < threshold:
                continue

            deltas = {
                stage: record.stage_ms(stage) - baseline.get(stage, 0.0)
                for stage in STAGES
            }
            worst_stage = max(deltas, key=lambda key: deltas[key]) if deltas else ""
            cause = _describe_stage(worst_stage)
            if record.tags:
                cause = f"{cause} ({', '.join(record.tags)})"

            reports.append(
                StallReport(
                    frame=record.frame,
                    total_ms=record.total_ms,
                    median_ms=median_ms,
                    ratio=record.total_ms / median_ms,
                    likely_cause=cause,
                    stages={stage: record.stage_ms(stage) for stage in STAGES},
                )
            )

        reports.sort(key=lambda report: report.total_ms, reverse=True)
        return reports[: max(1, int(limit))]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the whole trace as a JSON-friendly document."""
        return {
            "summary": self.summary(),
            "stalls": [report.to_dict() for report in self.stalls()],
            "records": [record.to_dict() for record in self._records],
        }

    def dump(self, path: str | Path) -> Path:
        """Write the trace to ``path`` as indented JSON."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
        return destination

    def format_report(self, limit: int = 8) -> str:
        """Return a terminal-friendly summary plus the worst stalls."""
        summary = self.summary()
        lines = [
            "frame trace",
            f"  frames          {summary['frames']}",
            f"  fps             {summary['fps']}",
            f"  budget          {summary['budget_ms']} ms",
            f"  decode          {summary['decode_ms']} ms",
            f"  graph           {summary['graph_ms']} ms",
            f"  convert         {summary['convert_ms']} ms",
            f"  upload          {summary['upload_ms']} ms",
            f"  total (mean)    {summary['total_ms']} ms",
            f"  total (p95)     {summary['p95_ms']} ms",
            f"  deadline misses {summary['late']} ({summary['miss_rate'] * 100:.1f}%)",
            f"  frames dropped  {summary['dropped']}",
            f"  frames reused   {summary['reused']}",
        ]
        stalls = self.stalls(limit=limit)
        if stalls:
            lines.append("  stalls:")
            lines.extend(f"    {report.format()}" for report in stalls)
        return "\n".join(lines)


#: Human-readable stage names for stall attribution.
_STAGE_LABELS: dict[str, str] = {
    "decode_ms": "media decode",
    "graph_ms": "graph evaluation",
    "convert_ms": "representation conversion",
    "upload_ms": "Qt upload",
}


def _describe_stage(stage: str) -> str:
    """Return a plain-language cause for an anomalous stage."""
    if not stage:
        return "unattributed"
    return _STAGE_LABELS.get(stage, stage)


def summarise_stages(records: Iterable[FrameRecord]) -> dict[str, float]:
    """Return mean milliseconds per stage across ``records``."""
    items = list(records)
    if not items:
        return {stage: 0.0 for stage in STAGES}
    return {
        stage: statistics.fmean(record.stage_ms(stage) for record in items)
        for stage in STAGES
    }


# ----------------------------------------------------------------------
# Process-wide trace
# ----------------------------------------------------------------------

_TRACE: FrameTrace | None = None


def get_frame_trace() -> FrameTrace:
    """Return the process-wide frame trace.

    One trace per process keeps the overlay, the worker, and the trace-dump
    command reading the same records instead of three separate rings.
    """
    global _TRACE
    if _TRACE is None:
        _TRACE = FrameTrace()
    return _TRACE


def reset_frame_trace() -> None:
    """Discard the process-wide trace (used by tests and benchmarks)."""
    global _TRACE
    _TRACE = None
