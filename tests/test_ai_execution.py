import json
import pytest
from ai.engine import AgentEngine, AgentConfig
from ai.host import HeadlessAgentHost
from ai.providers.base import ChatResponse
from ai.errors import ProviderAuthError
from ai.permissions import PermissionPolicy
from ai.tools.base import build_default_registry
from ai.types import ChatMessage, ToolCall, ProviderCapabilities, AgentMode, EditPolicy, AgentEventKind
from ai.task import AgentTask, TaskStatus, classify_intent
from core.project import Project
from core.history.stack import HistoryStack


class ScriptedProvider:
    def __init__(self, replies, native=True):
        self.replies = iter(replies)
        self.requests = []
        self.native = native

    def capabilities(self, model):
        return ProviderCapabilities(supports_tools=self.native)

    def generate(self, request, **kwargs):
        self.requests.append(request)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        if not self.native:
            if reply.tool_calls:
                call = reply.tool_calls[0]
                return ChatResponse(content=json.dumps({"type": "tool_call", "tool": call.name, "arguments": call.arguments}))
            return ChatResponse(content=json.dumps({"type": "final", "text": reply.content}))
        return reply


def call(tool_name, **args):
    return ChatResponse(tool_calls=[ToolCall(name=tool_name, arguments=args, call_id=tool_name)])


def engine(replies, native=True, task=None, **options):
    project = Project()
    host = HeadlessAgentHost(project, HistoryStack(project))
    provider = ScriptedProvider(replies, native)
    agent = AgentEngine(host=host, provider=provider, registry=build_default_registry(),
                        config=AgentConfig(mode=AgentMode.AGENT, edit_policy=EditPolicy.FULL_AGENT, **options),
                        permissions=PermissionPolicy(), model="test", task=task)
    return agent, host, provider


@pytest.mark.parametrize("native", [True, False])
def test_cinematic_narration_continues_through_real_tools(native):
    replies = [ChatResponse(content="Let me first check what color grading nodes are available."),
               call("node.list_types", query="Color Grading"),
               call("node.describe_type", type="Color Grading"),
               call("node.create", type="Color Grading", name="Cinematic Grade"),
               call("node.set_property", node="Cinematic Grade", property="contrast", value=1.12),
               ChatResponse(content="Added and configured Cinematic Grade.")]
    agent, host, provider = engine(replies, native)
    events = []
    result = agent.run([ChatMessage(role="user", content="Can you add a color grading node to make it look more cinematic?")], on_event=events.append)
    assert not result.error, result.error
    assert result.committed and result.validation["ok"]
    assert result.task.status is TaskStatus.COMPLETED
    assert result.steps == 6 and result.task.successful_edit_count == 2
    assert any(node.name == "Cinematic Grade" for node in host.project.nodes.values())
    assert all("Let me" not in e.text for e in events if e.kind is AgentEventKind.TEXT)
    assert "Applied changes" in result.text
    host.history.undo()
    assert not host.project.nodes


def test_empty_execution_is_bounded_failure():
    agent, host, _ = engine([ChatResponse(content="I added it.")] * 4)
    result = agent.run([ChatMessage(role="user", content="Add a Color Grading node.")])
    assert result.error and not result.committed
    assert result.task.status is TaskStatus.FAILED
    assert not host.project.nodes


@pytest.mark.parametrize("failure", ["provider", "limit", "stop"])
def test_incomplete_edits_rollback(failure):
    replies = [call("node.create", type="Color Grading"), ProviderAuthError("HTTP 401")]
    agent, host, _ = engine(replies, max_steps=1 if failure == "limit" else 10)
    stop = lambda: bool(host.project.nodes) if failure == "stop" else False
    result = agent.run([ChatMessage(role="user", content="Add a color grading node.")], should_stop=stop)
    assert result.rolled_back and not result.committed
    assert not host.project.nodes and not host.history.can_undo


def test_read_only_answer_and_narration():
    agent, _, _ = engine([ChatResponse(content="I'll inspect the available nodes."),
                         call("node.list_types", query="Floor Tracker"), ChatResponse(content="Floor Tracker tracks a floor plane.")])
    result = agent.run([ChatMessage(role="user", content="What does Floor Tracker do?")])
    assert not result.error and result.steps == 3 and not result.committed


def test_followup_keeps_discoveries_and_avoids_duplicate_lookup(monkeypatch):
    task = AgentTask()
    agent, host, _ = engine([call("node.describe_type", type="Color Grading"), ChatResponse(content="Color Grading is suitable.")], task=task)
    first = agent.run([ChatMessage(role="user", content="Which node can provide color grading?")])
    assert task.discovery_cache
    provider = ScriptedProvider([call("node.describe_type", type="Color Grading"),
                                call("node.create", type="Color Grading"), ChatResponse(content="Added Color Grading.")])
    agent.provider = provider
    original = agent.registry.execute
    def execute(name, *args):
        assert name != "node.describe_type", "Identical discovery should use cached result"
        return original(name, *args)
    monkeypatch.setattr(agent.registry, "execute", execute)
    second = agent.run(first.messages + [ChatMessage(role="user", content="Add it.")])
    assert second.committed, second.error
    assert "Color Grading is suitable" in provider.requests[0].system


