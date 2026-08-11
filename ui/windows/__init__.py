"""Top-level application windows."""

__all__ = [
    "AphelionRuntime",
    "ApplicationSession",
    "BootloaderWindow",
    "Editor",
    "ProjectLauncher",
]


def __getattr__(name: str) -> object:
    if name == "Editor":
        from ui.windows.editor import Editor

        return Editor
    if name == "ProjectLauncher":
        from ui.windows.launcher import ProjectLauncher

        return ProjectLauncher
    if name == "BootloaderWindow":
        from ui.windows.bootloader import BootloaderWindow

        return BootloaderWindow
    if name == "ApplicationSession":
        from ui.windows.session import ApplicationSession

        return ApplicationSession
    if name == "AphelionRuntime":
        from ui.windows.runtime import AphelionRuntime

        return AphelionRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
