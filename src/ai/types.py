"""Qt-free domain types shared by the AI agent, tools, and providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, Flag, auto
from typing import Any


# ======================================================================
# Permissions
# ======================================================================


class Permission(Flag):
    """Capability categories a tool can require.

    The panel summarises these so a user can see exactly what the assistant
    may read and change. ``NONE`` is the implicit requirement for purely
    local bookkeeping tools.
    """

    NONE = 0
    READ_PROJECT = auto()
    EDIT_GRAPH = auto()
    EDIT_PROPERTIES = auto()
    EDIT_TIMELINE = auto()
    EDIT_PROJECT = auto()
    ACCESS_MEDIA = auto()
    ACCESS_VISION = auto()
    #: Read-only access to the Aphelion application source tree. Never grants
    #: a write, an execution, or a network call.
    READ_SOURCE = auto()


#: Human labels used by the settings UI and tool-description strings.
PERMISSION_LABELS: dict[Permission, str] = {
    Permission.READ_PROJECT: "Node graphs",
    Permission.EDIT_GRAPH: "Graph structure (nodes and connections)",
    Permission.EDIT_PROPERTIES: "Node properties",
    Permission.EDIT_TIMELINE: "Timeline",
    Permission.EDIT_PROJECT: "Project settings and saving",
    Permission.ACCESS_MEDIA: "Local media filenames",
    Permission.ACCESS_VISION: "Media frames and graph snapshots",
    Permission.READ_SOURCE: "Application source code",
}

#: Everything an agent needs to inspect a project but change nothing.
READ_ONLY_PERMISSIONS: Permission = Permission.READ_PROJECT

#: Sensible default: full editing, no media filenames, no vision, no source.
#: Source access is opt-in because it can expose the developer's checkout.
DEFAULT_PERMISSIONS: Permission = (
    Permission.READ_PROJECT
    | Permission.EDIT_GRAPH
    | Permission.EDIT_PROPERTIES
    | Permission.EDIT_TIMELINE
    | Permission.EDIT_PROJECT
)

#: Every permission this build understands, in display order.
ALL_PERMISSIONS: tuple[Permission, ...] = tuple(PERMISSION_LABELS)


def permission_mask(names: list[str] | tuple[str, ...]) -> Permission:
    """Build a flag from a list of ``Permission`` member names."""
    mask = Permission.NONE
    for name in names:
        try:
            mask |= Permission[str(name)]
        except KeyError:
            # Unknown names from a newer build are ignored rather than fatal.
            continue
    return mask


def permission_names(mask: Permission) -> list[str]:
    """Return the member names present in ``mask`` (stable order)."""
    return [member.name for member in ALL_PERMISSIONS if member in mask]


# ======================================================================
# Agent modes
# ======================================================================


class AgentMode(str, Enum):
    """How much authority the assistant has over the live project."""

    #: Inspect and answer only. Mutating tools are not offered to the model.
    ASK = "ask"
    #: Propose edits; the user confirms before anything is committed.
    ASSIST = "assist"
    #: Apply edits directly through the command system (still undoable).
    AGENT = "agent"

    @property
    def label(self) -> str:
        return {
            AgentMode.ASK: "Ask",
            AgentMode.ASSIST: "Assist",
            AgentMode.AGENT: "Agent",
        }[self]

    @property
    def allows_mutation(self) -> bool:
        return self is not AgentMode.ASK


class EditPolicy(str, Enum):
    """User preference for how significant changes are applied."""

    ASK_BEFORE_CHANGES = "ask_before_changes"
    AUTO_APPLY_SAFE = "auto_apply_safe"
    FULL_AGENT = "full_agent"

    @property
    def label(self) -> str:
        return {
            EditPolicy.ASK_BEFORE_CHANGES: "Ask Before Changes",
            EditPolicy.AUTO_APPLY_SAFE: "Auto Apply Safe Changes",
            EditPolicy.FULL_AGENT: "Full Agent Mode",
        }[self]


class SourceAccess(str, Enum):
    """How much of the Aphelion source tree the assistant may read.

    ``METADATA`` needs no checkout at all: the generated node catalog plus the
    live registry. ``CORE`` limits file reads to the editor's own source
    directories, and ``FULL`` allows any allowed file under the configured
    root. Every level is read-only and sandboxed.
    """

    OFF = "off"
    METADATA = "metadata"
    CORE = "core"
    FULL = "full"

    @property
    def label(self) -> str:
        return {
            SourceAccess.OFF: "Off",
            SourceAccess.METADATA: "Installed Build Metadata",
            SourceAccess.CORE: "Core Source Read-Only",
            SourceAccess.FULL: "Full Repository Read-Only",
        }[self]

    @property
    def allows_file_reads(self) -> bool:
        return self in (SourceAccess.CORE, SourceAccess.FULL)

    @property
    def allows_node_catalog(self) -> bool:
        return self is not SourceAccess.OFF


class CloudSourceSharing(str, Enum):
    """Whether retrieved source may be sent to a remote provider."""

    NEVER = "never"
    ASK = "ask"
    ALLOW = "allow"

    @property
    def label(self) -> str:
        return {
            CloudSourceSharing.NEVER: "Never",
            CloudSourceSharing.ASK: "Ask Every Time",
            CloudSourceSharing.ALLOW: "Allow",
        }[self]


# ======================================================================
# Provider metadata
# ======================================================================


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a specific model can actually do."""

    supports_tools: bool = False
    supports_vision: bool = False
    supports_json: bool = False
    context_window: int = 8192
    supports_streaming: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_json": self.supports_json,
            "context_window": self.context_window,
            "supports_streaming": self.supports_streaming,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProviderCapabilities:
        data = data or {}
        return cls(
            supports_tools=bool(data.get("supports_tools", False)),
            supports_vision=bool(data.get("supports_vision", False)),
            supports_json=bool(data.get("supports_json", False)),
            context_window=int(data.get("context_window", 8192) or 8192),
            supports_streaming=bool(data.get("supports_streaming", True)),
        )