def test_explicit_clarification_waits_without_fake_success():
    agent, _, _ = engine([call("task.request_input", question="Which of the two selected viewers should receive the grade?")])
    result = agent.run([ChatMessage(role="user", content="Add it.")])
    assert result.task.status is TaskStatus.WAITING_FOR_USER
    assert result.text.startswith("Which")
    assert not result.committed


@pytest.mark.parametrize("text,expected", [("Add it", "CREATE"), ("Make this floor tracker more accurate", "EDIT"),
    ("What does Floor Tracker do?", "QUESTION"), ("How do I add a node?", "QUESTION"),
    ("Make a cinematic look", "EDIT"), ("Delete it", "DELETE")])
def test_intent(text, expected):
    assert classify_intent(text) == expected


def test_inserts_grade_into_existing_video_path_and_undo_restores_it():
    from ai.graph_model import resolve_type
    agent, host, _ = engine([
        ChatResponse(content="I'll look up the available nodes first."),
        call("graph.inspect"),
        call("node.describe_type", type="Color Grading"),
        call("node.create", type="Color Grading", name="Grade", properties={"contrast": 1.12}),
        call("connection.create", from_node="Input", from_port="frame", to_node="Grade", to_port="frame"),
        ChatResponse(content="Done."),  # One-sided insertion must not complete.
        call("connection.create", from_node="Grade", from_port="frame", to_node="Output", to_port="frame"),
        ChatResponse(content="Inserted the grade between Input and Output.")])
    source = resolve_type("Video Input").create_instance()
    source.name = "Input"
    viewer = resolve_type("Viewer").create_instance()
    viewer.name = "Output"
    source_id = host.project.add_node(source)
    viewer_id = host.project.add_node(viewer)
    host.project.connect_nodes(source_id, "frame", viewer_id, "frame")
    result = agent.run([ChatMessage(role="user", content="Add a cinematic Color Grading node between the input and viewer.")])
    assert result.committed, result.error
    grade_id = next(key for key, node in host.project.nodes.items() if node.name == "Grade")
    edges = {(c.output_node_id, c.input_node_id) for c in host.project.connections}
    assert (source_id, grade_id) in edges and (grade_id, viewer_id) in edges
    assert (source_id, viewer_id) not in edges
    host.history.undo()
    assert len(host.project.nodes) == 2
    assert {(c.output_node_id, c.input_node_id) for c in host.project.connections} == {(source_id, viewer_id)}


def test_validation_failure_continues_to_repair(monkeypatch):
    from ai.validation import ValidationReport, ValidationIssue
    import ai.engine as engine_module
    original = engine_module.validate_project
    validations = []
    def validate(project):
        validations.append(True)
        if len(validations) == 1:
            return ValidationReport([ValidationIssue("TEST", "Fix the property")])
        return original(project)
    monkeypatch.setattr(engine_module, "validate_project", validate)
    agent, host, _ = engine([
        call("node.create", type="Color Grading", name="Grade"),
        ChatResponse(content="Done."),
        call("node.set_property", node="Grade", property="contrast", value=1.12),
        ChatResponse(content="Added the grade and repaired its settings.")])
    result = agent.run([ChatMessage(role="user", content="Add Color Grading.")])
    assert result.committed and result.validation["ok"], result.error
    assert result.steps == 4 and len(validations) == 3


def test_retry_after_switch_preserves_original_intent(tmp_path, monkeypatch):
    from ai.session import AssistantSession
    from ai.settings import AISettings, ProviderConfig
    from ai.history import ConversationStore
    agent, host, _ = engine([])
    settings = AISettings(enabled=True, agent_mode=AgentMode.AGENT, edit_policy=EditPolicy.FULL_AGENT,
                          providers=[ProviderConfig("a", "A", model="one", enabled=True),
                                     ProviderConfig("b", "B", model="two", enabled=True)], default_provider_id="a")
    session = AssistantSession(host, settings)
    providers = {"a": ScriptedProvider([ProviderAuthError("HTTP 401")]),
                 "b": ScriptedProvider([call("node.create", type="Color Grading"), ChatResponse(content="Added Color Grading.")])}
    monkeypatch.setattr(session, "build_provider", lambda: providers[settings.default_provider_id])
    assert session.send("Add a Color Grading node.").error
    settings.default_provider_id = "b"
    result = session.retry()
    assert result.committed, result.error
    assert providers["b"].requests[0].messages[0].content == "Add a Color Grading node."
    assert len([m for m in session.turns if m.role == "user"]) == 1


def test_recorded_plan_cannot_finalize_with_pending_actions():
    agent, host, _ = engine([
        call("task.plan", steps=[{"description": "Add first grade", "tool": "node.create"},
                                 {"description": "Add second grade", "tool": "node.create"}]),
        call("node.create", type="Color Grading", name="First"),
        ChatResponse(content="Done."),
        call("node.create", type="Color Grading", name="Second"),
        ChatResponse(content="Added both nodes.")])
    result = agent.run([ChatMessage(role="user", content="Add two Color Grading nodes.")])
    assert result.committed and len(host.project.nodes) == 2, result.error
    assert result.steps == 5 and result.task.pending_actions == []
