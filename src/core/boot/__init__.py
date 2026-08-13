"""Editor boot pipeline: requests, recent projects, and staged loading."""

from core.boot.driver import BootStageResult, EditorBootDriver
from core.boot.recent import RecentProjectEntry, RecentProjectsStore
from core.boot.request import BootMode, BootRequest

__all__ = [
    "BootMode",
    "BootRequest",
    "BootStageResult",
    "EditorBootDriver",
    "RecentProjectEntry",
    "RecentProjectsStore",
]
