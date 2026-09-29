"""Assistant session: the Qt-free brain behind the panel.

The session owns the conversation, builds the provider, assembles context, and
runs the engine. The Qt panel is a thin view over this object, which is why the
whole assistant can be tested without a display.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ai.context import ContextRequest, ProjectContextProvider
from ai.credentials import CredentialStore
from ai.engine import AgentConfig, AgentEngine, RunResult
from ai.errors import AIError, AIDisabledError, ProviderError
from ai.history import (Conversation, ConversationStore, StoredMessage,
                        new_conversation, project_key)
from ai.permissions import PermissionPolicy
from ai.providers.registry import create_provider
from ai.settings import AISettings, ProviderConfig
from ai.task import AgentTask
from ai.source.factory import build_source_context
from ai.tools.base import build_default_registry
from ai.types import (AgentEvent, AgentEventKind, AgentMode, ChatMessage,
                      ModelInfo, PendingChanges, Permission, SourceAccess)
from utils.logging_setup import get_logger

_LOG = get_logger("ai.session")

#: Slash commands that expand into a directive for the model.
SLASH_COMMANDS: dict[str, str] = {
    "/graph": (
        "Describe the current graph: the processing flow, its main branches, and "
        "anything that looks wrong. Inspect it with tools first."
    ),
    "/selection": (
        "Explain what is currently selected and how it is wired into the graph."
    ),
    "/validate": "Validate the graph and report every problem you find.",
    "/explain": (
        "Explain the current graph in plain language: what it does, how data "
        "flows, which parts are expensive, and any suspicious connections."
    ),
    "/fix": (
        "Find and repair problems in the graph: validate, diagnose, fix only "
        "real issues, then validate again and explain the changes."
    ),
}

#: Matches ``@Some Name`` or ``@"Some Name"`` mentions.
_MENTION_RE = re.compile(r'@(?:"([^"]+)"|([^\s,;]+))')


@dataclass
class SessionState:
    """Mutable per-session UI state mirrored from the engine."""

    busy: bool = False
    cancelled: bool = False
    last_error: str = ""
    pending: PendingChanges | None = None


class AssistantSession:
    """Owns one conversation and the provider that serves it."""

    def __init__(
        self,
        host: Any,
        settings: AISettings,
        *,
        credentials: CredentialStore | None = None,
        registry: Any = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self.host = host
        self.settings = settings
        self.credentials = credentials or CredentialStore()
        self.registry = registry or build_default_registry()
        self.conversations = conversation_store or ConversationStore()

        self.task = AgentTask()
        self._retry_messages = []
        self.messages: list[ChatMessage] = []
        self.turns: list[StoredMessage] = []
        self.conversation: Conversation = new_conversation()
        self.state = SessionState()
        self._stop_requested = False
        self._unlocked_messages: list[ChatMessage] = []
        self.last_result: RunResult | None = None
        #: The most recent source context, used by the "Show AI context" view.
        self._last_source_context: Any = None

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled)

    def active_provider_config(self) -> ProviderConfig | None:
        return self.settings.active_provider()

    def build_provider(self) -> Any:
        """Construct the provider for the active configuration.

        Raises:
            AIDisabledError: when the assistant is off.
            ProviderError: when no provider/model is configured.
        """
        if not self.settings.enabled:
            raise AIDisabledError("The AI assistant is disabled.")
        config = self.active_provider_config()
        if config is None:
            raise ProviderError(
                "No AI provider is enabled. Enable one in Preferences → AI."
            )
        provider = create_provider(
            config,
            credentials=self.credentials,
            timeout=self.settings.request_timeout_seconds,
        )
        provider.transport.debug_logging = self.settings.verbose_logging
        return provider

    def capabilities(self) -> Any:
        from ai.types import ProviderCapabilities

        try:
            provider = self.build_provider()
        except AIError:
            return ProviderCapabilities()
        return provider.capabilities(self.active_model())

    def active_model(self) -> str:
        config = self.active_provider_config()
        return config.model if config else ""

    def provider_scope(self) -> str:
        config = self.active_provider_config()
        return config.scope if config else "—"

    def available_models(self) -> list[ModelInfo]:
        """Return models the user can switch to, from every enabled provider."""
        models: list[ModelInfo] = []
        for config in self.settings.enabled_providers():
            try:
                provider = create_provider(
                    config,
                    credentials=self.credentials,
                    timeout=min(20.0, self.settings.request_timeout_seconds),
                )
                found = provider.list_models()
            except Exception:  # noqa: BLE001 - a dead provider yields no models
                found = ()
            if not found and config.model:
                found = (config.model_info(),)
            models.extend(found)
        if not models:
            config = self.active_provider_config()
            if config and config.model:
                models.append(config.model_info())
        return models

    def test_provider(self, provider_id: str) -> Any:
        """Run a connection test for one configured provider."""
        from ai.types import ProviderTestResult

        config = self.settings.provider(provider_id)
        if config is None:
            return ProviderTestResult(ok=False, message="Unknown provider.")
        try:
            provider = create_provider(
                config,
                credentials=self.credentials,
                timeout=min(30.0, self.settings.request_timeout_seconds),
            )
            return provider.test_connection()
        except AIError as exc:
            return ProviderTestResult(ok=False, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - never let a test crash the UI
            return ProviderTestResult(
                ok=False, message=f"{type(exc).__name__}: {exc}"
            )

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def start_new_conversation(self) -> None:
        """Begin a fresh conversation without touching the project."""
        self.task = AgentTask()
        self._retry_messages = []
        self.messages = []
        self.turns = []
        self._unlocked_messages = []
        self.last_result = None
        self.state = SessionState()
        config = self.active_provider_config()
        self.conversation = new_conversation(
            provider_id=config.provider_id if config else "",
            model=config.model if config else "",
        )

    def load_conversation(self, conversation: Conversation) -> None:
        """Restore a stored conversation into the working history."""
        self.conversation = conversation
        self.turns = list(conversation.messages)
        self.messages = [
            ChatMessage(
                role=message.role,
                content=message.content,
            )
            for message in conversation.messages
            if message.role in ("user", "assistant")
        ]
        self._unlocked_messages = list(self.messages)

    def stored_conversations(self) -> list[Conversation]:
        if not self.settings.save_conversations:
            return []
        key = self.host.invoke_project(lambda: project_key(self.host.project))
        return self.conversations.load(key)

    def persist(self) -> None:
        """Write this conversation when the user opted into persistence."""
        if not self.settings.save_conversations:
            return
        self.conversation.messages = list(self.turns)
        self.conversation.updated_at = time.time()
        if self.conversation.messages and self.conversation.title == "New conversation":
            first = next(
                (m.content for m in self.conversation.messages if m.role == "user"),
                "",
            )
            self.conversation.title = (first[:60] or "Conversation").strip()
        key = self.host.invoke_project(lambda: project_key(self.host.project))
        existing = [
            stored
            for stored in self.conversations.load(key)
            if stored.conversation_id != self.conversation.conversation_id
        ]
        existing.insert(0, self.conversation)
        try:
            self.conversations.save(key, existing)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            _LOG.warning("Could not persist conversation: %s", exc)

    # ------------------------------------------------------------------
    # Input parsing
    # ------------------------------------------------------------------

    def expand_input(self, text: str) -> tuple[str, list[str]]:
        """Resolve slash commands and @mentions in a user message.

        Returns:
            ``(expanded_prompt, mentioned_node_ids)``.
        """
        stripped = text.strip()
        directive = ""
        for command, prompt in SLASH_COMMANDS.items():
            if stripped.lower().startswith(command):
                directive = prompt
                stripped = stripped[len(command):].strip()
                break

        mentioned: list[str] = []
        for match in _MENTION_RE.finditer(stripped):
            name = (match.group(1) or match.group(2) or "").strip()
            if not name:
                continue
            node_id = self._resolve_mention(name)
            if node_id:
                mentioned.append(node_id)

        parts: list[str] = []
        if directive:
            parts.append(directive)
        if mentioned:
            labels = self.host.invoke_project(
                lambda: [
                    f"{node.name} ({node_id})" if (node := self.host.project.nodes.get(node_id)) else node_id
                    for node_id in mentioned
                ]
            )
            parts.append("The user referred to these nodes: " + ", ".join(labels) + ".")
        if stripped:
            parts.append(stripped)
        return "\n".join(parts).strip(), mentioned

    def mention_candidates(self, prefix: str) -> list[tuple[str, str]]:
        """Return ``(node_id, name)`` pairs matching an in-progress mention."""
        needle = prefix.strip().lower()

        def collect() -> list[tuple[str, str]]:
            rows = [
                (node_id, node.name)
                for node_id, node in self.host.project.nodes.items()
                if not needle or needle in node.name.lower() or needle in node.node_type.lower()
            ]
            rows.sort(key=lambda item: item[1].lower())
            return rows[:20]

        return self.host.invoke_project(collect)

    def _resolve_mention(self, name: str) -> str | None:
        return self.host.invoke_project(lambda: self._resolve_mention_on_project(name))

    def _resolve_mention_on_project(self, name: str) -> str | None:
        project = self.host.project
        if name in project.nodes:
            return name
        lowered = name.lower()
        exact = [
            node_id
            for node_id, node in project.nodes.items()
            if node.name == name
        ]
        if len(exact) == 1:
            return exact[0]
        for node_id, node in project.nodes.items():
            if node.name.lower() == lowered:
                return node_id
        for node_id, node in project.nodes.items():
            if lowered in node.name.lower():
                return node_id
        return None

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send(
        self,
        text: str,
        *,
        on_event: Callable[[AgentEvent], None] | None = None,
        confirm: Callable[[PendingChanges, Any], bool] | None = None,
        mode: AgentMode | None = None,
    ) -> RunResult:
        """Run one turn. Never raises; failures arrive as events."""
        emit = on_event or (lambda _event: None)
        expanded, mentioned = self.expand_input(text)
        self._retry_messages = list(self.messages)
        self.turns.append(StoredMessage(role="user", content=text, timestamp=time.time()))

        if not self.settings.enabled:
            message = (
                "The AI assistant is disabled. Enable it in Preferences → AI to "
                "start a conversation."
            )
            self.state.last_error = message
            emit(AgentEvent(AgentEventKind.ERROR, message))
            return RunResult(error=message)

        try:
            provider = self.build_provider()
        except AIError as exc:
            message = str(exc)
            self.state.last_error = message
            emit(AgentEvent(AgentEventKind.ERROR, message))
            return RunResult(error=message)

        self._retry_messages = list(self.messages)
        request = ChatMessage(role="user", content=expanded or text)
        self.messages.append(request)

        permissions = self._effective_permissions(mode)
        context_provider = ProjectContextProvider(self.host, permissions)
        context_block = context_provider.build(
            ContextRequest(node_ids=mentioned)
        )
        # Read-only source intelligence, assembled per run so a settings change
        # takes effect immediately. Building this never walks the source tree:
        # the index is populated on the first source.* tool call.
        source_context = self._build_source_context(confirm)
        context_block = self._with_architecture(context_block, source_context)

        config = AgentConfig(
            mode=mode or self.settings.agent_mode,
            edit_policy=self.settings.edit_policy,
            max_steps=self.settings.max_agent_steps,
            max_output_tokens=self.settings.max_output_tokens,
            temperature=self.settings.temperature,
            stream=self.settings.stream,
            request_timeout=self.settings.request_timeout_seconds,
            verbose_logging=self.settings.verbose_logging,
        )
        engine = AgentEngine(
            host=self.host,
            registry=self.registry,
            provider=provider,
            config=config,
            permissions=permissions,
            model=self.active_model(),
            context_block=context_block,
            source_context=source_context,
            task=self.task,
        )

        self._stop_requested = False
        self.state.busy = True
        self.state.pending = None

        def should_stop() -> bool:
            return self._stop_requested

        try:
            result = engine.run(
                list(self.messages),
                on_event=on_event,
                should_stop=should_stop,
                confirm=confirm,
                label=self._transaction_label(text),
            )
        except AIError as exc:  # defence in depth: the engine also guards
            message = str(exc)
            self.state.last_error = message
            emit(AgentEvent(AgentEventKind.ERROR, message))
            result = RunResult(error=message)
        finally:
            self.state.busy = False

        self.last_result = result
        self.state.cancelled = result.cancelled
        self.state.last_error = result.error
        self.messages = result.messages or self.messages
        if result.text:
            self.turns.append(
                StoredMessage(
                    role="assistant",
                    content=result.text,
                    actions=list(result.actions),
                    timestamp=time.time(),
                )
            )
        elif result.error:
            self.turns.append(
                StoredMessage(
                    role="assistant",
                    content=f"(error) {result.error}",
                    timestamp=time.time(),
                )
            )
        self.persist()
        return result

    def retry(
        self,
        *,
        model: str | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        confirm: Callable[[PendingChanges, Any], bool] | None = None,
    ) -> RunResult:
        """Re-run the last user message, optionally on a different model."""
        if model:
            config = self.active_provider_config()
            if config is not None and config.model != model:
                updated = ProviderConfig.from_dict(config.to_dict())
                updated.model = model
                self.settings.set_provider(updated)
        last_user = next(
            (message.content for message in reversed(self.turns) if message.role == "user"),
            "",
        )
        if not last_user:
            return RunResult(error="There is nothing to retry.")
        while self.turns and self.turns[-1].role == "assistant":
            self.turns.pop()
        if self.turns and self.turns[-1].role == "user":
            self.turns.pop()
        self.messages = list(self._retry_messages)
        return self.send(last_user, on_event=on_event, confirm=confirm)

    def request_stop(self) -> None:
        """Ask the running turn to stop after the current tool completes."""
        self._stop_requested = True
        self.state.cancelled = True

    def should_stop(self) -> bool:
        """Return whether the active worker has been asked to cancel."""
        return self._stop_requested

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _effective_permissions(self, mode: AgentMode | None) -> PermissionPolicy:
        policy = self.settings.permissions
        # Choosing a source-access level *is* the grant: the two switches in
        # settings must not disagree, so the capability follows the level.
        if self.settings.source_access is not SourceAccess.OFF:
            policy = policy.with_permission(Permission.READ_SOURCE, True)
        active_mode = mode or self.settings.agent_mode
        if not isinstance(active_mode, AgentMode):
            active_mode = AgentMode(str(active_mode))
        if active_mode is AgentMode.ASK:
            return policy.without_all_edits()
        return policy

    def _build_source_context(self, confirm: Any) -> Any:
        """Build this run's read-only source context (never raises)."""
        try:
            config = self.active_provider_config()
            is_local = bool(config is not None and config.scope == "LOCAL")
            consent = None
            if confirm is not None:
                consent = lambda: bool(
                    confirm(
                        PendingChanges(
                            label="Share Aphelion source code with this provider?",
                            actions=[
                                "+ Read-only source snippets are sent to the "
                                "remote model",
                                "+ Only files inside the configured source root",
                                "+ Secret-looking values are redacted first",
                            ],
                        ),
                        None,
                    )
                )
            context = build_source_context(
                self.settings,
                provider_is_local=is_local,
                consent=consent,
            )
            self._last_source_context = context
            return context
        except Exception as exc:  # noqa: BLE001 - source context is optional
            _LOG.warning("source context unavailable: %s", type(exc).__name__)
            return None

    def source_status(self) -> dict[str, Any]:
        """Describe source access for the UI audit view."""
        context = self._last_source_context
        if context is None:
            return {
                "access": self.settings.source_access.value,
                "access_label": self.settings.source_access.label,
                "enabled": False,
                "reason": "No source context has been built yet.",
            }
        return context.status()

    @staticmethod
    def _with_architecture(context_block: str, source_context: Any) -> str:
        """Add the cheap registry digest to the context block."""
        if source_context is None or not source_context.enabled:
            return context_block
        import json

        try:
            payload = json.loads(context_block)
        except (TypeError, ValueError):
            return context_block
        if not isinstance(payload, dict):
            return context_block
        payload["architecture"] = source_context.digest()
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _transaction_label(text: str) -> str:
        cleaned = " ".join((text or "").split())
        for command in SLASH_COMMANDS:
            if cleaned.lower().startswith(command):
                cleaned = cleaned[len(command):].strip()
                break
        if not cleaned:
            return "AI: Edit project"
        if len(cleaned) > 60:
            cleaned = cleaned[:57].rstrip() + "…"
        return f"AI: {cleaned[0].upper()}{cleaned[1:]}"

    # ------------------------------------------------------------------
    # Descriptions
    # ------------------------------------------------------------------

    def permission_summary(self) -> list[tuple[str, str, bool]]:
        rows = []
        for permission, label, enabled in self.settings.permissions.capability_rows():
            rows.append((permission.name, label, enabled))
        return rows

    def describe_configuration(self) -> str:
        config = self.active_provider_config()
        if config is None:
            return "No provider enabled"
        return f"{config.label} • {config.model or 'no model'} [{config.scope}]"


__all__ = ["AssistantSession", "SLASH_COMMANDS", "SessionState"]
