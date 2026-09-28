"""Tool infrastructure: schemas, strict argument validation, execution.

Design rules enforced here (not by convention):

* Every tool declares a single required :class:`~ai.types.Permission`.
* Arguments are validated against a JSON schema before a handler runs. A
  malformed or out-of-enum call never reaches project state.
* A handler may only reach the project through the transaction / host the
  context gives it, and its failure is converted into a structured
  :class:`ToolResult` rather than an exception.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ai.errors import PermissionDeniedError, ToolArgumentError, ToolError
from ai.permissions import PermissionPolicy
from ai.transaction import AIEditTransaction
from ai.types import AgentMode, Permission, ToolResult

Handler = Callable[["ToolContext"], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    """One callable capability."""

    name: str
    description: str
    parameters: dict[str, Any]
    permission: Permission
    handler: Handler
    mutates: bool = False
    destructive: bool = False
    category: str = "General"
    #: Whether the tool may run inside a transaction that also contains other
    #: mutating tools. Destructive tools default to being isolated so a
    #: rejection cannot strand half of a larger batch.
    standalone: bool = False

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolContext:
    """Everything a tool handler is allowed to touch."""

    host: Any
    args: dict[str, Any]
    permissions: PermissionPolicy
    transaction: AIEditTransaction | None = None
    state: dict[str, Any] = field(default_factory=dict)

    # -- convenience accessors -------------------------------------------

    @property
    def project(self) -> Any:
        return self.host.project

    @property
    def history(self) -> Any:
        return self.host.history

    def require(self, permission: Permission, feature: str) -> None:
        """Raise when ``permission`` is not granted."""
        if not self.permissions.allows(permission):
            raise PermissionDeniedError(
                f"Cannot {feature}. {self.permissions.describe(permission)}",
                permission=permission.name,
            )

    def require_transaction(self, feature: str) -> AIEditTransaction:
        """Return the active transaction, or refuse a write."""
        if self.transaction is None:
            raise ToolError(
                "READ_ONLY_MODE",
                f"Cannot {feature}: the editor is in a read-only agent mode.",
            )
        return self.transaction


class ToolRegistry:
    """Holds the tools a run may use and executes them safely."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def tools(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda spec: spec.name)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    # ------------------------------------------------------------------
    # Exposure
    # ------------------------------------------------------------------

    def available(
        self,
        *,
        mode: AgentMode,
        permissions: PermissionPolicy,
    ) -> list[ToolSpec]:
        """Return the tools that may be *offered* to the model right now.

        In Ask mode no mutating tool is exposed at all, so the model cannot
        even be tempted into claiming a change it is not allowed to make.
        """
        chosen: list[ToolSpec] = []
        for spec in self.tools():
            if spec.mutates and not mode.allows_mutation:
                continue
            if not permissions.allows(spec.permission):
                continue
            chosen.append(spec)
        return chosen

    def openai_schemas(
        self,
        *,
        mode: AgentMode,
        permissions: PermissionPolicy,
    ) -> list[dict[str, Any]]:
        return [
            spec.to_openai_schema()
            for spec in self.available(mode=mode, permissions=permissions)
        ]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | str | None,
        context: ToolContext,
    ) -> ToolResult:
        """Validate and run one tool call, never raising."""
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult.failure(
                "UNKNOWN_TOOL",
                f"There is no tool named '{name}'. Call node.list_types to see "
                "what is available.",
            )
        try:
            parsed = _parse_arguments(arguments)
            validated = validate_arguments(spec.parameters, parsed)
        except ToolArgumentError as exc:
            return ToolResult.failure(
                exc.code,
                str(exc),
                technical={"tool": name, "arguments": arguments},
            )

        if not context.permissions.allows(spec.permission):
            return ToolResult.failure(
                "PERMISSION_DENIED",
                f"Tool '{name}' requires {spec.permission.name}. "
                + context.permissions.describe(spec.permission),
            )

        context.args = validated
        try:
            result = spec.handler(context)
        except PermissionDeniedError as exc:
            return ToolResult.failure(
                exc.code,
                str(exc),
                technical={"tool": name, "permission": exc.permission},
            )
        except ToolError as exc:
            # Includes the source subsystem's refusals (ACCESS_DENIED,
            # SOURCE_SHARING_DISABLED, SOURCE_BUDGET_EXCEEDED), which the model
            # must see verbatim so it can explain the limitation.
            return ToolResult.failure(exc.code, str(exc), technical={"tool": name})
        except Exception as exc:  # noqa: BLE001 - a tool bug must not crash the UI
            return ToolResult.failure(
                "TOOL_FAILED",
                f"{name} failed: {exc}",
                technical={"tool": name, "exception": type(exc).__name__},
            )

        if not isinstance(result, ToolResult):
            return ToolResult.failure(
                "TOOL_CONTRACT",
                f"{name} returned an unexpected value.",
                technical={"tool": name},
            )
        return result


# ======================================================================
# Argument parsing + schema validation
# ======================================================================


