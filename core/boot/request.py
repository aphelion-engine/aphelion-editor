"""Boot request describing how the editor session should start."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BootMode(Enum):
    """How the boot driver should obtain a project document."""

    NEW = "new"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class BootRequest:
    """Immutable instruction for an editor boot sequence.

    Attributes:
        mode: Create a blank project or load an existing ``.aph`` file.
        path: Absolute path to open when ``mode`` is ``OPEN``; otherwise ``None``.
    """

    mode: BootMode
    path: str | None = None

    def __post_init__(self) -> None:
        if self.mode is BootMode.OPEN and not self.path:
            raise ValueError("BootMode.OPEN requires a project path")
