"""Helpers for the Property Link node and its property-picker UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events import Connection
from core.nodes.base import Node, NodeProperty, NodePropertyInputType, NodeSocketType

if TYPE_CHECKING:
    # ``Project`` only appears in type hints here (``from __future__ import
    # annotations`` defers their evaluation) — importing it directly at
    # module scope would create a cycle, since ``core.project`` imports
    # ``sockets_compatible`` from this module.
    from core.project import Project

PROPERTY_LINK_SOURCE_SLOT: str = "source"
PROPERTY_LINK_PROPERTY_KEY: str = "source_property"

PROPERTY_DRIVE_TARGET_SLOT: str = "target"
PROPERTY_DRIVE_PROPERTY_KEY: str = "target_property"
PROPERTY_DRIVE_VALUE_SLOT: str = "value"

_LINKABLE_INPUT_TYPES: frozenset[NodePropertyInputType] = frozenset(
    {
        NodePropertyInputType.Number,
        NodePropertyInputType.Slider,
        NodePropertyInputType.Checkbox,
    }
)


def node_reference_id(
    project: Project,
    owner_node_id: str,
    input_slot: str,
) -> str | None:
    """Return the upstream node id wired into ``owner_node_id``'s ``input_slot``."""
    for connection in project.connections:
        if (
            connection.input_node_id == owner_node_id
            and connection.input_slot == input_slot
        ):
            return connection.output_node_id
    return None


def property_link_source_id(project: Project, link_node_id: str) -> str | None:
    """Return the upstream node id wired into a Property Link's source socket."""
    return node_reference_id(project, link_node_id, PROPERTY_LINK_SOURCE_SLOT)


def property_drive_target_id(project: Project, drive_node_id: str) -> str | None:
    """Return the upstream node id wired into a Property Drive's target socket."""
    return node_reference_id(project, drive_node_id, PROPERTY_DRIVE_TARGET_SLOT)


def linkable_properties(node: Node) -> list[tuple[str, NodeProperty]]:
    """Return numeric linkable properties on ``node``, sorted for display."""
    items: list[tuple[str, NodeProperty]] = []
    for key, prop in node.properties.items():
        if key.startswith("_input_"):
            continue
        if prop.input_type not in _LINKABLE_INPUT_TYPES:
            continue
        items.append((key, prop))
    items.sort(key=lambda item: (item[1].priority, item[1].label or item[0]))
    return items


def property_link_label(prop: NodeProperty, key: str) -> str:
    """Format one property entry for the link dropdown."""
    label: str = prop.label or key.replace("_", " ").title()
    if prop.group and prop.group != "General":
        return f"{prop.group} · {label}"
    return label


def sockets_compatible(
    output_type: NodeSocketType,
    input_type: NodeSocketType,
) -> bool:
    """Return whether an output may connect to an input socket."""
    if input_type == NodeSocketType.Node:
        return True
    return output_type == input_type


def is_property_link_source_connection(connection: Connection) -> bool:
    """Return whether ``connection`` feeds a Property Link source socket."""
    return connection.input_slot == PROPERTY_LINK_SOURCE_SLOT
