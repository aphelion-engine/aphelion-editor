"""Conversation task state and host-side execution evidence."""
from dataclasses import dataclass, field
from enum import Enum
import re

from ai.plan import StepStatus, TodoList, plan_titles


class TaskStatus(str, Enum):
    PLANNING = "PLANNING"
    INSPECTING = "INSPECTING"
    EDITING = "EDITING"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    CANCELLED = "CANCELLED"


_EDIT = re.compile(r"\b(add|create|insert|build|make|set|change|adjust|increase|decrease|connect|wire|rewire|disconnect|delete|remove|move|rename|fix|repair|optimize|organize|apply|use|replace|improve)\b", re.I)
_NARRATION = re.compile(r"\b(let me|i['\u2019]?ll|i will|i need to|next i|going to)\b", re.I)


def classify_intent(text):
    text = text.strip()
    if re.match(r"^(what|why|how|explain|describe|tell me|is there|are there|can (?:you|i) explain)\b", text, re.I):
        return "QUESTION"
    match = _EDIT.search(text)
    if not match or re.search(r"\b(don't|do not|without)\s+(?:\w+\s+)?(?:change|edit|modify|add|create|delete)\b", text, re.I):
        return "INSPECT" if re.search(r"\b(inspect|check|find|list|look up)\b", text, re.I) else "QUESTION"
    word = match.group(1).lower()
    return ({"add": "CREATE", "create": "CREATE", "insert": "CREATE", "build": "CREATE",
             "delete": "DELETE", "remove": "DELETE", "fix": "FIX", "repair": "FIX",
             "optimize": "OPTIMIZE", "organize": "ORGANIZE"}).get(word, "EDIT")


def is_narration(text):
    return bool(_NARRATION.search(text)) or bool(re.match(r"\s*(?:plan:|[1*]\.?.*(?:inspect|find))", text, re.I))


