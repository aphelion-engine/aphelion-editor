"""Adaptive preview quality and execution cost estimation.

Two related jobs live here:

:class:`CostEstimator`
    Keeps a rolling per-node-type cost so the engine can *predict* whether
    the next frame fits in its budget, instead of discovering the overrun
    after the user is already several frames behind.

:class:`QualityGovernor`
    Turns those measurements into one decision — what preview scale to use
    right now — with hysteresis strict enough that quality never oscillates
    frame to frame. A professional editor that visibly bounces resolution
    reads as broken even when its average frame rate is fine.

Both are deliberately Qt-free and deterministic under test: every method
that cares about time takes it as a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.render_plan import RenderPlan

__all__ = [
    "SCALE_STEPS",
    "CostEstimator",
    "QualityDecision",
    "QualityGovernor",
]

#: Selectable preview scales, as a percentage of the Viewer preview width.
#: Ordered best-first so ``index + 1`` is always "one step cheaper".
SCALE_STEPS: tuple[int, ...] = (100, 75, 50, 33, 25, 13)


@dataclass(frozen=True, slots=True)
class QualityDecision:
    """The governor's current verdict."""

    scale_percent: int
    changed: bool
    reason: str
    predicted_ms: float
    budget_ms: float

    @property
    def headroom(self) -> float:
        """Fraction of the frame budget still unused (0..1, negative = over)."""
        if self.budget_ms <= 0.0:
            return 0.0
        return 1.0 - (self.predicted_ms / self.budget_ms)

    def to_dict(self) -> dict[str, float | int | str | bool]:
        """Return a JSON-friendly representation."""
        return {
            "scale_percent": self.scale_percent,
            "changed": self.changed,
            "reason": self.reason,
            "predicted_ms": round(self.predicted_ms, 3),
            "budget_ms": round(self.budget_ms, 3),
            "headroom": round(self.headroom, 4),
        }


# ----------------------------------------------------------------------
# Cost estimation
# ----------------------------------------------------------------------


class CostEstimator:
    """Rolling execution cost per node type, plus a graph-level estimate.

    Only enabled while it is being consulted (playback and benchmarks), so
    the disabled path costs a single boolean test at the call site rather
    than a timer on every node of every frame.
    """

    __slots__ = ("_node_ms", "_graph_ms", "_alpha", "_enabled", "_samples")

    #: EWMA weight for the newest sample. 0.2 ≈ a ~5-frame memory: responsive
    #: enough to react to a cache miss, stable enough not to chase noise.
    DEFAULT_ALPHA: float = 0.2

    def __init__(self, alpha: float = DEFAULT_ALPHA, enabled: bool = False) -> None:
        self._node_ms: dict[str, float] = {}
        self._graph_ms: float = 0.0
        self._alpha = max(0.01, min(1.0, float(alpha)))
        self._enabled = bool(enabled)
        self._samples = 0

    @property
    def enabled(self) -> bool:
        """Whether sampling is active."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable sampling."""
        self._enabled = bool(enabled)

    def observe(self, node_type: str, milliseconds: float) -> None:
        """Fold one node evaluation into the rolling estimate."""
        if not self._enabled or milliseconds < 0.0:
            return
        previous = self._node_ms.get(node_type)
        if previous is None:
            self._node_ms[node_type] = milliseconds
        else:
            alpha = self._alpha
            self._node_ms[node_type] = (1.0 - alpha) * previous + alpha * milliseconds
        self._samples += 1

    def observe_graph(self, milliseconds: float) -> None:
        """Fold one whole-graph frame evaluation into the rolling estimate."""
        if not self._enabled or milliseconds < 0.0:
            return
        if self._graph_ms <= 0.0:
            self._graph_ms = milliseconds
        else:
            alpha = self._alpha
            self._graph_ms = (1.0 - alpha) * self._graph_ms + alpha * milliseconds

    def node_cost_ms(self, node_type: str) -> float:
        """Return the rolling cost of one node type, or 0 when unknown."""
        return self._node_ms.get(node_type, 0.0)

    @property
    def graph_cost_ms(self) -> float:
        """Return the rolling whole-graph frame cost."""
        return self._graph_ms

    @property
    def samples(self) -> int:
        """Number of node samples folded in."""
        return self._samples

    def predict_ms(self, plan: "RenderPlan") -> float:
        """Predict the cost of evaluating ``plan`` for one frame.

        Measured values win; for node types never measured (a node that has
        not been reached yet, or a freshly added branch) the declared
        ``preview_cost`` class supplies a coarse fallback so the prediction
        is never zero and never wildly optimistic.
        """
        if self._graph_ms > 0.0:
            return self._graph_ms

        total = 0.0
        for node_id in plan.order:
            plan_node = plan.nodes.get(node_id)
            if plan_node is None:
                continue
            measured = self._node_ms.get(plan_node.node_type)
            if measured is not None:
                total += measured
            else:
                total += _FALLBACK_MS.get(plan_node.preview_cost, 1.0)
        return total

    def bottleneck(self, plan: "RenderPlan") -> tuple[str, float]:
        """Return ``(node_type, ms)`` for the most expensive measured node."""
        worst_type = ""
        worst_ms = 0.0
        for node_id in plan.order:
            plan_node = plan.nodes.get(node_id)
            if plan_node is None:
                continue
            value = self._node_ms.get(plan_node.node_type, 0.0)
            if value > worst_ms:
                worst_ms = value
                worst_type = plan_node.node_type
        return worst_type, worst_ms

    def ranking(self) -> list[tuple[str, float]]:
        """Return every measured node type, most expensive first."""
        return sorted(self._node_ms.items(), key=lambda item: item[1], reverse=True)

    def stats(self) -> dict[str, object]:
        """Return a snapshot for the overlay and traces."""
        return {
            "graph_ms": round(self._graph_ms, 3),
            "samples": self._samples,
            "hot": {name: round(ms, 3) for name, ms in self.ranking()[:5]},
        }

    def reset(self) -> None:
        """Discard all measurements."""
        self._node_ms.clear()
        self._graph_ms = 0.0
        self._samples = 0


