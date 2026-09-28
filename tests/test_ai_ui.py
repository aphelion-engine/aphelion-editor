import time
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication
from ai.credentials import CredentialStore
from ai.settings import AISettingsStore
from ai.types import ProviderTestResult, ToolResult
from ai.ui.ai_settings_widget import AISettingsWidget, _PROVIDER_JOBS
from ai.ui.action_view import ActionLogView


def test_settings_modes_profiles_and_background_test(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
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
    deadline = time.monotonic() + 3
    while _PROVIDER_JOBS and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert "Connected to selected profile" in page._test_result.text()
    assert not _PROVIDER_JOBS
    page.close()


def test_action_card_focuses_affected_nodes():
    app = QApplication.instance() or QApplication([])
    view = ActionLogView()
    focused = []
    view.focus_nodes.connect(focused.append)
    view.finish_action(None, ToolResult(ok=True, summary="Added grade", changed_node_ids=["grade-id"]))
    view._focus_action(view._tree.topLevelItem(0), 0)
    assert focused == [["grade-id"]]
    view.close()


# ======================================================================
# Completion cards
# ======================================================================


def _card_panel():
    """A panel wired only enough to render a completion card."""
    from ai.ui.ai_panel import AIPanel

    panel = AIPanel.__new__(AIPanel)
    captured: list[str] = []
    panel._append_html = captured.append
    panel._scroll_to_end = lambda: None
    panel._plan_payload = {
        "steps": [
            {"title": "Built the nodes", "status": "done"},
            {"title": "Validated the graph", "status": "active"},
        ]
    }
    panel.session = Mock()
    panel.session.host.history.can_undo = False
    panel._undo_action = Mock()
    panel._status = Mock()
    panel._flush_stream = lambda: None
    return panel, captured


def test_completion_card_reports_status_changes_and_plan():
    QApplication.instance() or QApplication([])
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
    assert "✓ Built the nodes" in markup
    assert "● Validated the graph" in markup
    assert "Validation passed" in markup
    assert "Undo with Ctrl+Z" in markup


def test_completion_card_never_claims_success_for_a_failure():
    QApplication.instance() or QApplication([])
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
    QApplication.instance() or QApplication([])
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
    assert "Finished</" not in markup


def test_plan_event_updates_progress_without_a_new_message():
    QApplication.instance() or QApplication([])
    from ai.types import AgentEvent, AgentEventKind

    panel, captured = _card_panel()
    panel._on_event(AgentEvent(
        AgentEventKind.PLAN,
        "3/8 steps",
        payload={"steps": [{"title": "Built the nodes", "status": "done"}]},
    ))
    assert panel._plan_payload["steps"][0]["title"] == "Built the nodes"
    panel._status.setText.assert_called_with("3/8 steps")
    # Progress must not be appended to the transcript as a chat message.
    assert captured == []