@dataclass
class AgentTask:
    objective: str = ""
    intent: str = "QUESTION"
    status: TaskStatus = TaskStatus.PLANNING
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    discovered_nodes: dict = field(default_factory=dict)
    pending_actions: list[str] = field(default_factory=list)
    completed_actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    successful_edit_count: int = 0
    completion_reason: str = ""
    last_proposed_action: str = ""
    last_changed_node_ids: list[str] = field(default_factory=list)
    discovery_cache: dict = field(default_factory=dict, repr=False)
    registry_signature: tuple = field(default_factory=tuple, repr=False)
    required_operations: set[str] = field(default_factory=set)
    successful_tools: set[str] = field(default_factory=set)
    planned_tool_steps: list[dict] = field(default_factory=list)
    #: The visible plan: an explicit, status-carrying todo list the UI renders.
    todos: TodoList = field(default_factory=TodoList)
    #: The professional workflow this request was recognised as, if any.
    workflow_key: str = ""
    workflow_title: str = ""
    workflow_rationale: str = ""
    workflow_stages: list[str] = field(default_factory=list)
    unsupported_stages: list[str] = field(default_factory=list)

    @property
    def requires_edit(self):
        return self.intent not in ("QUESTION", "INSPECT")

    def begin(self, objective):
        if self.status is TaskStatus.WAITING_FOR_USER and self.requires_edit and classify_intent(objective) in ("QUESTION", "INSPECT"):
            objective = self.objective + "\nUser clarification: " + objective
        self.objective = objective
        self.intent = classify_intent(objective)
        self.status = TaskStatus.PLANNING
        self.current_step = self.successful_edit_count = 0
        self.completed_actions = []
        self.errors = []
        self.successful_tools = set()
        self.planned_tool_steps = []
        self.workflow_key = ""
        self.workflow_title = ""
        self.workflow_rationale = ""
        self.workflow_stages = []
        self.unsupported_stages = []
        self.todos.replace(
            plan_titles(needs_edit=self.requires_edit, workflow=False)
        )
        self.completion_reason = ""
        self._infer_operations(objective)
        self.plan = ["Inspect relevant context", "Execute requested changes", "Validate result"] if self.requires_edit else ["Inspect and answer"]
        self.pending_actions = list(self.plan)

    def _infer_operations(self, objective):
        """Work out which classes of edit this objective implies.

        These are the operations the run must actually perform before it may
        call itself complete; the model's own word is not enough.
        """
        self.required_operations = set()
        if self.intent == "CREATE":
            self.required_operations.add("create")
        if self.intent == "DELETE":
            self.required_operations.add("delete")
        if self.requires_edit and re.search(r"\b(between|connect|wire|rewire|path)\b", objective, re.I):
            self.required_operations.add("connect")
        if self.requires_edit and re.search(r"\b(cinematic|contrast|exposure|saturation|accurate|accuracy|stronger|property|properties|configure)\b", objective, re.I):
            self.required_operations.add("configure")

    def set_workflow(self, plan):
        """Record the recognised professional workflow and re-plan around it.

        The first two steps are completed here because resolving the workflow
        *is* that work: the engine identified how professionals do it, then
        mapped every stage onto real registered node types.
        """
        if not self.requires_edit:
            # Naming an established workflow *is* a request to build it, even
            # when the wording contains no obvious edit verb ("track this
            # graphic onto the wall"). Promote the intent so the run is treated
            # as the edit it really is.
            self.intent = "EDIT"
        self.workflow_key = plan.recipe.key
        self.workflow_title = plan.recipe.title
        self.workflow_rationale = plan.recipe.rationale
        self.workflow_stages = [match.stage.title for match in plan.matches]
        self.unsupported_stages = [match.stage.title for match in plan.unsupported]
        self._infer_operations(self.objective)
        # A recognised workflow always means the run must actually create the
        # nodes for its stages, whatever the wording of the request suggested.
        self.required_operations.add("create")
        self.plan = list(plan_titles(needs_edit=True, workflow=True))
        self.todos.replace(self.plan)
        self.pending_actions = list(self.plan)
        self.todos.complete(self.plan[0])
        self.todos.complete(self.plan[1])
        self.todos.activate_first()

    def record_plan(self, steps):
        """Adopt a plan the model recorded through the ``task.plan`` tool.

        When a professional workflow is already established its understanding
        stages are kept at the head of the list, because the engine really did
        perform them before the model proposed its own steps.
        """
        titles = [str(step["description"]) for step in steps]
        if self.workflow_key:
            understanding = list(plan_titles(needs_edit=True, workflow=True))[:2]
            titles = [title for title in understanding if title not in titles] + titles
        self.todos.replace(titles)
        if self.workflow_key:
            for title in plan_titles(needs_edit=True, workflow=True)[:2]:
                self.todos.complete(title)
        self.todos.activate_first()
        self.plan = list(titles)

    def mark(self, title, *, status: StepStatus = StepStatus.DONE) -> bool:
        """Set the status of one todo step by title.

        Returns:
            Whether a step changed, so the caller only republishes the plan
            when something actually moved.
        """
        step = self.todos.get(title)
        if step is None or step.status is status:
            return False
        step.status = status
        if status is StepStatus.DONE:
            self.todos.activate_first()
        return True

    def sync_planned_todos(self) -> int:
        """Mirror completed ``task.plan`` steps into the visible todo list."""
        changed = 0
        for planned in self.planned_tool_steps:
            if planned.get("done") and self.mark(str(planned["description"])):
                changed += 1
        return changed

    def sync_todos(self, *, validation_ok: bool = False, organised: bool = False) -> None:
        """Advance the visible plan from operations that actually succeeded."""
        tools = self.successful_tools
        if tools & {"node.create", "node.duplicate", "graph.import"}:
            self.mark("Built the nodes")
        if tools & {
            "node.set_property",
            "node.set_properties",
            "tracking.configure",
            "project.update_settings",
        }:
            self.mark("Configured their properties")
        if tools & {"connection.connect", "graph.connect", "connection.create"}:
            self.mark("Connected the chain")
        if validation_ok:
            self.mark("Validated the graph")
        if organised:
            self.mark("Organised the layout")

    def finish_todos(self, *, success: bool, reason: str = "") -> None:
        """Close out the plan once the run has resolved."""
        if success:
            for step in self.todos.unfinished():
                step.status = StepStatus.DONE
        else:
            self.todos.fail_remaining(reason or "The task did not finish.")

    def unfinished(self):
        categories = {"create": {"node.create", "graph.import"},
                      "delete": {"node.delete", "node.remove"},
                      "connect": {"connection.connect", "connection.create", "graph.connect"},
                      "configure": {"node.set_property", "node.set_properties", "tracking.configure"}}
        missing = sorted(name for name in self.required_operations if not self.successful_tools.intersection(categories[name]))
        missing.extend(step["description"] for step in self.planned_tool_steps if not step["done"])
        return missing

    def diagnostics(self):
        return {"turn_type": self.intent, "status": self.status.value,
                "agent_steps": self.current_step, "successful_edits": self.successful_edit_count,
                "completion_reason": self.completion_reason, "pending_actions": list(self.pending_actions),
                "todos": self.todos.to_dict(), "workflow": self.workflow_key}
