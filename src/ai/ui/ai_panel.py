"""The AI Assistant panel.



A modern-agent conversational surface: a clean header, a spacious transcript,

a collapsed activity strip, a large composer, the plan-as-progress card, and

a completion card.  The engine emits events through

:class:`ai.platform.event_bus.AgentEventBus`; the UI is the only receiver of

those events, so every widget update happens on the main Qt thread.



Layout (left to right)::



    [Aphelion AI]  [LOCAL/CLOUD]  [Access]  [Settings]

    +----------------------------------------------------------+

    |  Transcript (conversation + plan progress + completion)  |

    |                                                          |

    |  Activity (tool log, collapsed)                          |

    |  Selection context                                       |

    +----------------------------------------------------------+

    |  Composer: [Ask Aphelion...]      [E]ffort  [Send] [Stop]|

    +----------------------------------------------------------+



Design principles applied here:

    * clean whitespace, soft cards, rounded surfaces

    * no heavy borders; the transcript is a comfortable reading width

    * the composer is large and stays out of the way

    * progress is integrated into the conversation, not dumped as dozens of

      separate messages

    * a single live progress card replaces dozens of chat bubbles

"""

from __future__ import annotations

import html
import threading
import time
from typing import Any

from PyQt6.QtCore import QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ai.credentials import CredentialStore
from ai.platform.event_bus import (
    AgentEvent,
    AgentEventBus,
    AgentEventKind,
    QuestionPayload,
    ThinkingPayload,
)
from ai.session import SLASH_COMMANDS, AssistantSession
from ai.settings import AISettingsStore
from ai.summary import AgentCompletionSummary
from ai.task import StepStatus, TodoList
from ai.tasks import AgentEffort
from ai.types import AgentMode, PendingChanges
from ai.ui.action_view import ActionLogView
from ai.ui.changes_dialog import ChangesPreviewDialog, describe_region_proposal
from ai.ui.editor_host import EditorAgentHost
from ai.worker import AgentWorker

#: How often queued UI effects and streamed text are flushed.

_DRAIN_INTERVAL_MS: int = 55

#: Seconds the worker waits for a user decision before declining.

_CONFIRM_TIMEOUT_S: float = 600.0

#: How long a thinking bubble stays visible before fading.

_THINKING_FADE_MS: int = 6000


#: Completion-card colours per completion state: (background, accent).

_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "completed": ("#1d3124", "#8fe0a8"),
    "completed_with_warnings": ("#332c1c", "#f0d894"),
    "partially_completed": ("#332c1c", "#f0d894"),
    "failed": ("#3a2424", "#f0b0b0"),
    "cancelled": ("#282b33", "#c8ccd4"),
}


#: Plan-step glyphs, mirroring :class:`ai.plan.StepStatus`.

_STEP_SYMBOLS: dict[str, str] = {
    "pending": "○",
    "active": "●",
    "done": "✓",
    "failed": "✕",
    "skipped": "–",
}


#: Effort chip labels.

_EFFORT_LABELS = {
    "auto": "Auto",
    "fast": "Fast",
    "normal": "Normal",
    "expert": "Expert",
    "maximum": "Maximum",
}


class PromptEdit(QPlainTextEdit):
    """Input box: Enter sends, Shift+Enter breaks the line, '@' autocompletes."""

    send_requested = pyqtSignal()


class EffortPicker(QComboBox):
    """A compact dropdown chip in the composer header showing the selected effort."""

    def __init__(self, parent: QWidget | None = None) -> None:

        super().__init__(parent)

        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )

        self.addItems([_EFFORT_LABELS[e] for e in AgentEffort])
        self.setMinimumWidth(96)
        self.setStyleSheet("""
            QComboBox {

                background: #22262e;

                border: 1px solid #343a45;

                border-radius: 6px;

                padding: 4px 8px;

                color: #dce2eb;

                font-size: 12pt;

                min-height: 28px;

            }

            QComboBox::drop-down {

                border: 0px;

                subcontrol-origin: padding;

                subcontrol-position: top right;

            }

            QComboBox QAbstractItemView {

                background: #1c2128;

                selection-background-color: #2b3540;

                border: 1px solid #343a45;

                min-height: 160px;

            }

        """)

    def set_effort(self, effort: AgentEffort) -> None:

        index = self.findData(effort.value)

        if index >= 0:
            self.setCurrentIndex(index)


