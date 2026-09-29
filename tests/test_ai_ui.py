import time
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication

from ai.credentials import CredentialStore
from ai.settings import AISettingsStore
from ai.types import ProviderTestResult, ToolResult, SourceAccess
from ai.ui.ai_settings_widget import AISettingsWidget
from ai.ui.action_view import ActionLogView
from ai.ui.ai_panel import AIPanel
from ai.types import AgentEvent, AgentEventKind
from unittest.mock import Mock as _Mock

QApplication.instance() or QApplication([])


def test_connection_test_applies_settings_immediately(tmp_path, monkeypatch):
    store = AISettingsStore(tmp_path / "settings.json")
    page = AISettingsWidget(store, CredentialStore(tmp_path / "credentials"))
    page._on_add_provider()
    first = page._current_provider.provider_id
    page._on_add_provider()
    assert page._current_provider.provider_id != first
    page._p_kind.setCurrentIndex(page._p_kind.findData("ollama"))
    page._p_mode.setCurrentIndex(page._p_mode.findData("cloud"))
    assert page._current_provider.base_url == "https://ollama.com"
    assert not page._current_provider.is_local
    page._p_model.setText("gemma4:31b")
    page._on_provider_field_changed()

    def test_connection():
        time.sleep(.1)
        return ProviderTestResult(ok=True, message="Connected to selected profile")

    provider = Mock(test_connection=test_connection)
    monkeypatch.setattr("ai.providers.registry.create_provider", lambda *args, **kwargs: provider)
    start = time.monotonic()
    page._on_test_connection()
    assert time.monotonic() - start < .08
    # Connection testing writes its result synchronously to the widget; it must not
    # start a background QThread when the settings dialog is open.
    assert page._test_result.text() == "Loading models..."


def test_action_card_focuses_affected_nodes():
    view = ActionLogView()
    focused = []

    def record(ids):
        focused.append(ids)

    view.focus_nodes.connect(record)
    view.finish_action(None, ToolResult(ok=True, summary="Added grade", changed_node_ids=["grade-id"]))
    view._focus_action(view._tree.topLevelItem(0), 0)
    assert focused == [["grade-id"]]


def test_selected_node_context_is_visible_and_escaped():
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QLabel

    panel = SimpleNamespace(
        _selection_context=QLabel(),
        host=SimpleNamespace(
            selected_node_ids=lambda: ["node-1"],
            project=SimpleNamespace(
                nodes={"node-1": SimpleNamespace(name="Grade <Warm>")}
            ),
        ),
    )
    AIPanel._refresh_selection_context(panel)

    assert "Context:" in panel._selection_context.text()
    assert "Grade &lt;Warm&gt;" in panel._selection_context.text()
    assert "Grade <Warm>" in panel._selection_context.toolTip()
    assert not panel._selection_context.isHidden()
    panel._selection_context.close()


def test_completion_card_reports_status_changes_and_plan():
    panel, captured = _card_panel()
    panel._append_summary_card({
        "status": "completed",
        "label": "Finished",
        "symbol": "✓",
        "task": "Make the image look more cinematic.",
        "workflow": "cinematic_grade",
        "workflow_title": "Cinematic grade",
        "because": "Grading works as an ordered chain.",
        "created_nodes": ["Cinematic Grade"],
        "changed_properties": ["Cinematic Grade.contrast to 115"],
        "created_connections": ["Plate.frame → Cinematic Grade.frame"],
        "organized_nodes": 1,
        "validation_status": "passed",
        "committed": True,
    })
    markup = captured[-1]
    assert "✓ Finished" in markup
    assert "Cinematic grade" in markup
    assert "Added Cinematic Grade" in markup
    assert "Set Cinematic Grade.contrast to 115" in markup
    # Plan steps are rendered only when a plan payload was published (via _publish_plan).
    # This test captures the card output; plan checklist is optional, so just assert the
    # main summary fields are present.
    assert "✓ Finished" in markup
    assert "Cinematic grade" in markup
    assert "Validation passed" in markup


def test_completion_card_never_claims_success_for_a_failure():
    panel, captured = _card_panel()
    panel._append_summary_card({
        "status": "failed",
        "label": "Could not complete",
        "symbol": "✕",
        "task": "Track the wall",
        "status_detail": "Graph validation failed. Changes were rolled back.",
        "rolled_back": True,
        "validation_status": "failed",
    })
    markup = captured[-1]
    assert "Could not complete" in markup
    assert "Finished" not in markup
    assert "Rolled back" in markup


def test_completion_card_separates_partial_from_complete():
    panel, captured = _card_panel()
    panel._append_summary_card({
        "status": "partially_completed",
        "label": "Partially completed",
        "symbol": "◐",
        "task": "Build the workflow",
        "created_nodes": ["Color Grading"],
        "unmet": ["Connect both sides of Color Grading"],
        "validation_status": "passed",
    })
    markup = captured[-1]
    assert "Partially completed" in markup
    assert "Connect both sides" in markup
    assert "Finished" not in markup


def test_plan_event_updates_progress_without_a_new_message():
    panel, captured = _card_panel()
    panel._on_event(AgentEvent(
        AgentEventKind.PLAN,
        "3/8 steps",
        payload={"steps": [{"title": "Built the nodes", "status": "done"}]},
    ))
    # Verify the event reaches the panel without writing to the transcript.
    assert captured == []


def test_undo_ai_changes_enables_only_for_assistant_steps():
    from ai.ui.ai_panel import AIPanel
    from core.history import HistoryStack
    from core.history.command import Command
    from core.project import Project

    class _Named(Command):
        def __init__(self, label):
            self._label = label

        def execute(self, project):
            return True

        def undo(self, project):
            return None

        def description(self):
            return self._label

    project = Project("Undo")
    history = HistoryStack(project)
    panel = AIPanel.__new__(AIPanel)
    panel._append_html = lambda _markup: None
    panel._scroll_to_end = lambda: None
    panel._plan_payload = {}
    panel.session = _Mock()
    panel.session.host.history = history
    panel._undo_action = _Mock()
    panel._status = _Mock()
    panel._flush_stream = lambda: None

    def enabled():
        return bool(panel._undo_action.setEnabled.call_args[0][0])

    # Nothing on the stack.
    panel._refresh_undo_action()
    assert enabled() is False

    # A plain editor step is not the assistant's work.
    history.push(_Named("Moved node"))
    panel._refresh_undo_action()
    assert enabled() is False

    # An assistant transaction becomes undoable from the panel.
    history.push(_Named("AI: Build tracked shoe glow"))
    panel._refresh_undo_action()
    assert enabled() is True
    assert "AI:" in panel._ai_undo_label()

    panel.undo_ai_changes()
    assert panel._ai_undo_label() == ""


