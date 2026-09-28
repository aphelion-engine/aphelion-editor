"""The AI Assistant panel.

A modern-agent-style surface: a conversation transcript, a streamed reply, an
expandable activity log of every tool call, a provider/model selector with a
LOCAL/CLOUD badge, and Stop / Retry / New chat controls.

The engine runs on a worker thread so the editor stays responsive. Every
visual effect the agent asks for is queued on the host and drained by a timer
on the main thread, so Qt is only ever touched from the GUI thread.
"""

from __future__ import annotations

import html
import threading
import time
from typing import Any

from ai.settings import AISettingsStore
from ai.credentials import CredentialStore
from ai.session import AssistantSession, SLASH_COMMANDS
from ai.types import AgentEvent, AgentEventKind, AgentMode, PendingChanges
from ai.ui.action_view import ActionLogView
from ai.ui.changes_dialog import ChangesPreviewDialog, describe_region_proposal
from ai.ui.editor_host import EditorAgentHost
from PyQt6.QtCore import QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (QComboBox, QCompleter, QFrame, QHBoxLayout,
                             QLabel, QMenu, QMessageBox, QPlainTextEdit,
                             QPushButton, QTextBrowser, QToolButton,
                             QVBoxLayout, QWidget)

#: How often queued UI effects and streamed text are flushed.
_DRAIN_INTERVAL_MS: int = 55
#: Seconds the worker waits for a user decision before declining.
_CONFIRM_TIMEOUT_S: float = 600.0


class PromptEdit(QPlainTextEdit):
    """Input box: Enter sends, Shift+Enter breaks the line, '@' autocompletes."""

    send_requested = pyqtSignal()
    mention_typed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Ask Aphelion…  (@ to mention a node, / for commands)")
        self.setMinimumHeight(58)
        self.setMaximumHeight(140)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802
        if event is None:
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.send_requested.emit()
            return
        super().keyPressEvent(event)

    def text_after_mention(self) -> str | None:
        """Return the partial mention the caret is inside, if any."""
        text = self.toPlainText()
        cursor = self.textCursor().position()
        start = text.rfind("@", 0, cursor)
        if start < 0:
            return None
        chunk = text[start + 1 : cursor]
        if any(character.isspace() for character in chunk):
            return None
        return chunk


class AgentWorker(threading.Thread):
    """Runs one assistant turn off the GUI thread."""

    def __init__(
        self,
        session: AssistantSession,
        text: str,
        *,
        on_event: Any,
        on_finished: Any,
        confirm: Any,
        mode: AgentMode | None = None,
        model: str | None = None,
        retry: bool = False,
    ) -> None:
        super().__init__(daemon=True, name="aphelion-ai-agent")
        self._session = session
        self._text = text
        self._on_event = on_event
        self._on_finished = on_finished
        self._confirm = confirm
        self._mode = mode
        self._model = model
        self._retry = retry

    def run(self) -> None:
        try:
            if self._retry:
                result = self._session.retry(
                    model=self._model,
                    on_event=self._on_event,
                    confirm=self._confirm,
                )
            else:
                result = self._session.send(
                    self._text,
                    on_event=self._on_event,
                    confirm=self._confirm,
                    mode=self._mode,
                )
        except Exception as exc:  # noqa: BLE001 - the worker must never die loudly
            from ai.engine import RunResult

            result = RunResult(error=f"{type(exc).__name__}: {exc}")
        self._on_finished(result)


