"""Exception hierarchy for the optional AI subsystem.

Every failure path the assistant can hit has a named exception so callers can
degrade gracefully instead of letting a provider or parsing bug reach the Qt
event loop. The editor never lets these escape past the panel.
"""

from __future__ import annotations


class AIError(Exception):
    """Base class for every AI-subsystem failure."""


class AIDisabledError(AIError):
    """Raised when the assistant is used while disabled in preferences."""


class ProviderError(AIError):
    """Base class for provider/transport failures."""


class ProviderAuthError(ProviderError):
    """Invalid, missing, or expired credentials."""


class ProviderRateLimitError(ProviderError):
    """The provider asked us to slow down."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailableError(ProviderError):
    """Network failure, timeout, or endpoint that cannot be reached."""


class ProviderResponseError(ProviderError):
    """The provider replied with something we could not interpret."""


class ContextOverflowError(ProviderError):
    """The request exceeded the model's context window."""


class ToolError(AIError):
    """A tool failed in a way that should be reported back to the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PermissionDeniedError(ToolError):
    """A tool was invoked without the capability it requires."""

    def __init__(self, message: str, *, permission: str = "") -> None:
        super().__init__("PERMISSION_DENIED", message)
        self.permission = permission


class ToolArgumentError(ToolError):
    """Tool arguments failed schema validation."""

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__("INVALID_ARGUMENTS", message)
        self.field = field


class ToolNotFoundError(ToolError):
    """The model asked for a tool this build does not expose."""

    def __init__(self, name: str) -> None:
        super().__init__("UNKNOWN_TOOL", f"No such tool: {name}")


class SourceError(ToolError):
    """Base class for the read-only source-intelligence subsystem.

    Derives from :class:`ToolError` so a refusal keeps its error code all the
    way back to the model (``ACCESS_DENIED``, ``SOURCE_SHARING_DISABLED``, ...)
    instead of being flattened into a generic tool failure.
    """

    def __init__(self, message: str, *, code: str = "SOURCE_ERROR") -> None:
        super().__init__(code, message)


class SourceAccessError(SourceError):
    """A source read was refused by the sandbox, allowlist, or denylist."""

    def __init__(self, message: str, *, code: str = "ACCESS_DENIED") -> None:
        super().__init__(message, code=code)


class SourceUnavailableError(SourceError):
    """No source tree is configured, or it could not be indexed."""

    def __init__(self, message: str, *, code: str = "SOURCE_UNAVAILABLE") -> None:
        super().__init__(message, code=code)


class CancelledError(AIError):
    """The user pressed Stop; no further model or tool work should run."""


class ValidationFailedError(AIError):
    """A transaction produced an invalid graph that could not be repaired."""

    def __init__(self, message: str, *, issues: list[dict] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []
