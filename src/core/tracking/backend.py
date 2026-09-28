"""Backend contracts shared by classical, planar, object, and ML trackers."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import numpy as np


class TrackingMode(str, Enum):
    AUTO = "Auto"
    FAST = "Fast"
    BALANCED = "Balanced"
    ACCURATE = "Accurate"
    MAXIMUM = "Maximum Quality"
    DEEP = "Deep Learning"


class TrackingTarget(str, Enum):
    AUTO = "Auto"
    POINT = "Point"
    OBJECT = "Object"
    PERSON = "Person"
    SURFACE = "Surface"
    FLOOR = "Floor"
    WALL = "Wall"
    SCREEN = "Screen"
    LARGE_AREA = "Large Area"


class BackendStatus(str, Enum):
    AVAILABLE = "available"
    OPTIONAL = "optional"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    status: BackendStatus
    target_types: tuple[TrackingTarget, ...]
    modes: tuple[TrackingMode, ...]
    requires_gpu: bool = False
    requires_model: str | None = None
    reason: str = ""


@dataclass
class BackendProposal:
    """A backend proposal before geometric/temporal fusion accepts it."""

    frame_number: int
    backend: str
    confidence: float
    visible: bool
    geometry: Any = None
    points: np.ndarray | None = None
    mask: np.ndarray | None = None
    diagnostics: dict[str, float | str | bool] = field(default_factory=dict)
    state: str = "UNKNOWN"
    accepted: bool = False


class TrackingBackend(Protocol):
    capabilities: BackendCapabilities

    def propose(self, frame_number: int, frame: np.ndarray, context: dict[str, Any]) -> BackendProposal | None:
        """Produce a proposal. Geometry validation belongs to the fusion layer."""

    def reset(self) -> None:
        """Release short-term state while retaining optional long-term memory."""


@dataclass
class BackendHealth:
    """Runtime health used for automatic backend switching."""

    confidence: float = 0.0
    consecutive_failures: int = 0
    last_frame: int | None = None
    active: bool = False

    def observe(self, confidence: float, frame_number: int, success: bool) -> None:
        self.confidence = float(np.clip(confidence, 0.0, 1.0))
        self.last_frame = frame_number
        self.consecutive_failures = 0 if success else self.consecutive_failures + 1