class AIPanel(QWidget):
    """The dockable assistant panel."""

    #: Emitted from the worker thread; queued onto the GUI thread by Qt.
    _event_received = pyqtSignal(object)
    _run_finished = pyqtSignal(object)
    _confirm_requested = pyqtSignal(object)

    def __init__(
        self,
        editor: Any,
        settings_store: AISettingsStore,
        credentials: CredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.settings_store = settings_store
        self.credentials = credentials or CredentialStore()

        self.host = EditorAgentHost(editor)
        self.session = AssistantSession(
            self.host,
            settings_store.settings,
            credentials=self.credentials,
        )
        self._worker: AgentWorker | None = None
        self._stream_buffer: list[str] = []
        self._streaming_block = False
        self._pending_call: dict[str, Any] = {}
        self._confirm_event: threading.Event | None = None
        self._confirm_result: bool = False
        self._action_times: dict[str, float] = {}

        self._model_cache: list[Any] | None = None

        self._build_ui()
        self._connect_signals()
        self._refresh_provider_selector(force=True)
        self.refresh_state()

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(_DRAIN_INTERVAL_MS)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # The layout is deliberately shallow: a two-line header, the
        # conversation, a collapsed activity strip, the prompt, one footer
        # row. Nothing that can be inferred from the transcript is shown by
        # default, and everything that is shown earns its width, because the
        # panel shares the narrow right sidebar with the Properties dock.
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        root.addLayout(self._build_header())
        root.addWidget(self._build_banner())
        self._controls = self._build_controls()
        root.addWidget(self._controls)

        self._transcript = QTextBrowser()
        self._transcript.setObjectName("AITranscript")
        self._transcript.setOpenExternalLinks(False)
        self._transcript.setMinimumHeight(140)
        root.addWidget(self._transcript, 1)

        self._activity_section = self._build_activity_section()
        root.addWidget(self._activity_section)

        self._input = PromptEdit()
        root.addWidget(self._input)
        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(6)

        title = QLabel("Aphelion AI")
        title_font = QFont(title.font().family(), title.font().pointSize())
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)

        self._scope_label = QLabel("")
        self._scope_label.setObjectName("AIScopeBadge")
        self._scope_label.setToolTip(
            "Whether the selected provider runs on this machine (LOCAL) or "
            "sends data to a remote service (CLOUD)."
        )
        header.addWidget(self._scope_label)
        header.addStretch(1)

        gear = QToolButton()
        gear.setText("⚙")
        gear.setAutoRaise(True)
        gear.setToolTip("AI settings")
        gear.clicked.connect(self.open_settings)
        header.addWidget(gear)
        return header

    def _build_controls(self) -> QWidget:
        """The provider/model picker and the agent mode, on one compact row."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._provider_combo = QComboBox()
        # A hard minimum width here propagates into the dock's own minimum and
        # stops the right sidebar from being dragged narrower, so let the entry
        # elide instead.
        self._provider_combo.setMinimumContentsLength(8)
        self._provider_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._provider_combo.setToolTip("Provider and model for the next message.")
        self._provider_combo.currentIndexChanged.connect(self._on_model_changed)
        layout.addWidget(self._provider_combo, 1)

        self._mode_combo = QComboBox()
        for mode in AgentMode:
            self._mode_combo.addItem(mode.label, mode.value)
        self._mode_combo.setToolTip(
            "Ask: inspect only. Assist: confirm before applying. Agent: apply "
            "directly (still undoable)."
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self._mode_combo)
        return row

    def _build_banner(self) -> QWidget:
        """The "assistant is off" explainer (hidden once AI is enabled)."""
        self._banner = QFrame()
        self._banner.setObjectName("AIBanner")
        layout = QVBoxLayout(self._banner)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        self._banner_label = QLabel("")
        self._banner_label.setWordWrap(True)
        layout.addWidget(self._banner_label)
        self._enable_button = QPushButton("Enable AI…")
        self._enable_button.clicked.connect(self.open_settings)
        layout.addWidget(self._enable_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._banner.setVisible(False)
        return self._banner

    def _build_activity_section(self) -> QWidget:
        """A one-line toggle plus the tool-call tree, collapsed by default."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._activity_toggle = QToolButton()
        self._activity_toggle.setObjectName("AIActivityToggle")
        self._activity_toggle.setCheckable(True)
        self._activity_toggle.setAutoRaise(True)
        self._activity_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._activity_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._activity_toggle.setToolTip("Show every tool call the assistant made")
        self._activity_toggle.toggled.connect(self._on_activity_toggled)
        layout.addWidget(self._activity_toggle)

        self.activity = ActionLogView()
        self.activity.setMinimumHeight(90)
        self.activity.setVisible(False)
        layout.addWidget(self.activity)

        self._activity_count = 0
        self._set_activity_summary()
        return section

    def _on_activity_toggled(self, expanded: bool) -> None:
        self.activity.setVisible(expanded)
        self._activity_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _set_activity_summary(self) -> None:
        count = self._activity_count
        self._activity_toggle.setText(
            "Activity" if not count else f"Activity ({count})"
        )
        # Nothing to disclose until the assistant has actually called a tool.
        self._activity_toggle.setVisible(count > 0)

    def _reset_activity(self) -> None:
        """Clear the tool log and collapse it for a fresh turn."""
        self._activity_count = 0
        self.activity.clear()
        self._pending_call.clear()
        self._action_times.clear()
        self._activity_toggle.setChecked(False)
        self._set_activity_summary()

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(6)

        self._status = QLabel("Ready")
        self._status.setObjectName("AIHint")
        # Status text can be long ("Not permitted: …"). Word wrapping keeps the
        # label's minimum width down to its longest word, because the panel
        # shares the sidebar with the Properties dock.
        self._status.setWordWrap(True)
        self._status.setMinimumWidth(0)
        footer.addWidget(self._status, 1)

        # Secondary actions live behind one overflow button so the footer stays
        # two buttons wide and the sidebar stays resizable.
        self._overflow = QToolButton()
        self._overflow.setText("⋯")
        self._overflow.setAutoRaise(True)
        self._overflow.setToolTip("More")
        menu = QMenu(self._overflow)
        self._new_chat_action = menu.addAction("New chat")
        self._new_chat_action.triggered.connect(self.new_conversation)
        self._retry_action = menu.addAction("Retry last request")
        self._retry_action.setEnabled(False)
        self._retry_action.triggered.connect(lambda: self.retry())
        menu.addSeparator()
        self._context_action = menu.addAction("Show AI context…")
        self._context_action.setToolTip(
            "Which source files and schemas were retrieved, redactions, and "
            "whether the provider was local or remote."
        )
        self._context_action.triggered.connect(self.show_context_audit)
        self._overflow.setMenu(menu)
        self._overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        footer.addWidget(self._overflow)

        self._stop_button = QPushButton("Stop")
        self._stop_button.setEnabled(False)
        self._stop_button.setVisible(False)
        self._stop_button.clicked.connect(self.stop)
        footer.addWidget(self._stop_button)

        self._send_button = QPushButton("Send")
        self._send_button.setDefault(True)
        self._send_button.clicked.connect(self.send_message)
        footer.addWidget(self._send_button)
        return footer

    def _connect_signals(self) -> None:
        self._input.send_requested.connect(self.send_message)
        self._input.textChanged.connect(self._on_input_changed)
        self._event_received.connect(self._on_event)
        self._run_finished.connect(self._on_run_finished)
        self._confirm_requested.connect(self._on_confirm_requested)

        self._mention_model = QStringListModel(self)
        self._mention_labels: list[str] = []
        self._mention_ids: list[str] = []
        self._mention_completer = QCompleter(self._mention_model, self)
        self._mention_completer.setWidget(self._input)
        self._mention_completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self._mention_completer.activated.connect(self._insert_mention)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def refresh_state(self, *, refresh_models: bool = False) -> None:
        """Sync the panel with the current settings.

        Listing models hits the network on providers that support it, so it is
        only done when the user actually changes providers rather than on every
        incidental settings edit.
        """
        settings = self.settings_store.settings
        self.session.settings = settings

        index = self._mode_combo.findData(settings.agent_mode.value)
        if index >= 0:
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(index)
            self._mode_combo.blockSignals(False)

        enabled = settings.enabled
        self._input.setEnabled(enabled)
        self._send_button.setEnabled(enabled)
        self._stop_button.setVisible(enabled and self.session.state.busy)
        self._mode_combo.setEnabled(enabled)
        self._provider_combo.setEnabled(enabled)
        # The provider/mode row and the activity strip only exist to serve a
        # live conversation, so an off assistant shows neither.
        self._controls.setVisible(enabled)
        self._activity_section.setVisible(enabled)
        self._banner.setVisible(not enabled)
        if not enabled:
            self._banner_label.setText(
                "The AI assistant is off. Nothing about your project is read or "
                "sent until you enable it and configure a provider."
            )
            self._status.setText("Disabled")
        else:
            blocked = [
                label
                for _name, label, allowed in settings.permissions.capability_rows()
                if not allowed
            ]
            if blocked:
                self._status.setText("Not permitted: " + ", ".join(blocked[:3]))
            else:
                self._status.setText("Ready")
        self._refresh_provider_selector(force=refresh_models)

    def _refresh_provider_selector(self, *, force: bool = False) -> None:
        if force or self._model_cache is None:
            self._model_cache = self.session.available_models()
        models = self._model_cache or []
        active_config = self.session.active_provider_config()
        active_id = active_config.provider_id if active_config else ""
        active_model = active_config.model if active_config else ""

        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        seen: set[tuple[str, str]] = set()
        for info in models:
            key = (info.provider_id, info.model_id)
            if key in seen:
                continue
            seen.add(key)
            label = f"{info.provider_id} • {info.model_id or 'no model'}"
            self._provider_combo.addItem(label, key)
        if not models and active_config is not None:
            self._provider_combo.addItem(
                f"{active_config.provider_id} • {active_config.model or 'no model'}",
                (active_config.provider_id, active_config.model),
            )
        target = (active_id, active_model)
        index = self._provider_combo.findData(target)
        if index >= 0:
            self._provider_combo.setCurrentIndex(index)
        self._provider_combo.blockSignals(False)

        scope = self.session.provider_scope()
        self._scope_label.setText(scope)
        self._scope_label.setProperty("scope", scope)
        if scope == "LOCAL":
            self._scope_label.setToolTip(
                "The selected provider runs on this machine. No project data "
                "leaves it."
            )
        elif scope == "CLOUD":
            self._scope_label.setToolTip(
                "The selected provider is remote. Only the context you permitted "
                "is sent."
            )

    def _on_mode_changed(self, index: int) -> None:
        """Persist the agent mode the user picked in the header."""
        value = self._mode_combo.itemData(index)
        try:
            mode = AgentMode(value)
        except ValueError:
            return
        settings = self.settings_store.settings
        if mode is settings.agent_mode:
            return
        # Switching *into* full Agent mode is the one transition the design
        # insists on making explicit, so confirm it rather than assume.
        if mode is AgentMode.AGENT and not self._confirm_agent_mode():
            self._select_mode(settings.agent_mode)
            return
        settings.agent_mode = mode
        self.settings_store.save()
        self.session.settings = settings
        self._status.setText(f"{mode.label} mode")

    def _on_model_changed(self, index: int) -> None:
        """Remember the provider/model the user picked for the next message."""
        data = self._provider_combo.itemData(index)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        provider_id, model_id = data
        settings = self.settings_store.settings
        config = settings.provider(provider_id)
        if config is None:
            return
        changed = False
        if settings.default_provider_id != provider_id:
            settings.default_provider_id = provider_id
            changed = True
        if model_id and config.model != model_id:
            config.model = model_id
            changed = True
        if not changed:
            return
        self.settings_store.save()
        self.session.settings = settings
        # Re-derive the LOCAL/CLOUD badge for the newly selected provider.
        self._refresh_provider_selector(force=False)

    def _select_mode(self, mode: AgentMode) -> None:
        index = self._mode_combo.findData(mode.value)
        if index < 0:
            return
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(index)
        self._mode_combo.blockSignals(False)

    def _confirm_agent_mode(self) -> bool:
        answer = QMessageBox.warning(
            self,
            "Enable Agent mode",
            "Agent mode lets the assistant edit your project directly instead "
            "of proposing changes first.\n\nEvery AI edit is a single undoable "
            "step, so Ctrl+Z still reverts it.\n\nEnable Agent mode?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _set_busy(self, busy: bool) -> None:
        self.session.state.busy = busy
        self._send_button.setEnabled(not busy and self.settings_store.settings.enabled)
        # Stop exists only while there is something to stop.
        self._stop_button.setEnabled(busy)
        self._stop_button.setVisible(busy)
        self._retry_action.setEnabled(not busy and self._can_retry())
        self._input.setEnabled(not busy and self.settings_store.settings.enabled)
        if busy:
            self._status.setText("Working…")

    def _can_retry(self) -> bool:
        return any(turn.role == "user" for turn in self.session.turns)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def send_message(self) -> None:
        text = self._input.toPlainText().strip()
        if not text or self._worker is not None:
            return
        self._input.clear()
        self._append_user(text)
        self._activity_divider()
        self._reset_activity()
        self._set_busy(True)
        self._start_worker(AgentWorker(
            self.session,
            text,
            on_event=self._emit_event,
            on_finished=self._emit_finished,
            confirm=self._confirm_from_worker,
        ))

    def retry(self) -> None:
        if self._worker is not None or not self._can_retry():
            return
        self._set_busy(True)
        self._start_worker(AgentWorker(
            self.session,
            "",
            on_event=self._emit_event,
            on_finished=self._emit_finished,
            confirm=self._confirm_from_worker,
            retry=True,
        ))

    def stop(self) -> None:
        """Cancel generation and any further tool execution."""
        self.session.request_stop()
        self._status.setText("Stopping…")
        self._stop_button.setEnabled(False)

    def new_conversation(self) -> None:
        if self._worker is not None:
            self.stop()
        self.session.start_new_conversation()
        self._transcript.clear()
        self._reset_activity()
        self._status.setText("Ready")
        self._set_busy(False)

    def show_context_audit(self) -> None:
        """Open the "what did the AI actually see" report."""
        from ai.ui.context_view import ContextAuditDialog

        dialog = ContextAuditDialog(self, status=self.session.source_status())
        dialog.exec()

    def open_settings(self) -> None:
        from ai.ui.ai_settings_dialog import AISettingsDialog

        dialog = AISettingsDialog(self.settings_store, self.credentials, self)
        if dialog.exec() == AISettingsDialog.DialogCode.Accepted:
            # The user just edited providers, so re-listing models is expected.
            self.on_settings_changed(refresh_models=True)

    def on_settings_changed(self, *, refresh_models: bool = False) -> None:
        """Called when AI settings change elsewhere (e.g. the Preferences tab)."""
        self.session.settings = self.settings_store.settings
        self.refresh_state(refresh_models=refresh_models)

    # ------------------------------------------------------------------
    # Worker plumbing
    # ------------------------------------------------------------------

    def _start_worker(self, worker: AgentWorker) -> None:
        self._worker = worker
        worker.start()

    def _emit_event(self, event: AgentEvent) -> None:
        # Called on the worker thread: hand off to the GUI thread.
        self._event_received.emit(event)

    def _emit_finished(self, result: Any) -> None:
        self._run_finished.emit(result)

    def _drain(self) -> None:
        self.host.drain()
        if self._stream_buffer:
            fragment = "".join(self._stream_buffer)
            self._stream_buffer.clear()
            self._append_stream(fragment)

    def _confirm_from_worker(
        self,
        pending: PendingChanges,
        _transaction: Any,
    ) -> bool:
        """Block the worker until the GUI thread decides.

        The transaction itself is never resolved here — the engine owns commit
        and rollback. This only answers "may I proceed?".
        """
        # The engine only asks when the user's policy or mode requires a
        # decision, so anything that reaches here genuinely needs one.
        self._confirm_event = threading.Event()
        self._confirm_result = False
        self._confirm_requested.emit(pending)
        self._confirm_event.wait(timeout=_CONFIRM_TIMEOUT_S)
        approved = self._confirm_result
        self._confirm_event = None
        return approved

    def _on_confirm_requested(self, pending: PendingChanges) -> None:
        """GUI-thread slot: show the preview and release the worker."""
        dialog = ChangesPreviewDialog(pending, self)
        dialog.exec()
        self._confirm_result = bool(dialog.approved)
        if self._confirm_event is not None:
            self._confirm_event.set()

    def _on_run_finished(self, result: Any) -> None:
        self._worker = None
        self._flush_stream()
        if getattr(result, "error", ""):
            self._append_system_note(f"Error: {result.error}")
            self._status.setText("Failed — see the note above")
        elif getattr(result, "cancelled", False):
            self._status.setText("Stopped")
        elif getattr(result, "rolled_back", False):
            self._status.setText("Changes rejected")
        elif getattr(result, "committed", False):
            count = len(getattr(result, "changed_node_ids", []) or [])
            self._status.setText(
                f"Applied ({count} node(s) touched) — Ctrl+Z to undo"
                if count
                else "Applied — Ctrl+Z to undo"
            )
        else:
            self._status.setText("Ready")
        self._set_busy(False)
        self.session.persist()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_event(self, event: AgentEvent) -> None:
        kind = event.kind
        if kind is AgentEventKind.TEXT:
            if event.text:
                self._stream_buffer.append(event.text)
            return
        if kind is AgentEventKind.STATUS:
            self._flush_stream()
            self._status.setText(event.text or "Working…")
            return
        if kind is AgentEventKind.TOOL_START and event.tool_call is not None:
            self._flush_stream()
            self._activity_divider()
            self._activity_count += 1
            self._set_activity_summary()
            self.activity.begin_action(event.tool_call)
            self._action_times[event.tool_call.call_id or event.tool_call.name] = (
                time.perf_counter()
            )
            self._pending_call[event.tool_call.call_id or event.tool_call.name] = (
                event.tool_call
            )
            return
        if kind is AgentEventKind.TOOL_RESULT and event.tool_result is not None:
            keys = []
            if event.tool_call is not None:
                keys.extend(
                    [event.tool_call.call_id, event.tool_call.name]
                )
            call = None
            for key in keys:
                if key and key in self._pending_call:
                    call = self._pending_call.pop(key)
                    break
            if call is None and self._pending_call:
                # Fall back to the oldest outstanding call for the same name.
                call = next(iter(self._pending_call.values()))
                self._pending_call.clear()
            duration = None
            if call is not None:
                started = self._action_times.pop(
                    call.call_id or call.name, None
                )
                if started is not None:
                    duration = (time.perf_counter() - started) * 1000.0
            self._flush_stream()
            self.activity.finish_action(call, event.tool_result, duration_ms=duration)
            self._append_action(event.tool_result)
            return
        if kind is AgentEventKind.VALIDATION:
            self._flush_stream()
            self.activity.add_status(event.text)
            return
        if kind is AgentEventKind.PENDING_CHANGES:
            self._flush_stream()
            return
        if kind is AgentEventKind.ERROR:
            self._flush_stream()
            self._append_system_note(event.text)
            return
        if kind is AgentEventKind.DONE:
            self._flush_stream()
            return

    # ------------------------------------------------------------------
    # Transcript rendering
    # ------------------------------------------------------------------

    def _activity_divider(self) -> None:
        """Visual separator between a user turn and the agent's work."""
        return None

    def _append_html(self, markup: str) -> None:
        self._transcript.append(markup)

    def _append_user(self, text: str) -> None:
        self._append_html(
            f'<div style="margin:12px 0 2px 0;"><b>You</b></div>'
            f'<div style="color:#e8ecf1;">'
            f'{html.escape(text).replace(chr(10), "<br>")}</div>'
        )
        self._scroll_to_end()

    def _start_stream_block(self) -> None:
        """Open a fresh, unbolded paragraph for streamed reply text."""
        if self._streaming_block:
            return
        self._append_html('<div style="margin:12px 0 2px 0;"><b>Aphelion AI</b></div>')
        # Streamed fragments are inserted straight into the document, so give
        # them their own block and an explicit normal-weight character format
        # rather than inheriting the bold header's format.
        cursor = self._transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        self._streaming_block = True

    def _append_stream(self, fragment: str) -> None:
        if not fragment:
            return
        self._start_stream_block()
        cursor = self._transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        char_format = QTextCharFormat()
        char_format.setFontWeight(QFont.Weight.Normal)
        char_format.setForeground(Qt.GlobalColor.white)
        cursor.setCharFormat(char_format)
        cursor.insertText(fragment)
        self._scroll_to_end()

    def _flush_stream(self) -> None:
        if self._stream_buffer:
            fragment = "".join(self._stream_buffer)
            self._stream_buffer.clear()
            self._append_stream(fragment)
        self._streaming_block = False

    def _append_action(self, result: Any) -> None:
        mark = "✓" if result.ok else "✕"
        color = "#7ed994" if result.ok else "#f08c8c"
        self._append_html(
            f'<div style="margin:2px 0 2px 14px;color:{color};">'
            f"{mark} {html.escape(result.summary)}</div>"
        )
        self._scroll_to_end()

    def _append_system_note(self, text: str) -> None:
        self._append_html(
            '<div style="margin:6px 0;padding:6px 8px;background:#3a2a2a;'
            f'color:#f0c0c0;">{html.escape(text)}</div>'
        )
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        bar = self._transcript.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------

    def _on_input_changed(self) -> None:
        prefix = self._input.text_after_mention()
        if prefix is None:
            if self._mention_completer.popup().isVisible():
                self._mention_completer.popup().hide()
            return
        candidates = self.session.mention_candidates(prefix)
        self._mention_labels = [f"{name}  ({node_id})" for node_id, name in candidates]
        self._mention_ids = [node_id for node_id, _name in candidates]
        self._mention_model.setStringList(self._mention_labels)
        self._mention_completer.setCompletionPrefix(prefix)
        if self._mention_labels and prefix != "":
            popup = self._mention_completer.popup()
            rect = self._input.cursorRect()
            rect.setWidth(
                self._mention_completer.popup().sizeHintForColumn(0)
                + self._mention_completer.popup().verticalScrollBar().sizeHint().width()
                + 24
            )
            self._mention_completer.complete(rect)

    def _insert_mention(self, label: str) -> None:
        try:
            index = self._mention_labels.index(label)
        except ValueError:
            return
        node_id = self._mention_ids[index]
        text = self._input.toPlainText()
        cursor = self._input.textCursor()
        position = cursor.position()
        start = text.rfind("@", 0, position)
        if start < 0:
            return
        cursor.setPosition(start)
        cursor.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(f"@{node_id} ")
        self._input.setTextCursor(cursor)

    # ------------------------------------------------------------------
    # External hooks
    # ------------------------------------------------------------------

    def focus_input(self) -> None:
        self._input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def shutdown(self) -> None:
        """Stop timers and cancel any in-flight run before the editor closes."""
        self._drain_timer.stop()
        self.session.request_stop()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=2.0)
        self._worker = None
        if self._confirm_event is not None:
            self._confirm_result = False
            self._confirm_event.set()
        self.host.drain()

    def append_region_proposal(self, proposal: dict[str, Any]) -> None:
        """Show a vision region proposal in the transcript."""
        self._append_html(
            '<div style="margin:4px 0 4px 14px;color:#8fd0ff;">'
            f"Proposed region — {html.escape(describe_region_proposal(proposal))}"
            "</div>"
        )
        self._scroll_to_end()

    def slash_commands(self) -> list[str]:
        return list(SLASH_COMMANDS)


__all__ = ["AIPanel", "AgentWorker", "PromptEdit"]
