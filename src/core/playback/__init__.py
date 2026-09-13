"""Playback engine internals: clock, deadlines, governor, and tracing.

Everything in this package is Qt-free and independently testable. It exists
because interactive playback is a *deadline* problem, not a rendering
problem: the question is never "can we eventually produce frame N", it is
"is frame N ready before it stops being the frame the user should be
looking at".

Layout
------
``clock``
    The master timeline clock. Answers "which frame should be on screen
    right now" independently of how long rendering takes.
``deadline``
    Bounded, deadline-ordered request queue that discards superseded work.
``governor``
    Adaptive preview quality with hysteresis, driven by measured deadline
    misses rather than by a fixed resolution.
``trace``
    Per-frame stage timings, stall detection, and JSON trace export.
"""

from __future__ import annotations

__all__ = ["clock", "deadline", "governor", "trace"]
