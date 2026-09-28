"""Worker thread that runs an :class:`AgentEngine` turn off the GUI thread.

The panel only ever touches the worker's structured events. Every widget update
happens on the main Qt thread through :class:`ai.platform.event_bus.AgentEventBus`
and the panel's queued signal/slot slots.
"""

from __future__ import annotations

from typing import Any, Callable

from ai.engine import AgentEngine, RunResult
from ai.platform.event_bus import (
    AgentEvent,
    AgentEventBus,
    AgentEventKind,
)
from ai.settings import AISettings
from ai.session import AssistantSession, SessionState
from ai.task import AgentTask, TaskStatus
from ai.types import ChatMessage, AgentMode, EditPolicy
from ai.types import PendingChanges


class AgentWorker:
    """Runs one assistant turn on a background thread.

    Attributes
    ----------
    session : AssistantSession
        The session the engine runs against.
    engine : AgentEngine
        The engine that executes the turn.
    on_event : Callable[[AgentEvent], None] | None
        Called (on whichever thread the worker runs on) with structured events
        as they are produced. The receiver must post these onto the GUI thread.
    on_finished : Callable[[RunResult], None] | None
        Called when the run completes, with the :class:`RunResult`.
    confirm : Callable[[PendingChanges, Any], bool] | None
        Called when the user must confirm a destructive edit.
    mode : AgentMode
        The agent mode to use for this run.
    """

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
        self.session = session
        self.initial_text = initial_text
        self.on_event = on_event
        self.on_finished = on_finished
        self.confirm = confirm
        self.mode = mode
        self.retry = retry

        self.engine = AgentEngine(
            host=session.host,
            registry=session.registry,
            provider=session.active_provider(),
            config=self._build_config(),
            permissions=session.settings.permissions,
            model=session.settings.default_provider_id,
            context_block=self.session.context_block(),
            source_context=self.session.source_context(),
            task=self.session.task,
            event_bus=None,
        )
        self.engine.workflow_plan = self.session.workflow_plan
        self.engine.task = session.task

        self._result: RunResult | None = None
        self._error: BaseException | None = None
        self._finished = False

    # -- configuration ----------------------------------------------------

    def _build_config(self) -> AISettings:
        settings = self.session.settings
        task = self.session.task
        return AISettings(
            enabled=settings.enabled,
            agent_mode=self.mode,
            edit_policy=EditPolicy.FULL_AGENT
            if self.mode is AgentMode.AGENT
            else EditPolicy.ASK_BEFORE_CHANGES,
            max_steps=settings.max_steps,
            max_tool_calls=settings.max_tool_calls,
            task_timeout=settings.task_timeout,
            stream=settings.stream,
            request_timeout=settings.request_timeout,
            verbose_logging=settings.verbose_logging,
            system_prompt=settings.system_prompt,
            effort=settings.agent_effort,
            enable_visual_qa=settings.enable_visual_qa,
            enable_workspace_research=settings.enable_workspace_research,
            emit_progress=settings.emit_progress,
            emit_summary=settings.emit_summary,
            plan_titles=task.todos.steps if task.todos else [],
        )

    # -- run ---------------------------------------------------------------

    def run(self) -> None:
        """Execute the turn on this thread and post structured events."""
        try:
            from ai.platform.event_bus import AgentEventBus

            bus = AgentEventBus()
            self.engine.event_bus = bus
            bus.event_received.connect(self._on_event_gui)
            bus.run_finished.connect(self._on_finished)

            messages = self._build_messages()
            self._result = self.engine.run(
                messages,
                on_event=self._emit_event,
                should_stop=self.session.should_stop,
                confirm=self.confirm,
                label="AI: Edit project",
            )
        except Exception as exc:  # noqa: BLE001
            self._error = exc
            self._result = RunResult(error=str(exc))
        finally:
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
        if self.on_event is not None:
            self.on_event(event)

    def _on_event_gui(self, event: AgentEvent) -> None:
        # Delivered on the GUI thread through the queued connection.
        if self.on_event is not None:
            self.on_event(event)

    def _on_finished(self, result: RunResult) -> None:
        if self.on_finished is not None:
            self.on_finished(result)

    # -- state ------------------------------------------------------------

    @property
    def result(self) -> RunResult | None:
        return self._result

    @property
    def error(self) -> BaseException | None:
        return self._error

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def task(self) -> AgentTask:
        return self.session.task

    @property
    def task_status(self) -> TaskStatus:
        return self.session.task.status

    def request_stop(self) -> None:
        self.session.request_stop()