@dataclass(frozen=True)
class ModelInfo:
    """One selectable model on a provider."""

    provider_id: str
    model_id: str
    label: str
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)

    @property
    def display(self) -> str:
        return f"{self.label} [{self.provider_id}]"


@dataclass(frozen=True)
class ProviderTestResult:
    """Outcome of a provider connection test shown in settings."""

    ok: bool
    message: str
    models: tuple[str, ...] = ()
    capabilities: ProviderCapabilities | None = None


# ======================================================================
# Chat + tool wire types
# ======================================================================


@dataclass
class ChatMessage:
    """One conversation turn in a provider-neutral shape."""

    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    #: Attached images for vision-capable models (data URLs or raw base64).
    images: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        return payload


@dataclass
class ToolCall:
    """A model-requested tool invocation (arguments not yet validated)."""

    name: str
    arguments: dict[str, Any]
    call_id: str = ""
    #: Raw argument text as produced by the model, retained for diagnostics.
    raw_arguments: str = ""


@dataclass
class ToolResult:
    """Authoritative outcome of executing one tool call.

    ``summary`` is what the UI shows ("Created Floor Tracker"); ``data`` is
    the structured payload handed back to the model. The model is instructed
    to treat these results as the only source of truth.
    """

    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error: str = ""
    #: User-facing action lines, e.g. ``["+ Add Floor Tracker"]``.
    details: list[str] = field(default_factory=list)
    #: Technical detail revealed when a user expands the action in the log.
    technical: dict[str, Any] = field(default_factory=dict)
    #: Node ids created or changed, used for highlighting.
    changed_node_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Inline images (``data:image/png;base64,...``) for vision-capable models.
    #: Deliberately excluded from :meth:`to_model_payload`; the engine attaches
    #: them to the conversation as message content part of a fixed size cap.
    images: list[str] = field(default_factory=list)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        *,
        technical: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            summary=message,
            error_code=code,
            error=message,
            technical=technical or {},
        )

    def to_model_payload(self, *, limit: int = 12_000) -> dict[str, Any]:
        """Return the JSON the model sees for this result (size-bounded)."""
        payload: dict[str, Any] = {"ok": self.ok, "summary": self.summary}
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.error:
            payload["error"] = self.error
        if self.data:
            payload["data"] = self.data
        if self.warnings:
            payload["warnings"] = self.warnings
        if self.changed_node_ids:
            payload["changed_node_ids"] = self.changed_node_ids
        text = _stringify(payload)
        if len(text) > limit:
            # Never let one verbose result blow the model's context budget.
            payload = {
                "ok": self.ok,
                "summary": self.summary,
                "truncated": True,
                "note": "Result was too large and has been truncated. "
                        "Re-query with narrower arguments if more detail is needed.",
            }
        return payload


class AgentEventKind(str, Enum):
    """Streaming events emitted by the agent loop for the UI."""

    STATUS = "status"
    TEXT = "text"
    REASONING = "reasoning"
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_STARTED = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_COMPLETED = "tool_result"
    PLAN = "plan"
    PLAN_READY = "plan"
    VALIDATION = "validation"
    VALIDATION_RESULT = "validation"
    PENDING_CHANGES = "pending_changes"
    PROJECT_EDIT = "project_edit"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    QUESTION = "question"
    WAITING_FOR_USER = "waiting_for_user"
    VISUAL_QA_STARTED = "visual_qa_started"
    VISUAL_QA_RESULT = "visual_qa_result"
    #: Structured completion report for the turn (what really changed and how
    #: completely the task finished). Rendered as the completion card.
    SUMMARY = "summary"
    ERROR = "error"
    DONE = "done"


@dataclass
class AgentEvent:
    """One streamed event from :class:`ai.engine.AgentEngine`."""

    kind: AgentEventKind
    text: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingChanges:
    """A set of edits the assistant wants to apply (Assist mode preview)."""

    label: str
    actions: list[str] = field(default_factory=list)
    changed_node_ids: list[str] = field(default_factory=list)
    #: ``True`` when the batch contains, or is, a destructive action that must
    #: be confirmed even under an auto-apply policy.
    destructive: bool = False


@dataclass
class Usage:
    """Token accounting when the provider reports it."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def merge(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


def _stringify(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)
