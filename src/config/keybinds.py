"""Central keybind definitions and mutable binding store (Qt-free)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

class KeyAction(Enum):
    """Stable identifiers for every bindable editor action."""

    NEW_PROJECT = "new_project"
    OPEN_PROJECT = "open_project"
    SAVE_PROJECT = "save_project"
    SAVE_PROJECT_AS = "save_project_as"
    PROJECT_SETTINGS = "project_settings"
    EXPORT_SEQUENCE = "export_sequence"
    CLEAR_CACHE = "clear_cache"
    TOGGLE_LOGS = "toggle_logs"
    EXIT = "exit"

    UNDO = "undo"
    REDO = "redo"
    COPY = "copy"
    PASTE = "paste"
    SELECT_ALL = "select_all"
    DUPLICATE = "duplicate"
    DELETE = "delete"

    SEARCH_NODE = "search_node"
    FIT_GRAPH = "fit_graph"
    FIT_GRAPH_ALT = "fit_graph_alt"
    ORGANIZE_GRAPH = "organize_graph"

    TOGGLE_FULLSCREEN = "toggle_fullscreen"
    FOCUS_VIEWPORT = "focus_viewport"
    FOCUS_GRAPH = "focus_graph"
    FOCUS_TIMELINE = "focus_timeline"
    FOCUS_PROPERTIES = "focus_properties"

    RESET_LAYOUT = "reset_layout"
    SHOW_ALL_PANELS = "show_all_panels"

    PLAY_PAUSE = "play_pause"
    GO_TO_START = "go_to_start"
    STEP_BACK = "step_back"
    STEP_FORWARD = "step_forward"
    GO_TO_END = "go_to_end"
    MARK_IN = "mark_in"
    MARK_OUT = "mark_out"

    SHOW_SHORTCUTS = "show_shortcuts"
    OPEN_PREFERENCES = "open_preferences"


@dataclass(frozen=True)
class KeybindSpec:
    """Metadata for one bindable action."""

    action: KeyAction
    label: str
    category: str
    default_sequence: str
    description: str = ""


@dataclass(frozen=True)
class NodeCreateTarget:
    """Registry identity for a node type a create-slot can spawn."""

    node_type: str
    node_category: str

    @property
    def is_bound(self) -> bool:
        return bool(self.node_type.strip()) and bool(self.node_category.strip())


@dataclass
class NodeCreateSlot:
    """Rebindable hotkey slot that creates a registry node.

    Settings UIs should mutate ``sequence`` and ``target`` — never hardcode
    node types inside the action registry.
    """

    slot_id: str
    sequence: str
    target: NodeCreateTarget
    default_sequence: str
    default_target: NodeCreateTarget

    def display_label(self) -> str:
        if self.target.is_bound:
            return f"Create {self.target.node_type}"
        return f"Create Node ({self.slot_id})"

    def description(self) -> str:
        if self.target.is_bound:
            return (
                f"Insert a {self.target.node_type} "
                f"({self.target.node_category}) at the cursor"
            )
        return "Unassigned create-node slot (configure in settings)"


def _slot(
    slot_id: str,
    sequence: str,
    node_type: str = "",
    node_category: str = "",
) -> NodeCreateSlot:
    target = NodeCreateTarget(node_type=node_type, node_category=node_category)
    return NodeCreateSlot(
        slot_id=slot_id,
        sequence=sequence,
        target=target,
        default_sequence=sequence,
        default_target=target,
    )


# Defaults only — runtime remapping goes through KeybindStore setters.
DEFAULT_NODE_CREATE_SLOTS: tuple[NodeCreateSlot, ...] = (
    _slot("slot_1", "1", "Video Input", "Input/Output"),
    _slot("slot_2", "2", "Viewer", "Input/Output"),
    _slot("slot_3", "3"),
    _slot("slot_4", "4"),
    _slot("slot_5", "5"),
    _slot("slot_6", "6"),
    _slot("slot_7", "7"),
    _slot("slot_8", "8"),
    _slot("slot_9", "9"),
    _slot("slot_0", "0"),
)


DEFAULT_KEYBINDS: tuple[KeybindSpec, ...] = (
    KeybindSpec(KeyAction.NEW_PROJECT, "New Project", "File", "Ctrl+N", "Create a new project"),
    KeybindSpec(KeyAction.OPEN_PROJECT, "Open Project", "File", "Ctrl+O", "Open an existing project"),
    KeybindSpec(KeyAction.SAVE_PROJECT, "Save Project", "File", "Ctrl+S", "Save the current project"),
    KeybindSpec(
        KeyAction.SAVE_PROJECT_AS,
        "Save Project As…",
        "File",
        "Ctrl+Shift+S",
        "Save the project under a new name",
    ),
    KeybindSpec(
        KeyAction.PROJECT_SETTINGS,
        "Project Settings…",
        "File",
        "Ctrl+Shift+,",
        "Edit timeline resolution, frame rate, and duration",
    ),
    KeybindSpec(
        KeyAction.EXPORT_SEQUENCE,
        "Export…",
        "File",
        "Ctrl+E",
        "Export the active viewer to video or image sequence",
    ),
    KeybindSpec(KeyAction.EXIT, "Exit", "File", "Ctrl+Q", "Quit Aphelion"),
    KeybindSpec(KeyAction.UNDO, "Undo", "Edit", "Ctrl+Z", "Undo the last document change"),
    KeybindSpec(KeyAction.REDO, "Redo", "Edit", "Ctrl+Shift+Z", "Redo the last undone change"),
    KeybindSpec(KeyAction.COPY, "Copy", "Edit", "Ctrl+C", "Copy selected nodes"),
    KeybindSpec(KeyAction.PASTE, "Paste", "Edit", "Ctrl+V", "Paste nodes from the clipboard"),
    KeybindSpec(KeyAction.SELECT_ALL, "Select All", "Edit", "Ctrl+A", "Select all nodes"),
    KeybindSpec(KeyAction.DUPLICATE, "Duplicate", "Edit", "Ctrl+D", "Duplicate the selection"),
    KeybindSpec(KeyAction.DELETE, "Delete", "Edit", "Delete", "Delete the selection"),
    KeybindSpec(
        KeyAction.CLEAR_CACHE,
        "Clear Frame Cache",
        "Edit",
        "Ctrl+Shift+K",
        "Drop cached preview frames to reclaim memory",
    ),
    KeybindSpec(
        KeyAction.SEARCH_NODE,
        "Search Nodes",
        "Graph",
        "Tab",
        "Open the node search palette",
    ),
    KeybindSpec(KeyAction.FIT_GRAPH, "Fit Graph to View", "Graph", "F", "Frame all nodes"),
    KeybindSpec(
        KeyAction.FIT_GRAPH_ALT,
        "Fit Graph to View (Alt)",
        "Graph",
        "Shift+F",
        "Frame all nodes",
    ),
    KeybindSpec(
        KeyAction.ORGANIZE_GRAPH,
        "Organize Graph",
        "Graph",
        "Ctrl+Shift+O",
        "Auto-layout nodes by data flow",
    ),
    KeybindSpec(
        KeyAction.TOGGLE_FULLSCREEN,
        "Toggle Fullscreen",
        "View",
        "F11",
        "Enter or exit fullscreen",
    ),
    KeybindSpec(KeyAction.FOCUS_VIEWPORT, "Focus Viewport", "View", "Ctrl+1"),
    KeybindSpec(KeyAction.FOCUS_GRAPH, "Focus Node Graph", "View", "Ctrl+2"),
    KeybindSpec(KeyAction.FOCUS_TIMELINE, "Focus Timeline", "View", "Ctrl+3"),
    KeybindSpec(KeyAction.FOCUS_PROPERTIES, "Focus Properties", "View", "Ctrl+4"),
    KeybindSpec(
        KeyAction.TOGGLE_LOGS,
        "Toggle Logs Panel",
        "Window",
        "Ctrl+Shift+L",
        "Show or hide the log viewer panel",
    ),
    KeybindSpec(
        KeyAction.RESET_LAYOUT,
        "Reset Layout",
        "Window",
        "Ctrl+Shift+R",
        "Restore the default workspace layout",
    ),
    KeybindSpec(
        KeyAction.SHOW_ALL_PANELS,
        "Show All Panels",
        "Window",
        "Ctrl+Shift+P",
        "Show every dock panel",
    ),
    KeybindSpec(KeyAction.PLAY_PAUSE, "Play / Pause", "Playback", "Space"),
    KeybindSpec(KeyAction.GO_TO_START, "Go to Start", "Playback", "Home"),
    KeybindSpec(KeyAction.STEP_BACK, "Previous Frame", "Playback", "Left"),
    KeybindSpec(KeyAction.STEP_FORWARD, "Next Frame", "Playback", "Right"),
    KeybindSpec(KeyAction.GO_TO_END, "Go to End", "Playback", "End"),
    KeybindSpec(KeyAction.MARK_IN, "Set In Point", "Playback", "I"),
    KeybindSpec(KeyAction.MARK_OUT, "Set Out Point", "Playback", "O"),
    KeybindSpec(
        KeyAction.SHOW_SHORTCUTS,
        "Keyboard Shortcuts",
        "Help",
        "Ctrl+/",
        "Show all keybindings",
    ),
    KeybindSpec(
        KeyAction.OPEN_PREFERENCES,
        "Preferences",
        "Edit",
        "Ctrl+,",
        "Open editor preferences",
    ),
)

CATEGORY_ORDER: tuple[str, ...] = (
    "File",
    "Edit",
    "Graph",
    "Create Node",
    "Playback",
    "View",
    "Window",
    "Help",
)


@dataclass(frozen=True)
class ShortcutDisplayRow:
    """Unified row for the shortcuts dialog (actions + create slots)."""

    label: str
    sequence: str
    category: str
    description: str = ""


class KeybindStore:
    """Holds active key sequences and create-node slot mappings."""

    def __init__(self) -> None:
        self._specs: dict[KeyAction, KeybindSpec] = {
            spec.action: spec for spec in DEFAULT_KEYBINDS
        }
        self._bindings: dict[KeyAction, str] = {
            spec.action: spec.default_sequence for spec in DEFAULT_KEYBINDS
        }
        self._node_slots: dict[str, NodeCreateSlot] = {
            slot.slot_id: NodeCreateSlot(
                slot_id=slot.slot_id,
                sequence=slot.sequence,
                target=slot.target,
                default_sequence=slot.default_sequence,
                default_target=slot.default_target,
            )
            for slot in DEFAULT_NODE_CREATE_SLOTS
        }

    def spec(self, action: KeyAction) -> KeybindSpec:
        return self._specs[action]

    def sequence(self, action: KeyAction) -> str:
        """Return the active key sequence string (e.g. ``Ctrl+Z``)."""
        return self._bindings[action]

    def hint(self, action: KeyAction) -> str:
        """Short UI hint for tooltips and status chrome."""
        return self.sequence(action)

    def tooltip(self, label: str, action: KeyAction) -> str:
        """Build ``Label (Hint)`` for buttons and widgets."""
        hint = self.hint(action)
        if not hint:
            return label
        return f"{label} ({hint})"

    def set_sequence(self, action: KeyAction, sequence: str) -> None:
        """Override a binding (for future preferences UI)."""
        self._bindings[action] = sequence.strip()

    def node_create_slots(self) -> list[NodeCreateSlot]:
        """Return create-node slots in stable slot order."""
        order = [slot.slot_id for slot in DEFAULT_NODE_CREATE_SLOTS]
        return [self._node_slots[slot_id] for slot_id in order]

    def bound_node_create_slots(self) -> list[NodeCreateSlot]:
        """Return only slots that currently target a node type."""
        return [slot for slot in self.node_create_slots() if slot.target.is_bound]

    def get_node_create_slot(self, slot_id: str) -> NodeCreateSlot | None:
        return self._node_slots.get(slot_id)

    def set_node_create_sequence(self, slot_id: str, sequence: str) -> None:
        """Remap the hotkey for a create-node slot (settings UI)."""
        slot = self._node_slots.get(slot_id)
        if slot is None:
            return
        slot.sequence = sequence.strip()

    def set_node_create_target(
        self,
        slot_id: str,
        node_type: str,
        node_category: str,
    ) -> None:
        """Point a create-node slot at a registry type (settings UI)."""
        slot = self._node_slots.get(slot_id)
        if slot is None:
            return
        slot.target = NodeCreateTarget(
            node_type=node_type.strip(),
            node_category=node_category.strip(),
        )

    def clear_node_create_target(self, slot_id: str) -> None:
        """Leave a slot's key intact but unassign its node type."""
        self.set_node_create_target(slot_id, "", "")

    def reset_to_defaults(self) -> None:
        for spec in DEFAULT_KEYBINDS:
            self._bindings[spec.action] = spec.default_sequence
        for slot_id, slot in self._node_slots.items():
            defaults = next(
                (item for item in DEFAULT_NODE_CREATE_SLOTS if item.slot_id == slot_id),
                None,
            )
            if defaults is None:
                continue
            slot.sequence = defaults.default_sequence
            slot.target = defaults.default_target

    def all_specs(self) -> list[KeybindSpec]:
        return [self._specs[action] for action in self._bindings]

    def display_rows_by_category(self) -> list[tuple[str, list[ShortcutDisplayRow]]]:
        """Return action + create-slot rows grouped for the shortcuts dialog."""
        grouped: dict[str, list[ShortcutDisplayRow]] = {}
        for spec in DEFAULT_KEYBINDS:
            grouped.setdefault(spec.category, []).append(
                ShortcutDisplayRow(
                    label=spec.label,
                    sequence=self.sequence(spec.action),
                    category=spec.category,
                    description=spec.description,
                )
            )
        create_rows = [
            ShortcutDisplayRow(
                label=slot.display_label(),
                sequence=slot.sequence,
                category="Create Node",
                description=slot.description(),
            )
            for slot in self.node_create_slots()
            if slot.sequence
        ]
        if create_rows:
            grouped["Create Node"] = create_rows

        result: list[tuple[str, list[ShortcutDisplayRow]]] = []
        for category in CATEGORY_ORDER:
            if category in grouped:
                result.append((category, grouped[category]))
        for category, rows in grouped.items():
            if category not in CATEGORY_ORDER:
                result.append((category, rows))
        return result

    def specs_by_category(self) -> list[tuple[str, list[KeybindSpec]]]:
        """Return action specs grouped in display order (create slots excluded)."""
        grouped: dict[str, list[KeybindSpec]] = {}
        for spec in DEFAULT_KEYBINDS:
            grouped.setdefault(spec.category, []).append(spec)
        result: list[tuple[str, list[KeybindSpec]]] = []
        for category in CATEGORY_ORDER:
            if category in grouped:
                result.append((category, grouped[category]))
        for category, specs in grouped.items():
            if category not in CATEGORY_ORDER:
                result.append((category, specs))
        return result
