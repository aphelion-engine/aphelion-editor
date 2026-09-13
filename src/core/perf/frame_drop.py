"""Adaptive preview frame-dropping policy.

Playback latency is dominated by one question: *is it worth finishing the
frame we are working on, or should we jump to the frame the clock says
should be visible right now?* A late frame is worthless — showing frame
493 while the clock reads 500 only adds latency that never recovers.

This module isolates that decision so it can be unit-tested without Qt,
threads, or a real project. It never applies to export/render, where every
frame is mandatory and ordering is correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

__all__ = [
    "FrameDropDecision",
    "FrameDropMode",
    "FrameDropPolicy",
]


class FrameDropMode(IntEnum):
    """How aggressively playback may skip preview frames."""

    OFF = 0
    CONSERVATIVE = 1
    BALANCED = 2
    AGGRESSIVE = 3
    ADAPTIVE = 4

    @classmethod
    def from_name(cls, name: str) -> "FrameDropMode":
        """Parse a preference string, defaulting to :attr:`BALANCED`."""
        normalized = str(name).strip().upper()
        try:
            return cls[normalized]
        except KeyError:
            return cls.BALANCED

    @property
    def label(self) -> str:
        """Human-readable name for the preferences UI."""
        return self.name.replace("_", " ").title()


#: ``(overload_multiplier, max_frames_skipped)`` per fixed mode.
#: A multiplier of 1.25 means "only drop once a frame takes 25% longer
#: than the playback budget".
_MODE_TOLERANCE: dict[FrameDropMode, tuple[float, float]] = {
    FrameDropMode.OFF: (float("inf"), 0.0),
    FrameDropMode.CONSERVATIVE: (1.60, 2.0),
    FrameDropMode.BALANCED: (1.25, 4.0),
    FrameDropMode.AGGRESSIVE: (1.02, 8.0),
}

# Adaptive mode escalates/de-escalates between these two fixed modes.
_ADAPTIVE_FLOOR = FrameDropMode.CONSERVATIVE
_ADAPTIVE_CEILING = FrameDropMode.AGGRESSIVE

#: Excess-latency ceilings, in "frame budgets", per fixed mode.
_MODE_LATENCY_BUDGET: dict[FrameDropMode, float] = {
    FrameDropMode.OFF: float("inf"),
    FrameDropMode.CONSERVATIVE: 2.0,
    FrameDropMode.BALANCED: 1.0,
    FrameDropMode.AGGRESSIVE: 0.5,
}


def _initial_tier(mode: FrameDropMode) -> FrameDropMode:
    """Return the tier a freshly configured policy starts at.

    ``ADAPTIVE`` is a *policy*, not a tier: it starts in the middle of the
    conservative↔aggressive range and moves from there based on measured
    frame cost, so a machine that is coping never behaves aggressively.
    """
    if mode is FrameDropMode.ADAPTIVE:
        return FrameDropMode.BALANCED
    return mode


@dataclass(frozen=True, slots=True)
class FrameDropDecision:
    """Result of one :meth:`FrameDropPolicy.decide` call."""

    drop: bool
    skip_frames: int
    latency_frames: float
    frame_budget_ms: float
    smoothed_ms: float
    mode: FrameDropMode
    reason: str

    @property
    def skip_to_offset(self) -> int:
        """Frames to advance past the requested frame (0 when not dropping)."""
        return self.skip_frames if self.drop else 0


class FrameDropPolicy:
    """Tracks observed frame cost and decides whether to skip work.

    Parameters:
        mode: Initial :class:`FrameDropMode`.
        target_fps: Playback rate the budget is derived from.

    Usage::

        policy = FrameDropPolicy(FrameDropMode.ADAPTIVE, target_fps=30)
        policy.observe(processing_seconds=0.048, queue_latency_seconds=0.02)
        decision = policy.decide()
        if decision.drop:
            playhead += decision.skip_frames
    """

    __slots__ = (
        "_mode",
        "_base_mode",
        "_target_fps",
        "_smoothed_ms",
        "_overload_streak",
        "_recovery_streak",
        "_decisions",
        "_drops",
        "_skipped",
        "_max_observed_ms",
    )

    #: EWMA weight for the newest sample (higher reacts faster).
    _ALPHA: float = 0.25
    #: Consecutive overloaded frames before adaptive mode escalates.
    _ESCALATE_AFTER: int = 3
    #: Consecutive comfortable frames before adaptive mode relaxes.
    _RECOVER_AFTER: int = 45

    def __init__(
        self,
        mode: FrameDropMode = FrameDropMode.BALANCED,
        target_fps: float = 30.0,
    ) -> None:
        self._base_mode = FrameDropMode(mode)
        self._mode = _initial_tier(self._base_mode)
        self._target_fps = max(0.001, float(target_fps))
        self._smoothed_ms: float = 0.0
        self._overload_streak: int = 0
        self._recovery_streak: int = 0
        self._decisions: int = 0
        self._drops: int = 0
        self._skipped: int = 0
        self._max_observed_ms: float = 0.0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def mode(self) -> FrameDropMode:
        """Configured mode (adaptive mode reports its current effective tier)."""
        return self._mode

    @property
    def config_mode(self) -> FrameDropMode:
        """Mode as configured by the user (may be ``ADAPTIVE``)."""
        return self._base_mode

    def set_mode(self, mode: FrameDropMode) -> None:
        """Set the drop mode and reset adaptation counters."""
        self._base_mode = FrameDropMode(mode)
        self._mode = _initial_tier(self._base_mode)
        self._overload_streak = 0
        self._recovery_streak = 0

    def set_target_fps(self, fps: float) -> None:
        """Update the playback rate the frame budget is derived from."""
        self._target_fps = max(0.001, float(fps))

    @property
    def frame_budget_ms(self) -> float:
        """Milliseconds available per frame at the current target rate."""
        return 1000.0 / self._target_fps

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(
        self,
        processing_seconds: float,
        queue_latency_seconds: float = 0.0,
    ) -> None:
        """Feed one completed frame's cost into the EWMA and adaptation.

        Parameters:
            processing_seconds: Wall-clock time the frame took to produce.
            queue_latency_seconds: Age of the result when it became ready.
        """
        total_ms = max(0.0, processing_seconds + queue_latency_seconds) * 1000.0
        if total_ms > self._max_observed_ms:
            self._max_observed_ms = total_ms

        if self._smoothed_ms <= 0.0:
            self._smoothed_ms = total_ms
        else:
            alpha = self._ALPHA
            self._smoothed_ms = (1.0 - alpha) * self._smoothed_ms + alpha * total_ms

        if self._base_mode is not FrameDropMode.ADAPTIVE:
            return

        budget = self.frame_budget_ms
        if self._smoothed_ms > budget * 1.10:
            self._overload_streak += 1
            self._recovery_streak = 0
            if self._overload_streak >= self._ESCALATE_AFTER:
                self._escalate()
        elif self._smoothed_ms < budget * 0.70:
            self._recovery_streak += 1
            self._overload_streak = 0
            if self._recovery_streak >= self._RECOVER_AFTER:
                self._decay()
        else:
            self._overload_streak = 0
            self._recovery_streak = 0

    def _escalate(self) -> None:
        """Move one tier toward :data:`_ADAPTIVE_CEILING`."""
        self._overload_streak = 0
        if self._mode < _ADAPTIVE_CEILING:
            self._mode = FrameDropMode(min(int(self._mode) + 1, int(_ADAPTIVE_CEILING)))

    def _decay(self) -> None:
        """Move one tier toward :data:`_ADAPTIVE_FLOOR`."""
        self._recovery_streak = 0
        if self._mode > _ADAPTIVE_FLOOR:
            self._mode = FrameDropMode(max(int(self._mode) - 1, int(_ADAPTIVE_FLOOR)))

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    def decide(self, latency_frames: float = 0.0) -> FrameDropDecision:
        """Decide whether the requested frame is still worth producing.

        Parameters:
            latency_frames: How many frames behind the clock the pending
                work already is (``0`` when the queue is empty).

        Returns:
            A :class:`FrameDropDecision`; ``drop=False`` means render
            normally.
        """
        self._decisions += 1
        budget = self.frame_budget_ms
        mode = self._mode
        tolerance, max_skip = _MODE_TOLERANCE.get(mode, (1.25, 4.0))

        comfortable = self._smoothed_ms <= budget * tolerance
        if comfortable and latency_frames < _MODE_LATENCY_BUDGET.get(mode, 1.0):
            return FrameDropDecision(
                drop=False,
                skip_frames=0,
                latency_frames=latency_frames,
                frame_budget_ms=budget,
                smoothed_ms=self._smoothed_ms,
                mode=mode,
                reason="on-budget",
            )

        # Whole frames the smoothed cost exceeds the budget by.
        overrun_frames = max(0.0, (self._smoothed_ms - budget) / budget)
        skip = int(min(max_skip, max(1.0, round(overrun_frames + latency_frames))))

        if skip <= 0:
            return FrameDropDecision(
                drop=False,
                skip_frames=0,
                latency_frames=latency_frames,
                frame_budget_ms=budget,
                smoothed_ms=self._smoothed_ms,
                mode=mode,
                reason="within-latency-budget",
            )

        self._drops += 1
        self._skipped += skip
        reason = "latency" if latency_frames >= 1.0 else "over-budget"
        return FrameDropDecision(
            drop=True,
            skip_frames=skip,
            latency_frames=latency_frames,
            frame_budget_ms=budget,
            smoothed_ms=self._smoothed_ms,
            mode=mode,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def smoothed_ms(self) -> float:
        """EWMA of observed per-frame cost in milliseconds."""
        return self._smoothed_ms

    @property
    def stats(self) -> dict[str, float | int | str]:
        """Counters for the performance overlay and benchmarks."""
        return {
            "mode": self._mode.label,
            "decisions": self._decisions,
            "drops": self._drops,
            "skipped_frames": self._skipped,
            "smoothed_ms": round(self._smoothed_ms, 3),
            "frame_budget_ms": round(self.frame_budget_ms, 3),
            "max_observed_ms": round(self._max_observed_ms, 3),
        }

    def reset(self) -> None:
        """Clear counters and the smoothed estimate."""
        self._smoothed_ms = 0.0
        self._overload_streak = 0
        self._recovery_streak = 0
        self._decisions = 0
        self._drops = 0
        self._skipped = 0
        self._max_observed_ms = 0.0
