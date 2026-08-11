"""Top-level application windows."""

__all__ = ["Editor"]


def __getattr__(name: str) -> object:
    if name == "Editor":
        from ui.windows.editor import Editor

        return Editor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