def _parse_arguments(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    """Normalise raw model arguments into a dict."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ToolArgumentError(
                f"Arguments were not valid JSON: {exc.msg}",
                field="<root>",
            ) from exc
        if not isinstance(decoded, dict):
            raise ToolArgumentError("Arguments must be a JSON object.")
        return decoded
    raise ToolArgumentError("Arguments must be an object or JSON string.")


def validate_arguments(
    schema: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    """Validate ``values`` against ``schema`` and return coerced values.

    Supports the subset of JSON Schema the tool definitions actually use:
    object/array/string/number/integer/boolean/null, ``required``,
    ``properties``, ``enum``, ``items``, ``minimum``, ``maximum``, and
    ``additionalProperties: false``. Scalar coercion is permissive for numbers
    and booleans because small models frequently send them as strings.
    """
    if schema.get("type") != "object":
        return dict(values)

    properties: dict[str, Any] = schema.get("properties", {}) or {}
    required: list[str] = list(schema.get("required", ()) or ())
    allow_extra = schema.get("additionalProperties", False)

    unknown = [key for key in values if key not in properties]
    if unknown and not allow_extra:
        raise ToolArgumentError(
            "Unknown argument(s): "
            + ", ".join(sorted(unknown))
            + ". Allowed: "
            + (", ".join(sorted(properties)) or "(none)"),
            field=sorted(unknown)[0],
        )

    result: dict[str, Any] = {}
    for key, value in values.items():
        if key not in properties:
            result[key] = value
            continue
        result[key] = _coerce(key, value, properties[key])

    for key in required:
        if key not in result or result[key] in (None, ""):
            raise ToolArgumentError(
                f"Missing required argument '{key}'"
                + (f" ({properties[key].get('description', '')})"
                   if key in properties and properties[key].get("description")
                   else "."),
                field=key,
            )
    return result


def _coerce(field_name: str, value: Any, schema: dict[str, Any]) -> Any:
    """Coerce and range-check one argument value."""
    expected = schema.get("type")

    if value is None:
        if expected is None or "null" in _as_type_list(expected):
            return None
        raise ToolArgumentError(f"'{field_name}' cannot be null.", field=field_name)

    if expected is None:
        return value

    types = _as_type_list(expected)

    if "integer" in types or "number" in types:
        coerced = _as_number(field_name, value, integer="integer" in types and "number" not in types)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and coerced < minimum:
            raise ToolArgumentError(
                f"'{field_name}' must be >= {minimum} (received {coerced}).",
                field=field_name,
            )
        if maximum is not None and coerced > maximum:
            raise ToolArgumentError(
                f"'{field_name}' must be <= {maximum} (received {coerced}).",
                field=field_name,
            )
        return coerced

    if "boolean" in types:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        raise ToolArgumentError(
            f"'{field_name}' must be true or false.", field=field_name
        )

    if "string" in types:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        raise ToolArgumentError(f"'{field_name}' must be text.", field=field_name)

    if "array" in types:
        if not isinstance(value, list):
            raise ToolArgumentError(
                f"'{field_name}' must be a list.", field=field_name
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [
                _coerce(f"{field_name}[{index}]", item, item_schema)
                for index, item in enumerate(value)
            ]
        return value

    if "object" in types:
        if not isinstance(value, dict):
            raise ToolArgumentError(
                f"'{field_name}' must be an object.", field=field_name
            )
        nested = dict(schema)
        nested.setdefault("type", "object")
        return validate_arguments(nested, value)

    allowed = schema.get("enum")
    if allowed and value not in allowed:
        raise ToolArgumentError(
            f"'{field_name}' must be one of: {', '.join(map(str, allowed))}.",
            field=field_name,
        )
    return value


def _as_type_list(expected: Any) -> list[str]:
    if isinstance(expected, str):
        return [expected]
    if isinstance(expected, list):
        return [str(item) for item in expected]
    return []


def _as_number(field_name: str, value: Any, *, integer: bool) -> float | int:
    if isinstance(value, bool):
        raise ToolArgumentError(f"'{field_name}' must be a number.", field=field_name)
    if isinstance(value, (int, float)):
        number: float = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ToolArgumentError(
                f"'{field_name}' must be a number (received {value!r}).",
                field=field_name,
            ) from exc
    else:
        raise ToolArgumentError(f"'{field_name}' must be a number.", field=field_name)
    if integer:
        return int(round(number))
    return number


# ======================================================================
# Default registry
# ======================================================================


def build_default_registry() -> ToolRegistry:
    """Build the full tool set from the individual tool modules."""
    from ai.tools import (connection_tools, graph_tools, node_tools,
                          project_tools, selection_tools, source_tools,
                          timeline_tools, tracking_tools, vision_tools)

    registry = ToolRegistry()
    for module in (
        project_tools,
        graph_tools,
        node_tools,
        connection_tools,
        selection_tools,
        tracking_tools,
        timeline_tools,
        vision_tools,
        source_tools,
    ):
        module.register_tools(registry)
    return registry
