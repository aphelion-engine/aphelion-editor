"""UI-independent measured tracking samples and gap interpretation."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum


class TrackingState(str, Enum):
    TRACKING = "TRACKING"
    LOST = "LOST"
    REACQUIRING = "REACQUIRING"


class GapPolicy(Enum):
    Hold = "Hold Last Position"
    Interpolate = "Interpolate Gap"
    Extrapolate = "Extrapolate Motion"
    Disable = "Disable Effect During Gap"


@dataclass(frozen=True)
class TrackingSample:
    frame_number: int
    x: float | None
    y: float | None
    confidence: float
    valid: bool
    predicted: bool = False
    state: TrackingState = TrackingState.TRACKING
    predicted_x: float | None = None
    predicted_y: float | None = None
    reacquired: bool = False
    reason: str = ""

    def to_dict(self):
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["state"] = TrackingState(data.get("state","TRACKING"))
        return cls(**data)


@dataclass(frozen=True)
class TrackingOptions:
    track_threshold: float = 0.45
    reacquire_threshold: float = 0.65
    max_lost_frames: int = 30
    confirmation_frames: int = 2
    max_search_multiplier: float = 4.0
    ambiguity_margin: float = 0.08
    max_jump: float = 0.10

    def __post_init__(self):
        if not 0 <= self.track_threshold < self.reacquire_threshold <= 1:
            raise ValueError("Reacquisition confidence must exceed tracking confidence (0..1)")
        if self.max_lost_frames < 0 or self.confirmation_frames < 1:
            raise ValueError("Invalid recovery duration")
        if not 1 <= self.max_search_multiplier <= 16 or not 0 <= self.ambiguity_margin <= 1 or not 0 < self.max_jump <= 1:
            raise ValueError("Invalid search limits")


def resolve_gap(samples, frame, policy):
    """Resolve coordinates separately; never alter raw missing/measured samples."""
    sample = samples.get(frame)
    if sample is not None and sample.valid:
        return sample.x, sample.y
    if policy == GapPolicy.Disable:
        return None
    # Insertion order follows the tracking direction, including backward jobs.
    measured = [s for s in samples.values() if s.valid]
    if not measured:
        return None
    direction = 1 if list(samples)[-1] >= next(iter(samples)) else -1
    previous = [s for s in measured if (frame-s.frame_number)*direction >= 0]
    following = [s for s in measured if (s.frame_number-frame)*direction > 0]
    before = min(previous,key=lambda s:abs(frame-s.frame_number)) if previous else None
    after = min(following,key=lambda s:abs(frame-s.frame_number)) if following else None
    if before is None:
        return None
    if policy == GapPolicy.Interpolate and after is not None:
        t = (frame-before.frame_number)/(after.frame_number-before.frame_number)
        return before.x+(after.x-before.x)*t, before.y+(after.y-before.y)*t
    if policy == GapPolicy.Extrapolate and sample is not None and sample.predicted_x is not None:
        return sample.predicted_x,sample.predicted_y
    return before.x,before.y
