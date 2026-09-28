"""Structured graph validation.

The assistant must be able to check its own work, so validation is a pure
function over the live :class:`~core.project.Project` producing machine
readable issues. Both the agent and the ``graph.validate`` tool call it, and
the same codes are surfaced to the UI action log.

Diagnostics are intentionally conservative: only genuine structural
corruption is an *error*. Missing inputs on nodes that are not part of the
evaluated graph, or that the engine can legitimately leave unconnected, are
*informational* warnings so the model is not pushed into "fixing" a valid
graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.events import Connection
from core.nodes.base import NodePropertyInputType
from core.nodes.property_link import sockets_compatible


@dataclass(frozen=True)
class ValidationIssue:
    """One machine-readable graph problem."""

    code: str
    message: str
    severity: str = "error"  # error | warning | info
    node_id: str | None = None
    port: str | None = None
    suggestions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.node_id:
            payload["node_id"] = self.node_id
        if self.port:
            payload["port"] = self.port
        if self.suggestions:
            payload["suggestions"] = list(self.suggestions)
        return payload


@dataclass
class ValidationReport:
    """Aggregate validation result."""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity != "error"]

    def to_dict(self, *, include_warnings: bool = True) -> dict[str, Any]:
        chosen = self.issues if include_warnings else self.errors
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in chosen],
        }

    def summary_line(self) -> str:
        if self.ok and not self.warnings:
            return "Graph is valid."
        if self.ok:
            return f"Graph is valid ({len(self.warnings)} warning(s))."
        return f"{len(self.errors)} problem(s) found."


def validate_project(
    project: Any,
    *,
    include_warnings: bool = True,
    viewer_id: str | None = None,
) -> ValidationReport:
    """Validate the live project graph and return a structured report.

    Checks performed:

    * every connection endpoint references an existing node (broken reference)
    * every connection port actually exists on the node
    * the two ports are type-compatible
    * no leftover self-connections
    * numeric properties stay inside their declared slider range
    * duplicate node names (ambiguous ``Property Link`` targets)
    * missing required inputs on nodes reachable from the active viewer
    * nodes not connected to anything
    """
    report = ValidationReport()
    nodes = getattr(project, "nodes", {}) or {}
    connections = list(getattr(project, "connections", ()) or ())

    _check_connections(nodes, connections, report)
    _check_properties(nodes, report)
    _check_duplicate_names(nodes, report)
    _check_reachability(project, nodes, connections, report, viewer_id=viewer_id)

    if not include_warnings:
        report.issues = report.errors
    return report


def _check_connections(
    nodes: dict[str, Any],
    connections: list[Connection],
    report: ValidationReport,
) -> None:
    seen_inputs: dict[tuple[str, str], int] = {}
    for connection in connections:
        source = nodes.get(connection.output_node_id)
        target = nodes.get(connection.input_node_id)
        if source is None or target is None:
            report.issues.append(
                ValidationIssue(
                    "BROKEN_REFERENCE",
                    "A connection references a node that no longer exists.",
                    node_id=connection.input_node_id if target is None
                    else connection.output_node_id,
                )
            )
            continue

        if connection.output_node_id == connection.input_node_id:
            report.issues.append(
                ValidationIssue(
                    "SELF_CONNECTION",
                    f"Node '{source.name}' is connected to itself.",
                    node_id=connection.output_node_id,
                )
            )

        output = source.outputs.get(connection.output_slot)
        input_port = target.inputs.get(connection.input_slot)
        if output is None:
            report.issues.append(
                ValidationIssue(
                    "UNKNOWN_OUTPUT",
                    f"'{source.name}' has no output named "
                    f"'{connection.output_slot}'.",
                    node_id=connection.output_node_id,
                    port=connection.output_slot,
                    suggestions=tuple(source.outputs),
                )
            )
            continue
        if input_port is None:
            report.issues.append(
                ValidationIssue(
                    "UNKNOWN_INPUT",
                    f"'{target.name}' has no input named "
                    f"'{connection.input_slot}'.",
                    node_id=connection.input_node_id,
                    port=connection.input_slot,
                    suggestions=tuple(target.inputs),
                )
            )
            continue
        if not sockets_compatible(output.socket_type, input_port.socket_type):
            report.issues.append(
                ValidationIssue(
                    "INCOMPATIBLE_PORT_TYPES",
                    f"Cannot connect {source.name}.{connection.output_slot} "
                    f"({output.type_label}) to "
                    f"{target.name}.{connection.input_slot} "
                    f"({input_port.type_label}).",
                    node_id=connection.input_node_id,
                    port=connection.input_slot,
                    suggestions=(),
                )
            )

        key = (connection.input_node_id, connection.input_slot)
        seen_inputs[key] = seen_inputs.get(key, 0) + 1

    for (node_id, slot), count in seen_inputs.items():
        if count > 1:
            report.issues.append(
                ValidationIssue(
                    "DUPLICATE_INPUT_LINK",
                    f"Input '{slot}' receives {count} connections; only one is "
                    "honoured at evaluation time.",
                    severity="warning",
                    node_id=node_id,
                    port=slot,
                )
            )


def _check_properties(nodes: dict[str, Any], report: ValidationReport) -> None:
    for node_id, node in nodes.items():
        for key, prop in node.properties.items():
            if key.startswith("_input_"):
                continue
            value = prop.value
            if prop.input_type in (
                NodePropertyInputType.Number,
                NodePropertyInputType.Slider,
            ) and isinstance(value, (int, float)) and not isinstance(value, bool):
                low = prop.slider_min_value
                high = prop.slider_max_value
                if high > low and not (low <= float(value) <= high):
                    report.issues.append(
                        ValidationIssue(
                            "PROPERTY_OUT_OF_RANGE",
                            f"{node.name}.{key} = {value} is outside the "
                            f"supported range {low}–{high}.",
                            severity="warning",
                            node_id=node_id,
                            port=key,
                        )
                    )
            if value is None and prop.input_type in (
                NodePropertyInputType.Number,
                NodePropertyInputType.Slider,
                NodePropertyInputType.Text,
                NodePropertyInputType.File,
            ):
                report.issues.append(
                    ValidationIssue(
                        "PROPERTY_MISSING_VALUE",
                        f"{node.name}.{key} has no value.",
                        severity="warning",
                        node_id=node_id,
                        port=key,
                    )
                )


def _check_duplicate_names(nodes: dict[str, Any], report: ValidationReport) -> None:
    names: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        names.setdefault(node.name, []).append(node_id)
    for name, ids in names.items():
        if len(ids) > 1:
            report.issues.append(
                ValidationIssue(
                    "DUPLICATE_NODE_NAME",
                    f"{len(ids)} nodes share the name '{name}'. Property Link "
                    "nodes resolving by name may target the wrong node.",
                    severity="warning",
                    node_id=ids[0],
                )
            )


def _check_reachability(
    project: Any,
    nodes: dict[str, Any],
    connections: list[Connection],
    report: ValidationReport,
    *,
    viewer_id: str | None,
) -> None:
    active = viewer_id or getattr(project, "active_viewer", None)
    if not nodes:
        return

    incoming: dict[str, list[Connection]] = {}
    outgoing: dict[str, list[str]] = {}
    for connection in connections:
        incoming.setdefault(connection.input_node_id, []).append(connection)
        outgoing.setdefault(connection.output_node_id, []).append(
            connection.input_node_id
        )

    viewer_node = nodes.get(active) if active else None
    reachable: set[str] = set()
    if viewer_node is not None:
        stack = [active]
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(
                connection.output_node_id
                for connection in incoming.get(current, ())
            )

    connected = set(outgoing) | set(incoming)
    for node_id, node in nodes.items():
        if node_id not in connected and node.node_type != "Viewer":
            report.issues.append(
                ValidationIssue(
                    "UNCONNECTED_NODE",
                    f"'{node.name}' is not connected to any other node.",
                    severity="info",
                    node_id=node_id,
                )
            )

    if viewer_node is None:
        if any(node.node_type == "Viewer" for node in nodes.values()):
            report.issues.append(
                ValidationIssue(
                    "NO_ACTIVE_VIEWER",
                    "No Viewer is active, so the graph cannot be previewed.",
                    severity="warning",
                )
            )
        return

    # Missing-input reporting is deliberately narrow. Most nodes declare
    # every socket as "required" purely because the base class defaults to
    # True, so flagging each bare socket would bury real problems in noise.
    # A node that is *part of the evaluated graph* yet has no input wires at
    # all is the case worth surfacing: it will evaluate on defaults, which is
    # almost never what the user intended.
    for node_id in reachable:
        node = nodes[node_id]
        if not node.inputs:
            continue
        if incoming.get(node_id):
            continue
        bare = [
            slot
            for slot in node.inputs
            if _input_required(node, slot) and slot != "audio"
        ]
        if not bare:
            continue
        report.issues.append(
            ValidationIssue(
                "MISSING_REQUIRED_INPUT",
                f"'{node.name}' is part of the evaluated graph but has no "
                f"connections on its inputs ({', '.join(bare)}).",
                severity="warning",
                node_id=node_id,
                port=bare[0],
            )
        )


def _input_required(node: Any, slot: str) -> bool:
    """Return ``node``'s own opinion about whether ``slot`` must be wired."""
    try:
        return bool(node.input_required(slot))
    except Exception:  # noqa: BLE001 - a custom node may not implement it
        return True
