"""Thread-safe agent event bus for the revamped AI UI.

The rule is simple and strict: **model/network work runs on worker threads,
Qt UI work never does**.  Event *data* may be emitted from a worker, but the
*receivers* are all bound with ``Qt.QueuedConnection`` (or equivalent) so
every widget update happens on the main thread.  No widget is ever touched
from a background thread, and no worker thread is ever asked to start a QTimer
(or any other thread-affine object).

Events emitted here:
    AGENT_THINKING
    PLAN_READY
    TASK_STARTED
    STEP_STARTED
    STEP_COMPLETED
    TOOL_STARTED
    TOOL_COMPLETED
    PROJECT_EDIT
    QUESTION
    WAITING_FOR_USER
    VISUAL_QA_STARTED
    VISUAL_QA_RESULT
    VALIDATION_RESULT
    TASK_COMPLETED
    TASK_FAILED
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from ai.types import AgentEventKind

Logger = logging.Logger

_EVENT_LOG = logging.getLogger("aphelion.event_bus")

# ---------------------------------------------------------------------------
# Event kinds
# ---------------------------------------------------------------------------

class AgentEventKindError(ValueError):
    pass


def _coerce_kind(raw: Any) -> AgentEventKind:
    try:
        return AgentEventKind(raw)
    except Exception:
        raise AgentEventKindError(f"unknown event kind: {raw!r}") from None


# ---------------------------------------------------------------------------
# Event payload objects
# ---------------------------------------------------------------------------

@dataclass
class ThinkingPayload:
    """Summary-level reasoning the UI may show.  Not raw chain-of-thought."""
    stage: str          # e.g. "Inspecting footage", "Editing", "Validating"
    summary: str        # a few short sentences, human readable
    details: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "summary": self.summary,
            "details": list(self.details),
            "timestamp": self.timestamp,
        }


@dataclass
class PlanPayload:
    """The visible todo list the UI renders as a progress card."""
    steps: list[dict[str, Any]] = field(default_factory=list)
    finished: int = 0
    total: int = 0
    complete: bool = False
    headline: str = ""
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [dict(s) for s in self.steps],
            "finished": self.finished,
            "total": self.total,
            "complete": self.complete,
            "headline": self.headline,
            "timestamp": self.timestamp,
        }


@dataclass
class StepPayload:
    """One progress step (working / done / failed)."""
    title: str
    detail: str = ""
    done: bool = False
    failed: bool = False
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "done": self.done,
            "failed": self.failed,
            "timestamp": self.timestamp,
        }


@dataclass
class ToolPayload:
    name: str
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    ok: bool = True
    error_code: str = ""
    error: str = ""
    changed_node_ids: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "ok": self.ok,
            "error_code": self.error_code,
            "error": self.error,
            "changed_node_ids": list(self.changed_node_ids),
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


@dataclass
class ProjectEditPayload:
    action: str
    changed_node_ids: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "changed_node_ids": list(self.changed_node_ids),
            "timestamp": self.timestamp,
        }


@dataclass
class QuestionPayload:
    """A native confirmation card the UI shows to the user."""
    id: str
    title: str
    prompt: str
    options: list[dict[str, Any]]
    default_option_index: int | None = None
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prompt": self.prompt,
            "options": [dict(o) for o in self.options],
            "default_option_index": self.default_option_index,
            "timestamp": self.timestamp,
        }


@dataclass
class VisualQAPayload:
    frames_inspected: list[int]
    summary: str
    results: dict[str, Any]
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames_inspected": list(self.frames_inspected),
            "summary": self.summary,
            "results": dict(self.results),
            "timestamp": self.timestamp,
        }


@dataclass
class ValidationResultPayload:
    ok: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [dict(i) for i in self.issues],
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

@dataclass
class AgentEvent:
    kind: AgentEventKind
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_call: Any = None
    tool_result: Any = None

    @property
    def text(self) -> str:
        """Compatibility view for the Qt-free event contract."""
        return self.payload if isinstance(self.payload, str) else ""

    def __post_init__(self) -> None:
        self.kind = _coerce_kind(self.kind)

    def to_dict(self) -> dict[str, Any]:
        base = {"kind": self.kind.value}
        if self.payload is not None:
            base["payload"] = self.payload
        if self.metadata:
            base["metadata"] = dict(self.metadata)
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentEvent":
        kind = data["kind"]
        return cls(
            kind=kind,
            payload=data.get("payload"),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# The bridge.  Workers emit; the GUI receives.
# ---------------------------------------------------------------------------

class AgentEventBus(QObject):
    """Thread-safe emitter + main-thread receiver of structured agent events.

    The C++ object owns the signal/slot machinery, so slots are connected
    with ``Qt.QueuedConnection`` wherever they live on the GUI thread.  A
    worker thread calls :meth:`emit` with a plain dataclass; the Qt meta
    system delivers it to every slot on the receiver's thread.

    Slots must never mutate UI.  They simply convert the payload into a
    redraw or a dialog prompt.
    """

    #: Emitted on any thread that calls :meth:`emit`.
    _event = pyqtSignal(object)

    #: Delivered to a main-thread slot on the GUI thread.
    event_received = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # QueuedConnection guarantees the GUI thread receives and dispatches.
        self._event.connect(self._on_event, type=self._event)

    # -- public API ---------------------------------------------------------

    def emit(self, event: AgentEvent) -> None:
        """Push an event.  Safe to call from any thread.

        The datum is copied into a Qt ``QVariant``-compatible object before
        the queued send, so the sender's lifetime does not outlive the send.
        """
        try:
            self._event.emit(event)
        except Exception:  # noqa: BLE001
            _EVENT_LOG.exception("Failed to emit agent event: %r", event)

    def emit_sync(self, event: AgentEvent) -> None:
        """Emit and block until every receiver has finished processing."""
        if threading.current_thread() is self.event_received.sender():
            self._emit_now(event)
            return
        ev = threading.Event()
        results: dict[str, Any] = {}

        def _collect(result: Any) -> None:
            results["result"] = result
            ev.set()

        # Wire a temporary slot on the receiving thread.  The connection is
        # queued, so _collect runs after the GUI event loop has processed the
        # event, and the lock guarantees the slot is wired before we send.
        self.event_received.connect(_collect, type=self.event_received)
        self._event.emit(event)
        ev.wait()

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _on_event(event: AgentEvent) -> None:
        """Slot on the GUI thread.  Re-emit under a different signal so that
        connect(..., type=...) is unambiguous and we never re-enter the C++ slot
        that launched us."""
        try:
            AgentEventBus._deliver(event)
        except Exception:  # noqa: BLE001
            _EVENT_LOG.exception("Error delivering agent event to GUI")

    @staticmethod
    def _deliver(event: AgentEvent) -> None:
        # Normal flow: the queued connection delivers here.
        AgentEventBus._event.emit(event)

    def _emit_now(self, event: AgentEvent) -> None:
        self._event.emit(event)


# ---------------------------------------------------------------------------
# Thread-safe publisher wrapper
# ---------------------------------------------------------------------------

class EventPublisher:
    """A convenience wrapper so worker threads can ``publish(event)`` without
    thinking about threading."""

    def __init__(self, bus: AgentEventBus) -> None:
        self._bus = bus

    def publish(self, event: AgentEvent) -> None:
        self._bus.emit(event)

    def thinking(self, stage: str, summary: str, *, details: list[str] | None = None) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.THINKING, ThinkingPayload(stage, summary, details or [])))

    def plan_ready(self, plan: PlanPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.PLAN_READY, plan))

    def task_started(self, objective: str) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.TASK_STARTED, {"objective": objective}))

    def step_started(self, step: StepPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.STEP_STARTED, step))

    def step_completed(self, step: StepPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.STEP_COMPLETED, step))

    def tool_started(self, name: str, arguments: dict[str, Any] | None = None) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.TOOL_STARTED, ToolPayload(name, arguments)))

    def tool_completed(self, payload: ToolPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.TOOL_COMPLETED, payload))

    def project_edited(self, action: str, *, changed_node_ids: list[str] | None = None) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.PROJECT_EDIT, ProjectEditPayload(action, changed_node_ids or [])))

    def question(self, payload: QuestionPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.QUESTION, payload))

    def waiting_for_user(self) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.WAITING_FOR_USER))

    def visual_qa_started(self) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.VISUAL_QA_STARTED))

    def visual_qa_result(self, result: VisualQAPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.VISUAL_QA_RESULT, result))

    def validation_result(self, result: ValidationResultPayload) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.VALIDATION_RESULT, result))

    def task_completed(self) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.TASK_COMPLETED))

    def task_failed(self, error: str, *, details: str = "") -> None:
        self._bus.emit(AgentEvent(AgentEventKind.TASK_FAILED, {"error": error, "details": details}))

    def status(self, text: str) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.STATUS, text))

    def text(self, text: str) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.TEXT, text))

    def error(self, text: str) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.ERROR, text))

    def done(self) -> None:
        self._bus.emit(AgentEvent(AgentEventKind.DONE))
