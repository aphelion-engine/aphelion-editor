"""Conversation task state and host-side execution evidence."""
from dataclasses import dataclass, field
from enum import Enum
import re


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
_NARRATION = re.compile(r"\b(let me|i(?:'|?)?ll|i will|i need to|next i|going to)\b", re.I)


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

    @property
    def requires_edit(self):
        return self.intent not in ("QUESTION", "INSPECT")

    def begin(self, objective):
        self.objective = objective
        self.intent = classify_intent(objective)
        self.status = TaskStatus.PLANNING
        self.current_step = self.successful_edit_count = 0
        self.completed_actions = []
        self.errors = []
        self.successful_tools = set()
        self.completion_reason = ""
        self.required_operations = set()
        if self.intent == "CREATE":
            self.required_operations.add("create")
        if self.intent == "DELETE":
            self.required_operations.add("delete")
        if self.requires_edit and re.search(r"\b(between|connect|wire|rewire|path)\b", objective, re.I):
            self.required_operations.add("connect")
        if self.requires_edit and re.search(r"\b(cinematic|contrast|exposure|saturation|accurate|accuracy|stronger|property|properties|configure)\b", objective, re.I):
            self.required_operations.add("configure")
        self.plan = ["Inspect relevant context", "Execute requested changes", "Validate result"] if self.requires_edit else ["Inspect and answer"]
        self.pending_actions = list(self.plan)

    def unfinished(self):
        categories = {"create": {"node.create", "graph.import"},
                      "delete": {"node.delete", "node.remove"},
                      "connect": {"connection.connect", "connection.create", "graph.connect"},
                      "configure": {"node.set_property", "node.set_properties", "tracking.configure"}}
        return sorted(name for name in self.required_operations if not self.successful_tools.intersection(categories[name]))

    def diagnostics(self):
        return {"turn_type": self.intent, "status": self.status.value,
                "agent_steps": self.current_step, "successful_edits": self.successful_edit_count,
                "completion_reason": self.completion_reason, "pending_actions": list(self.pending_actions)}