#: Coarse per-node-type fallback cost, in milliseconds, by PreviewCost value.
_FALLBACK_MS: Mapping[int, float] = {
    0: 0.3,   # LIGHT
    1: 1.2,   # MEDIUM
    2: 6.0,   # HEAVY
    3: 18.0,  # EXTREME
}


# ----------------------------------------------------------------------
# Quality governor
# ----------------------------------------------------------------------


class QualityGovernor:
    """Chooses the preview scale from measured deadline behaviour.

    Hysteresis rules (all tunable, all deliberately conservative):

    * step **down** after ``downgrade_streak`` consecutive frames that each
      missed the deadline by a meaningful margin — one unlucky frame is
      noise, five in a row is a trend;
    * step **up** only after ``upgrade_stable_seconds`` of sustained
      headroom, where every frame used less than ``upgrade_headroom`` of the
      budget;
    * never change more often than ``min_dwell_seconds``.

    Parameters:
        min_scale_percent: Cheapest preview scale the governor may pick.
        max_scale_percent: Best preview scale the governor may pick.
        enabled: When False the governor reports ``max_scale_percent``.
    """

    #: Consecutive meaningful misses before stepping down.
    DOWNGRADE_STREAK: int = 5
    #: A miss counts only when the frame overran by at least this fraction
    #: of the budget. Absorbs measurement jitter around the boundary.
    MEANINGFUL_MISS_FRACTION: float = 0.10
    #: Sustained headroom required before stepping back up.
    UPGRADE_STABLE_SECONDS: float = 2.0
    #: Fraction of budget a frame must stay under to count as headroom.
    UPGRADE_HEADROOM: float = 0.65
    #: Minimum time between quality changes.
    MIN_DWELL_SECONDS: float = 1.5

    __slots__ = (
        "_enabled",
        "_steps",
        "_index",
        "_miss_streak",
        "_stable_since",
        "_last_change",
        "_last_predicted_ms",
        "_last_budget_ms",
        "_downgrades",
        "_upgrades",
    )

    def __init__(
        self,
        min_scale_percent: int = 25,
        max_scale_percent: int = 100,
        enabled: bool = True,
    ) -> None:
        steps = [
            step
            for step in SCALE_STEPS
            if step <= max(1, int(max_scale_percent))
            and step >= max(1, int(min_scale_percent))
        ]
        # ``SCALE_STEPS`` is best-first; a governor that cannot offer at
        # least two choices has nothing to adapt.
        self._steps: tuple[int, ...] = tuple(steps) or (max(1, int(max_scale_percent)),)
        self._enabled = bool(enabled)
        self._index = 0
        self._miss_streak = 0
        self._stable_since: float | None = None
        self._last_change: float | None = None
        self._last_predicted_ms = 0.0
        self._last_budget_ms = 0.0
        self._downgrades = 0
        self._upgrades = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the governor may change quality at all."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable adaptation."""
        self._enabled = bool(enabled)

    def set_range(self, min_scale_percent: int, max_scale_percent: int) -> None:
        """Update the allowed scale window and clamp the current step."""
        steps = [
            step
            for step in SCALE_STEPS
            if step <= max(1, int(max_scale_percent))
            and step >= max(1, int(min_scale_percent))
        ]
        self._steps = tuple(steps) or (max(1, int(max_scale_percent)),)
        self._index = min(self._index, len(self._steps) - 1)

    @property
    def scale_percent(self) -> int:
        """Currently selected preview scale."""
        return self._steps[self._index]

    @property
    def at_floor(self) -> bool:
        """Whether the governor is already at its cheapest scale."""
        return self._index >= len(self._steps) - 1

    @property
    def at_ceiling(self) -> bool:
        """Whether the governor is already at its best scale."""
        return self._index <= 0

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(
        self,
        cost_ms: float,
        budget_ms: float,
        now: float,
        *,
        missed: bool | None = None,
    ) -> None:
        """Fold one presented frame's timing into the adaptation state.

        Parameters:
            cost_ms: Measured end-to-end cost of the frame.
            budget_ms: Budget that frame had.
            now: Current monotonic time.
            missed: Explicit override for whether the deadline was missed.
                Derived from ``cost_ms > budget_ms`` when omitted.
        """
        self._last_predicted_ms = cost_ms
        self._last_budget_ms = budget_ms

        if not self._enabled or budget_ms <= 0.0:
            return

        if missed is None:
            overrun = cost_ms - budget_ms
            missed = overrun > budget_ms * self.MEANINGFUL_MISS_FRACTION

        if missed:
            self._miss_streak += 1
            self._stable_since = None
        else:
            self._miss_streak = 0
            if cost_ms < budget_ms * self.UPGRADE_HEADROOM:
                if self._stable_since is None:
                    self._stable_since = now
            else:
                # Comfortable but not idle: keep the "stable" timer honest.
                self._stable_since = now

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    def decide(self, now: float) -> QualityDecision:
        """Return the scale the engine should use for the next frame."""
        if not self._enabled:
            return self._decision(False, "disabled")

        if (
            self._last_change is not None
            and (now - self._last_change) < self.MIN_DWELL_SECONDS
        ):
            return self._decision(False, "dwell")

        if self._miss_streak >= self.DOWNGRADE_STREAK and not self.at_floor:
            self._index += 1
            self._miss_streak = 0
            self._last_change = now
            self._stable_since = None
            self._downgrades += 1
            return self._decision(True, "deadline-misses")

        if (
            self._stable_since is not None
            and (now - self._stable_since) >= self.UPGRADE_STABLE_SECONDS
            and not self.at_ceiling
        ):
            self._index -= 1
            self._last_change = now
            self._stable_since = now
            self._upgrades += 1
            return self._decision(True, "sustained-headroom")

        return self._decision(False, "steady")

    def _decision(self, changed: bool, reason: str) -> QualityDecision:
        return QualityDecision(
            scale_percent=self.scale_percent,
            changed=changed,
            reason=reason,
            predicted_ms=self._last_predicted_ms,
            budget_ms=self._last_budget_ms,
        )

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def force_scale(self, scale_percent: int) -> None:
        """Pin the governor to the closest available step."""
        target = max(1, int(scale_percent))
        best = min(range(len(self._steps)), key=lambda i: abs(self._steps[i] - target))
        self._index = best
        self._miss_streak = 0
        self._stable_since = None

    def reset(self, now: float | None = None) -> None:
        """Return to the best available scale and clear counters."""
        self._index = 0
        self._miss_streak = 0
        self._stable_since = None
        self._last_change = now
        self._downgrades = 0
        self._upgrades = 0

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, float | int | bool]:
        """Return a snapshot for the overlay and traces."""
        return {
            "scale_percent": self.scale_percent,
            "steps": len(self._steps),
            "enabled": self._enabled,
            "miss_streak": self._miss_streak,
            "downgrades": self._downgrades,
            "upgrades": self._upgrades,
            "last_ms": round(self._last_predicted_ms, 3),
            "budget_ms": round(self._last_budget_ms, 3),
        }

    def describe(self, plan: "RenderPlan" | None, estimator: CostEstimator | None) -> str:
        """Return the graph-complexity readout used by the status UI.

        Maps a predicted cost onto a plain-language verdict so the user can
        tell "this comp is fine" from "this comp needs a render cache"
        without reading a profiler.
        """
        if plan is None or estimator is None:
            return "Unknown"
        predicted = estimator.predict_ms(plan)
        budget = self._last_budget_ms or 33.33
        ratio = predicted / budget if budget > 0 else 0.0

        if ratio <= 0.6:
            verdict = "Realtime"
        elif ratio <= 1.0:
            verdict = "Heavy"
        elif ratio <= 2.0:
            verdict = "Very heavy"
        else:
            verdict = "Cache recommended"

        bottleneck, cost = estimator.bottleneck(plan)
        if bottleneck:
            return f"{verdict} · {bottleneck} {cost:.1f} ms"
        return verdict


def cheapest_step(scale_percent: int) -> int:
    """Return the cheapest configured step at or below ``scale_percent``."""
    for step in reversed(SCALE_STEPS):
        if step <= scale_percent:
            return step
    return SCALE_STEPS[-1]


def steps_within(minimum: int, maximum: int) -> Iterable[int]:
    """Yield the configured scale steps inside ``[minimum, maximum]``."""
    return (step for step in SCALE_STEPS if minimum <= step <= maximum)
