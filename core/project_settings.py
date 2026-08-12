"""Immutable snapshot of editable project timeline and format settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    """Timeline resolution, frame rate, duration, and display name."""

    name: str
    fps: int
    width: int
    height: int
    duration: float

    def summary(self) -> str:
        """Compact label for status chrome."""
        return (
            f"{self.width}×{self.height}  ·  {self.fps} fps  ·  "
            f"{self.duration:.1f}s"
        )
