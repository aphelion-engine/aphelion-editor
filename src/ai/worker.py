"""Worker thread that runs an :class:`AgentEngine` turn off the GUI thread.

The panel only ever touches the worker's structured events. Every widget update
happens on the main Qt thread through :class:`ai.platform.event_bus.AgentEventBus`
and the panel's queued signal/slot slots.
"""

from __future__ import annotations

from typing import Any, Callable

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from ai.engine import AgentEngine, RunResult, SYSTEM_PROMPT, AgentConfig
from ai.platform.event_bus import (
    AgentEvent,
    AgentEventBus,
    AgentEventKind,
)
from ai.settings import AISettings
from ai.context import ProjectContextProvider, ContextRequest
from ai.session import AssistantSession, SessionState
from ai.history import StoredMessage
from ai.task import AgentTask, TaskStatus
from ai.tasks import AgentEffort
from ai.types import ChatMessage, AgentMode, EditPolicy, SourceAccess
from ai.types import PendingChanges

#: Seconds the worker waits for a user decision before declining.
_CONFIRM_TIMEOUT_S: float = 600.0


class AgentWorker(QThread):
    """Runs one assistant turn on a background thread.

    Emits structured :class:`AgentEvent` instances through a dedicated
    :class:`AgentEventBus` with queued connections, so every widget update
    happens on the GUI thread. No worker ever touches a Qt widget directly.

    Attributes
    ----------
    session : AssistantSession
        The session the engine runs against.
    engine : AgentEngine
        The engine that executes the turn.
    on_event : Callable[[AgentEvent], None] | None
        Called on the GUI thread with structured events as they are produced.
    on_finished : Callable[[RunResult], None] | None
        Called on the GUI thread when the run completes.
    confirm : Callable[[PendingChanges, Any], bool] | None
        Called on the GUI thread when the user must confirm a destructive edit.
    mode : AgentMode
        The agent mode to use for this run.
    """

    #: Emitted on the GUI thread with structured events.
    event_received = pyqtSignal(AgentEvent)
    #: Emitted on the GUI thread when the run finishes.
    finished = pyqtSignal(RunResult)
    #: Emitted on the GUI thread when user confirmation is requested.
    confirm_requested = pyqtSignal(PendingChanges)

    def __init__(
        self,
        session: AssistantSession,
        initial_text: str,
        *,
        on_event: Callable[[AgentEvent], None] | None = None,
        on_finished: Callable[[RunResult], None] | None = None,
        confirm: Callable[[PendingChanges, Any], bool] | None = None,
        mode: AgentMode = AgentMode.ASSIST,
        retry: bool = False,
    ) -> None:
        super().__init__()
        self.session = session
        self.initial_text = initial_text
        self.on_event = on_event
        self.on_finished = on_finished
        self.confirm = confirm
        self.mode = mode
        self.retry = retry

        settings = session.settings
        task = session.task
        # Compute context block and source context the same way the session does.
        permissions = session._effective_permissions(mode)
        context_provider = ProjectContextProvider(session.host, permissions)
        context_block = context_provider.build(
            ContextRequest(node_ids=[])
        )
        # Recompute source context per run so a settings change takes effect.
        source_context = session._build_source_context(None)
        context_block = session._with_architecture(context_block, source_context)

        provider = session.build_provider() if callable(getattr(session, "build_provider", None)) else session.active_provider_config()
        self.engine = AgentEngine(
            host=session.host,
            registry=session.registry,
            provider=provider,
            config=self._build_config(settings, task),
            permissions=permissions,
            model=session.active_model(),
            context_block=context_block,
            source_context=source_context,
            task=task,
            event_bus=None,
        )
        self.engine.task = task

        self._result: RunResult | None = None
        self._error: BaseException | None = None
        self._finished = False
        self._confirm_event: threading.Event | None = None
        self._confirm_result: bool = False
        self._confirm_event_id: int | None = None

    # -- configuration ----------------------------------------------------

    def _build_config(self, settings: AISettings, task: AgentTask | None) -> AgentConfig:
        """Build the engine config from the session settings."""
        return AgentConfig(
            mode=self.mode,
            edit_policy=EditPolicy.FULL_AGENT
            if self.mode is AgentMode.AGENT
            else EditPolicy.ASK_BEFORE_CHANGES,
            max_steps=settings.max_agent_steps,
            max_tool_calls=settings.max_tool_calls if settings.max_tool_calls > 0 else 192,
            task_timeout=settings.request_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
            temperature=settings.temperature,
            stream=settings.stream,
            request_timeout=settings.request_timeout_seconds,
            verbose_logging=settings.verbose_logging,
            system_prompt=settings.system_prompt or SYSTEM_PROMPT,
            effort=getattr(settings, "agent_effort", AgentEffort.AUTO),
            enable_visual_qa=getattr(settings, "agent_effort", AgentEffort.AUTO) is not AgentEffort.FAST,
            enable_workspace_research=settings.source_access == SourceAccess.FULL,
            emit_progress=True,
            emit_summary=True,
            # plan_titles is held by the engine config (AgentConfig), not in AISettings.
        )

    # -- run ---------------------------------------------------------------

    def run(self) -> None:
        """Execute the turn on this thread.

        Structured events are emitted through a dedicated event bus with
        queued connections, so the GUI thread receives them on the
        appropriate signal/slot slots. No widget is touched here.
        """
        try:
            from ai.platform.event_bus import AgentEventBus

            bus = AgentEventBus()
            self.engine.event_bus = bus
            self.engine._event_bus = bus
            self.engine._publisher = self.engine._bind_publisher()
            # Queued connection: events are delivered on the GUI thread,
            # where the panel's slots update widgets.
            bus.event_received.connect(self.event_received.emit)

            messages = self._build_messages()
            self._result = self.engine.run(
                messages,
                on_event=self._emit_event,
                should_stop=self.session.should_stop,
                confirm=self._confirm_from_worker,
                label="AI: Edit project",
            )
        except Exception as exc:  # noqa: BLE001
            self._error = exc
            self._result = RunResult(error=str(exc))
        finally:
            if self._result is None:
                self._result = RunResult(error="The assistant worker stopped without a result.")
            self.session.last_result = self._result
            self.session.messages = list(self._result.messages or self.session.messages)
            self.session.state.busy = False
            if not self.retry and self.initial_text:
                self.session.turns.append(StoredMessage(role="user", content=self.initial_text))
            if self._result.text:
                self.session.turns.append(StoredMessage(
                    role="assistant", content=self._result.text,
                    actions=list(self._result.actions),
                ))
            self.session.persist()
            self.finished.emit(self._result)
            self._finished = True

    def _build_messages(self) -> list[ChatMessage]:
        task = self.session.task
        messages = list(self.session.messages)
        if self.retry:
            return messages
        if self.initial_text:
            messages.append(
                ChatMessage(role="user", content=self.initial_text)
            )
        return messages

    def _emit_event(self, event: AgentEvent) -> None:
        """Re-emit the event on the GUI thread via the bus."""
        self.event_received.emit(event)

    def _on_finished(self, result: RunResult) -> None:
        """Notify the panel that the run finished."""
        self.finished.emit(result)

    # -- state ------------------------------------------------------------

    @property
    def result(self) -> RunResult | None:
        return self._result

    @property
    def error(self) -> BaseException | None:
        return self._error

    @property
    def is_finished(self) -> bool:
        """Whether this worker has produced its terminal result."""
        return self._finished

    @property
    def task(self) -> AgentTask:
        return self.session.task

    @property
    def task_status(self) -> TaskStatus:
        return self.session.task.status

    def _confirm_from_worker(self, pending: PendingChanges, _transaction: Any) -> bool:
        """Request user confirmation for a destructive edit.

        Emits a signal the panel's slot picks up on the GUI thread, where it
        shows the confirmation dialog. Blocks the worker until the user
        responds (within the timeout).
        """
        self.confirm_requested.emit(pending)
        # Wait for the panel to respond. The panel sets _confirm_result
        # from its slot and signals an event that unblocks this thread.
        # This is a simple flag-based protocol; the worker does not touch
        # any Qt widget directly.
        import threading

        # Use a local event to avoid clobbering the panel's event.
        self._confirm_event = threading.Event()
        self._confirm_result = False
        self._confirm_event.wait(timeout=_CONFIRM_TIMEOUT_S)
        approved = self._confirm_result
        self._confirm_event = None
        return approved

    def request_stop(self) -> None:
        self.session.request_stop()


