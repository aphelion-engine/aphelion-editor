"""Performance infrastructure: profiling, scheduling, and adaptive policy.

This package intentionally keeps the individual pieces small and single
purpose (see ``docs/performance.md``):

``profiler``      Optional timing scopes with rolling statistics.
``scheduler``     Central bounded priority worker pool.
``capabilities``  Hardware detection used to derive "Auto" settings.
``presets``       Named performance profiles (Eco → Maximum).
``frame_drop``    Adaptive preview frame-dropping policy.
"""

from __future__ import annotations

from core.perf.frame_drop import (FrameDropDecision, FrameDropMode,
                                  FrameDropPolicy)
from core.perf.profiler import (MetricSnapshot, Profiler, get_profiler,
                                is_profiling_enabled, profiler,
                                set_profiling_enabled)

__all__ = [
    "FrameDropDecision",
    "FrameDropMode",
    "FrameDropPolicy",
    "MetricSnapshot",
    "Profiler",
    "get_profiler",
    "is_profiling_enabled",
    "profiler",
    "set_profiling_enabled",
]