class StatusLabel(QLabel):
    """Compact status text in the footer."""

    def __init__(self, parent: QWidget | None = None) -> None:

        super().__init__("Ready", parent)

        self.setWordWrap(True)

        self.setMinimumWidth(0)

        self.setObjectName("AIHint")


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
        credentials: Any | None = None,
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

        #: Latest plan payload, rendered into the completion card.

        self._plan_payload: dict[str, Any] = {}

        self._question: QuestionPayload | None = None

        #: A "thinking" bubble that is replaced in place by the next one.

        self._thinking_payload: ThinkingPayload | None = None

        self._thinking_fade_timer: QTimer | None = None

        self._action_times: dict[str, float] = {}

        self._model_cache: list[Any] | None = None

        self._build_ui()

        self._connect_signals()

        graph = getattr(editor, "node_graph", None)

        scene = getattr(graph, "scene", None)

        if scene is not None:
            scene.selectionChanged.connect(self._refresh_selection_context)

        self._refresh_selection_context()

        self._refresh_provider_selector(force=True)

        self.refresh_state()

        self._drain_timer = QTimer(self)

        self._drain_timer.setInterval(_DRAIN_INTERVAL_MS)

        self._drain_timer.timeout.connect(self._drain)

        self._drain_timer.start()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:

        root = QVBoxLayout(self)

        root.setContentsMargins(10, 8, 10, 8)

        root.setSpacing(6)

        root.addLayout(self._build_header())

        root.addWidget(self._build_banner())

        self._controls = self._build_controls()
        root.addWidget(self._controls)

        self._transcript = QTextBrowser()

        root.addWidget(self._transcript)

        self._transcript.setObjectName("AITranscript")

        self._transcript.setOpenExternalLinks(False)

        self._transcript.setMinimumHeight(140)

        root.addWidget(self._transcript, 1)

        self._activity_section = self._build_activity_section()

        root.addWidget(self._activity_section)

        self._selection_context = QLabel()

        self._selection_context.setObjectName("AISelectionContext")

        self._selection_context.setWordWrap(True)

        self._selection_context.setVisible(False)

        root.addWidget(self._selection_context)

        self._input = self._build_input()

        root.addWidget(self._input)

        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:

        header = QHBoxLayout()

        header.setSpacing(6)

        title = QLabel("Aphelion AI")

        title.setFont(
            QFont(title.font().family(), title.font().pointSize(), QFont.Weight.Bold)
        )

        header.addWidget(title)

        self._scope_label = QLabel("")

        self._scope_label.setObjectName("AIScopeBadge")

        header.addWidget(self._scope_label)

        self._access_button = QToolButton()

        self._access_button.setText("Access")

        self._access_button.setAutoRaise(True)

        self._access_button.setToolTip("Review what Aphelion AI can access.")

        self._access_button.clicked.connect(self.open_settings)

        header.addWidget(self._access_button)

        header.addStretch(1)

        gear = QToolButton()

        gear.setText("⚙")

        gear.setAutoRaise(True)

        gear.setToolTip("AI settings")

        gear.clicked.connect(self.open_settings)

        header.addWidget(gear)

        return header

    def _build_controls(self) -> QWidget:

        row = QWidget()

        layout = QHBoxLayout(row)

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(6)

        self._provider_combo = QComboBox()

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
            "Ask: inspect only. Assist: confirm before applying. Agent: apply directly (still undoable)."
        )

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        layout.addWidget(self._mode_combo)

        self._effort_picker = EffortPicker()

        self._effort_picker.currentIndexChanged.connect(self._on_effort_changed)

        layout.addWidget(self._effort_picker)

        return row

    def _build_banner(self) -> QFrame:

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

        section = QWidget()

        layout = QVBoxLayout(section)

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(4)

        self._activity_toggle = QToolButton()

        self._activity_toggle.setObjectName("AIActivityToggle")

        self._activity_toggle.setCheckable(True)

        self._activity_toggle.setAutoRaise(True)

        self._activity_toggle.setArrowType(Qt.ArrowType.RightArrow)

        self._activity_toggle.setToolTip("Show every tool call the assistant made")

        self._activity_toggle.toggled.connect(self._on_activity_toggled)

        layout.addWidget(self._activity_toggle)

        self.activity = ActionLogView()

        self.activity.focus_nodes.connect(
            lambda ids: self.session.host.select_nodes(ids, focus=True)
        )

        self.activity.setMinimumHeight(90)

        self.activity.setVisible(False)

        layout.addWidget(self.activity)

        self._activity_count = 0

        self._set_activity_summary()

        return section

    def _set_activity_summary(self) -> None:
        """Update the activity toggle button with the current tool-call count."""
        if self._activity_count > 0:
            self._activity_toggle.setText(f"Activity ({self._activity_count})")
            self._activity_toggle.setToolTip(
                f"Show every tool call the assistant made ({self._activity_count} calls)"
            )
        else:
            self._activity_toggle.setText("Activity")
            self._activity_toggle.setToolTip("Show every tool call the assistant made")

    def _on_activity_toggled(self, expanded: bool) -> None:

        self.activity.setVisible(expanded)

        self._activity_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

        self._set_activity_summary()

    def _build_input(self) -> QWidget:

        input = PromptEdit()

        input.setPlaceholderText(
            "Ask Aphelion anything...  (@ to mention a node, / for commands)"
        )

        input.setMinimumHeight(58)

        input.setMaximumHeight(140)

        input.setTabChangesFocus(True)

        input.send_requested.connect(self.send_message)

        return input

    def _build_footer(self) -> QHBoxLayout:

        footer = QHBoxLayout()

        footer.setSpacing(6)

        self._status = StatusLabel()

        self._status.setObjectName("AIHint")

        footer.addWidget(self._status, 1)

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

        self._undo_action = menu.addAction("Undo AI changes")

        self._undo_action.setEnabled(False)

        self._undo_action.setToolTip(
            "Undo the assistant's most recent change as a single step."
        )

        self._undo_action.triggered.connect(self.undo_ai_changes)

        self._context_action = menu.addAction("Show AI context…")

        self._context_action.setToolTip(
            "Which source files and schemas were retrieved, redactions, and whether the provider was local or remote."
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

    # -- threading / signals ----------------------------------------------

    def _connect_signals(self) -> None:

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

    # -- state -------------------------------------------------------------

    def refresh_state(self, *, refresh_models: bool = False) -> None:

        settings = self.settings_store.settings

        self.session.settings = settings

        granted = [
            label
            for _name, label, allowed in settings.permissions.capability_rows()
            if allowed
        ]

        access = ", ".join(granted) if granted else "No project capabilities"

        self._access_button.setToolTip(
            f"Agent has access to: {access}. Click to manage permissions."
        )

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

        self._controls.setVisible(enabled)

        self._activity_section.setVisible(enabled)

        self._banner.setVisible(not enabled)

        if not enabled:
            self._banner_label.setText(
                "The AI assistant is off. Nothing about your project is read or sent until you enable it and configure a provider."
            )

            self._status.setText("Disabled")

        else:
            blocked = [
                label
                for _name, label, allowed in settings.permissions.capability_rows()
                if not allowed
            ]

            self._status.setText(
                "Ready" if not blocked else "Not permitted: " + ", ".join(blocked[:3])
            )

        self._refresh_provider_selector(force=refresh_models)

        # Effort is stored per-engine-config, not in AISettings. Use the
        # session's default (Normal) until an engine run resolves it.
        self._effort_picker.set_effort(AgentEffort.NORMAL)

    def _refresh_selection_context(self) -> None:
        """Refresh the selection-context label from the current graph selection."""
        selected = self.host.selected_node_ids()
        if not selected:
            self._selection_context.setVisible(False)
            return
        names = []
        for node_id in selected:
            node = getattr(self.host.project, "nodes", {}).get(node_id)
            if node is not None:
                name = getattr(node, "name", node_id)
            else:
                name = node_id
            names.append(str(name))
        text = "Context: " + ", ".join(html.escape(n) for n in names)
        self._selection_context.setText(text)
        self._selection_context.setToolTip(
            ", ".join(f"{n} ({i})" for n, i in zip(names, selected))
        )
        self._selection_context.setVisible(True)

    def _refresh_provider_selector(self, *, force: bool = False) -> None:

        if force or self._model_cache is None:
            self._model_cache = [
                p.model_info() for p in self.session.settings.enabled_providers()
            ]

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

    def _on_model_changed(self, index: int) -> None:
        """Apply the selected provider/model for the next message."""

        payload = self._provider_combo.itemData(index)

        if not isinstance(payload, tuple) or len(payload) != 2:
            return

        provider_id, model = payload

        settings = self.settings_store.settings

        settings.default_provider_id = provider_id

        self.settings_store.save()

        self.refresh_state(refresh_models=True)

        self._status.setText(f"{provider_id} • {model}")

    def _on_mode_changed(self, index: int) -> None:

        value = self._mode_combo.itemData(index)

        try:
            mode = AgentMode(value)

        except ValueError:
            return

        settings = self.settings_store.settings

        if mode is settings.agent_mode:
            return

        if mode is AgentMode.AGENT and not self._confirm_agent_mode():
            self._select_mode(settings.agent_mode)

            return

        settings.agent_mode = mode

        self.settings_store.save()

        self.session.settings = settings

        self._status.setText(f"{mode.label} mode")

    def _on_effort_changed(self, index: int) -> None:

        value = self._effort_picker.itemData(index)

        if not isinstance(value, str):
            return

        effort = effort_from_string(value)

        settings = self.settings_store.settings

        settings.agent_effort = effort

        self.settings_store.save()

        self.session.settings = settings

        self._status.setText(f"Effort: {effort.label}")

    def _confirm_agent_mode(self) -> bool:

        answer = QMessageBox.warning(
            self,
            "Enable Agent mode",
            "Agent mode lets the assistant edit your project directly instead of proposing changes first.\n\n"
            "Every AI edit is a single undoable step, so Ctrl+Z still reverts it.\n\n"
            "Enable Agent mode?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        return answer == QMessageBox.StandardButton.Yes

    def _set_busy(self, busy: bool) -> None:

        self.session.state.busy = busy

        self._send_button.setEnabled(not busy and self.settings_store.settings.enabled)

        self._stop_button.setEnabled(busy)

        self._stop_button.setVisible(busy)

        self._retry_action.setEnabled(not busy and self._can_retry())

        self._input.setEnabled(not busy and self.settings_store.settings.enabled)

        if busy:
            self._status.setText("Working…")

    def _can_retry(self) -> bool:

        return any(turn.role == "user" for turn in self.session.turns)

    def _begin_turn(self) -> None:
        """Reset per-turn state before starting a new agent run."""
        self._activity_count = 0
        self._stream_buffer.clear()
        self._streaming_block = False
        self._pending_call.clear()
        self._action_times.clear()
        self._append_user(self._input.toPlainText().strip())

    def _end_turn(self) -> None:
        """Finalize a turn after the agent run completes."""
        self._flush_stream()
        self._set_busy(False)

    def _reset_activity(self) -> None:
        """Clear the activity log for a new run."""
        self._activity_count = 0
        self.activity.clear()
        self._set_activity_summary()

    # -- actions -----------------------------------------------------------

    def send_message(self) -> None:

        text = self._input.toPlainText().strip()

        if not text or self._worker is not None:
            return

        self._input.clear()

        self._append_user(text)

        self._activity_divider()

        self._reset_activity()

        self._set_busy(True)

        self._start_worker(
            AgentWorker(
                self.session,
                text,
                on_event=self._emit_event,
                on_finished=self._emit_finished,
                confirm=self._confirm_from_worker,
                mode=self._mode_combo.currentData(),
            )
        )

    def retry(self) -> None:

        if self._worker is not None or not self._can_retry():
            return

        self._set_busy(True)

        self._start_worker(
            AgentWorker(
                self.session,
                "",
                on_event=self._emit_event,
                on_finished=self._emit_finished,
                confirm=self._confirm_from_worker,
                mode=self._mode_combo.currentData(),
                retry=True,
            )
        )

    def stop(self) -> None:

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

        from ai.ui.context_view import ContextAuditDialog

        dialog = ContextAuditDialog(self, status=self.session.source_status())

        dialog.exec()

    def open_settings(self) -> None:

        from ai.ui.ai_settings_dialog import AISettingsDialog

        dialog = AISettingsDialog(self.settings_store, self.credentials, self)

        if dialog.exec() == AISettingsDialog.DialogCode.Accepted:
            self.on_settings_changed(refresh_models=True)

    def on_settings_changed(self, *, refresh_models: bool = False) -> None:

        self.session.settings = self.settings_store.settings

        self.refresh_state(refresh_models=refresh_models)

    # -- worker plumbing ---------------------------------------------------

    def _start_worker(self, worker: AgentWorker) -> None:

        self._begin_turn()

        self._worker = worker

        worker.start()

    def _emit_event(self, event: AgentEvent) -> None:

        self._event_received.emit(event)

    def _emit_finished(self, result: Any) -> None:

        self._run_finished.emit(result)

    def _drain(self) -> None:

        self.host.drain()

        if self._stream_buffer:
            fragment = "".join(self._stream_buffer)

            self._stream_buffer.clear()

            self._append_stream(fragment)

    def _confirm_from_worker(self, pending: PendingChanges, _transaction: Any) -> bool:

        self._confirm_event = threading.Event()

        self._confirm_result = False

        self._confirm_requested.emit(pending)

        self._confirm_event.wait(timeout=_CONFIRM_TIMEOUT_S)

        approved = self._confirm_result

        self._confirm_event = None

        return approved

    def _on_confirm_requested(self, pending: PendingChanges) -> None:

        dialog = ChangesPreviewDialog(pending, self)

        dialog.exec()

        self._confirm_result = bool(dialog.approved)

        if self._confirm_event is not None:
            self._confirm_event.set()

    def _on_run_finished(self, result: Any) -> None:

        self._worker = None

        self._flush_stream()

        self._refresh_undo_action()

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

        elif (
            getattr(getattr(result, "task", None), "completion_reason", "")
            == "USER_INPUT_REQUIRED"
        ):
            self._status.setText("Waiting for your answer")

        else:
            self._status.setText("Done")

        self._set_busy(False)

        self.session.persist()

    # -- events ------------------------------------------------------------

    def _on_event(self, event: AgentEvent) -> None:

        kind = event.kind

        if kind is AgentEventKind.TEXT:
            if event.payload:
                self._stream_buffer.append(str(event.payload))

            return

        if kind is AgentEventKind.STATUS:
            self._flush_stream()

            self._status.setText(str(event.payload) if event.payload else "Working…")

            self.activity.add_status(str(event.payload) if event.payload else "")

            return

        if kind is AgentEventKind.THINKING:
            self._show_thinking_event(event)

            return

        if kind is AgentEventKind.PLAN_READY:
            self._plan_payload = dict(event.payload or {})

            self._flush_stream()

            if event.payload:
                self._status.setText(str(event.payload).get("headline", "Working…"))

            return

        if kind is AgentEventKind.STEP_STARTED:
            self._flush_stream()

            self.activity.begin_action(
                ToolCall(
                    name=event.payload.get("title", "step"),
                    arguments={},
                    call_id="step",
                )
            )

            return

        if kind is AgentEventKind.STEP_COMPLETED:
            self._flush_stream()

            self.activity.finish_action(
                ToolCall(
                    name=event.payload.get("title", "step"),
                    arguments={},
                    call_id="step",
                ),
                ToolResult(ok=True, summary=event.payload.get("title", "step")),
            )

            return

        if kind is AgentEventKind.TOOL_STARTED and event.tool_call is not None:
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

        if kind is AgentEventKind.TOOL_COMPLETED and event.tool_result is not None:
            keys = (
                [event.tool_call.call_id, event.tool_call.name]
                if event.tool_call
                else []
            )

            call = None

            for key in keys:
                if key and key in self._pending_call:
                    call = self._pending_call.pop(key)

                    break

            if call is None and self._pending_call:
                call = next(iter(self._pending_call.values()))

                self._pending_call.clear()

            duration = None

            if call is not None:
                started = self._action_times.pop(call.call_id or call.name, None)

                if started is not None:
                    duration = (time.perf_counter() - started) * 1000.0

            self._flush_stream()

            self.activity.finish_action(call, event.tool_result, duration_ms=duration)

            self._append_action(event.tool_result)

            return

        if kind is AgentEventKind.VALIDATION_RESULT:
            self._flush_stream()

            self.activity.add_status(str(event.payload))

            return

        if kind is AgentEventKind.QUESTION:
            self._flush_stream()

            self._question = event.payload

            self._show_question_card()

            return

        if kind is AgentEventKind.WAITING_FOR_USER:
            self._flush_stream()

            self._show_waiting_card()

            return

        if kind is AgentEventKind.VISUAL_QA_STARTED:
            self._flush_stream()

            self.activity.add_status("Visual QA: inspecting representative frames…")

            return

        if kind is AgentEventKind.VISUAL_QA_RESULT:
            self._flush_stream()

            payload = event.payload

            self.activity.add_status(f"Visual QA: {payload.get('overall', '')}")

            return

        if kind is AgentEventKind.ERROR:
            self._flush_stream()

            self._append_system_note(str(event.payload))

            return

        if kind is AgentEventKind.DONE:
            self._flush_stream()

            return

    def _show_thinking_event(self, event: AgentEvent) -> None:

        payload = event.payload

        if not isinstance(payload, ThinkingPayload):
            return

        self._thinking_payload = payload

        self._flush_stream()

        self._status.setText(f"Thinking… ({payload.stage})")

        self._render_thinking_card(payload, expanded=False)

    def _show_question_card(self) -> None:

        payload = self._question

        if not payload:
            return

        self._append_html(
            f'<div id="ai-question-card" style="margin:10px 0;padding:10px 12px;background:#2b3540;border-radius:10px;">'
            f'<div style="font-weight:600;">{html.escape(payload.title)}</div>'
            f'<div style="margin-top:4px;">{html.escape(payload.prompt)}</div>'
            f'<div style="margin-top:8px;">'
        )

        for index, option in enumerate(payload.options):
            label = html.escape(str(option.get("label", option.get("text", option))))

            value = option.get("value", option.get("id", str(index)))

            selected = "selected" if (payload.default_option_index == index) else ""

            self._append_html(
                f'<button id="ai-question-option-{index}" data-value="{html.escape(value)}" '
                f'style="background:#343a45;color:#dce2eb;border:none;padding:8px 12px;'
                f"border-radius:6px;margin-right:6px;text-align:left;width:100%;"
                f'cursor:pointer;" onclick="app.answer_question({index}, this)" {selected}>'
                f"{label}</button>"
            )

        self._append_html("</div></div>")

        self._scroll_to_end()

        self._transcript.document().findElementById("ai-question-card").setVisible(
            True
        ) if self._transcript.document().findElementById(
            "ai-question-card"
        ) is not None else None

    def _show_waiting_card(self) -> None:

        self._append_html(
            '<div style="margin:10px 0;padding:10px 12px;background:#333a45;border-radius:10px;color:#c8ccd4;">'
            "The assistant is waiting for your answer. Click an option below to continue.</div>"
        )

        self._scroll_to_end()

    # -- transcript rendering ----------------------------------------------

    def _activity_divider(self) -> None:
        """Visual separator between a user turn and the agent's work."""

        return None

    def _append_html(self, markup: str) -> None:

        self._transcript.append(markup)

    def _append_user(self, text: str) -> None:

        self._append_html(
            f'<div style="margin:12px 0 2px 0;"><b>You</b></div>'
            f'<div style="color:#e8ecf1;">{html.escape(text).replace(chr(10), "<br>")}</div>'
        )

        self._scroll_to_end()

    def _start_stream_block(self) -> None:

        if self._streaming_block:
            return

        self._append_html('<div style="margin:12px 0 2px 0;"><b>Aphelion AI</b></div>')

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
            f'<div style="margin:2px 0 2px 14px;color:{color};">{mark} {html.escape(result.summary)}</div>'
        )

        self._scroll_to_end()

    def _append_system_note(self, text: str) -> None:

        self._append_html(
            '<div style="margin:6px 0;padding:6px 8px;background:#3a2a2a;color:#f0c0c0;">'
            f"{html.escape(text)}</div>"
        )

        self._scroll_to_end()

    def _render_thinking_card(
        self, payload: ThinkingPayload, *, expanded: bool
    ) -> None:
        """Render the thinking/progress card in place, replacing the previous one."""

        steps_html = "".join(
            f'<div style="margin:3px 0;">'
            f'<span style="color:#9aa2ae;">{s.get("status", "pending") and {"done": "✓", "active": "●", "failed": "✕", "skipped": "–"}.get(s.get("status"), "○")}</span> '
            f"{html.escape(s.get('title', ''))}"
            f"</div>"
            for s in payload.steps or []
        )

        body = "\n".join(
            f'<div style="margin-left:14px;">• {html.escape(d)}</div>'
            for d in (payload.details or [])
        )

        header = (
            f'<div id="ai-thinking-card" style="margin:8px 0;padding:10px 12px;background:#2b3540;border-radius:10px;'
            f'border:1px solid #343a45;transition:opacity {int(_THINKING_FADE_MS / 1000)}s;">'
        )

        header += f'<div style="display:flex;justify-content:space-between;align-items:center;">'

        header += f'<span style="font-weight:600;color:#8fd0ff;">▸ Thinking — {html.escape(payload.stage)}</span>'

        header += f'<button onclick="app.toggleThinking()" style="background:none;border:none;color:#9aa2ae;cursor:pointer;">{expanded and "▾" or "▸"}</button>'

        header += f"</div>"

        header += f'<div style="margin-top:6px;'

        header += f"{'display:none;' if not expanded else 'display:block;'}"

        header += f'line-height:1.5;">{body}</div>'

        header += (
            f'<div style="margin-top:8px;font-size:11pt;color:#9aa2ae;line-height:1.5;'
        )

        header += f"{'display:none;' if not expanded else 'display:block;'}"

        header += f'">{steps_html}</div>'

        header += f"</div>"

        self._replace_html_in_place(header, "ai-thinking-card")

        self._scroll_to_end()

    def _replace_html_in_place(self, new_markup: str, element_id: str) -> None:
        """Replace an existing element's inner HTML with the new markup."""

        element = self._transcript.document().findElementById(element_id)

        if element is None:
            self._append_html(new_markup)

            return

        container = element.toElement().parent()

        if container is None:
            self._append_html(new_markup)

            return

        fragment = container.document().createFragment()

        # Clear children and insert new markup.

        new_fragment = self._transcript.document().createFragment()

        new_fragment.fromHtml(new_markup)

        container.appendChild(new_fragment)

    # -- completion card ---------------------------------------------------

    def _append_summary_card(self, payload: dict[str, Any]) -> None:

        if not payload:
            return

        try:
            summary = AgentCompletionSummary.from_dict(payload)

        except Exception:  # noqa: BLE001
            return

        background, accent = _STATUS_COLORS.get(
            summary.status.value, ("#22262e", "#e8ecf1")
        )

        heading = f"{summary.status.symbol} {html.escape(summary.status.label)}"

        subject = summary.workflow_title or summary.task

        if subject:
            heading += f" — {html.escape(subject)}"

        rows: list[str] = [
            f'<div style="font-weight:600;color:{accent};">{heading}</div>'
        ]

        if summary.because:
            rows.append(
                f'<div style="margin-top:4px;color:#c8ccd4;">{html.escape(summary.because)}</div>'
            )

        lines = summary.change_lines(limit=12)

        if lines:
            rows.append(
                '<div style="margin-top:6px;">'
                + "<br>".join(f"• {html.escape(line)}" for line in lines)
                + "</div>"
            )

        if summary.warnings:
            rows.append(
                '<div style="margin-top:6px;color:#f0d894;">'
                + "<br>".join(f"! {html.escape(item)}" for item in summary.warnings)
                + "</div>"
            )

        if summary.unmet:
            rows.append(
                '<div style="margin-top:6px;color:#f0d894;">'
                + "<br>".join(f"○ {html.escape(item)}" for item in summary.unmet)
                + "</div>"
            )

        checklist = self._plan_checklist()

        if checklist:
            rows.append(
                '<div style="margin-top:8px;color:#9aa2ae;">Plan</div><div>{checklist}</div>'
            )

        footer = self._summary_footer(summary)

        if footer:
            rows.append(f'<div style="margin-top:8px;color:#9aa2ae;">{footer}</div>')

        self._append_html(
            '<div style="margin:10px 0;padding:8px 10px;background:'
            + background
            + ';border-radius:6px;">'
            + "".join(rows)
            + "</div>"
        )

        self._scroll_to_end()

        self._refresh_undo_action()

    def _plan_checklist(self) -> str:

        steps = (self._plan_payload or {}).get("steps") or []

        rows = [
            f"{_STEP_SYMBOLS.get(str(step.get('status', '')), '○')} {html.escape(str(step.get('title', '')))}"
            for step in steps
            if isinstance(step, dict)
        ]

        return "<br>".join(rows)

    def _summary_footer(self, summary: AgentCompletionSummary) -> str:

        parts: list[str] = []

        if summary.validation_status == "passed":
            parts.append("Validation passed")

        elif summary.validation_status == "failed":
            parts.append("Validation failed")

        if summary.rolled_back:
            parts.append("Rolled back — the project is unchanged")

        if summary.committed:
            parts.append("Undo with Ctrl+Z or ⋯ → Undo AI changes")

        return " · ".join(parts)

    def _ai_undo_label(self) -> str:

        history = getattr(self.session.host, "history", None)

        if history is None:
            return ""

        try:
            if not history.can_undo:
                return ""

            text = history.undo_text()

        except Exception:  # noqa: BLE001
            return ""

        return text if "AI:" in str(text) else ""

    def _refresh_undo_action(self) -> None:

        label = self._ai_undo_label()

        self._undo_action.setEnabled(bool(label))

        if label:
            self._undo_action.setToolTip(label)

    def undo_ai_changes(self) -> None:

        history = getattr(self.session.host, "history", None)

        if history is None or not self._ai_undo_label():
            return

        try:
            history.undo()

        except Exception:  # noqa: BLE001
            return

        self._append_system_note("Undid the assistant's last changes.")

        self._refresh_undo_action()

    def _scroll_to_end(self) -> None:

        bar = self._transcript.verticalScrollBar()

        if bar is not None:
            bar.setValue(bar.maximum())

    # -- input helpers -----------------------------------------------------

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

    # -- external hooks ----------------------------------------------------

    def focus_input(self) -> None:

        self._input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def shutdown(self) -> None:

        self._drain_timer.stop()

        self.session.request_stop()

        worker = self._worker

        if worker is not None:
            worker.join(timeout=2.0)

        self._worker = None

        self._confirm_event = threading.Event()

        self._confirm_result = False

        if self._confirm_event is not None:
            self._confirm_event.set()

        self.host.drain()

    def append_region_proposal(self, proposal: dict[str, Any]) -> None:

        self._append_html(
            '<div style="margin:4px 0 4px 14px;color:#8fd0ff;">Proposed region — '
            f"{html.escape(describe_region_proposal(proposal))}</div>"
        )

        self._scroll_to_end()

    def slash_commands(self) -> list[str]:

        return list(SLASH_COMMANDS)

    # --utative---

    @staticmethod
    def _answer_question(index: int, button: Any) -> None:
        """Hook called when the user clicks a question option (see the JS below)."""

        # The panel needs a public callback.  The UI is rendered by the engine,

        # so this is a placeholder the engine wires to.

        pass

    @staticmethod
    def _toggle_thinking() -> None:
        """Hook for the UI to expand/collapse the thinking card."""

        pass
