"""Read-only source tools.

These are the only tools that can look at Aphelion's own code, and they are
deliberately incapable of anything else: no writes, no execution, no network.
Two of them (``source.architecture_digest`` and ``node implementation`` data)
work from the live registry alone, so a packaged build with no checkout still
gets an accurate picture of the graph vocabulary.

Retrieved text is returned as *untrusted data*: it carries provenance, secret
redaction results, and prompt-injection flags, and the runtime tells the model
to treat all of it as content rather than instructions.
"""

from __future__ import annotations

from typing import Any

from ai.errors import SourceAccessError, SourceError, SourceUnavailableError
from ai.tools.base import ToolContext, ToolRegistry, ToolSpec
from ai.types import Permission, ToolResult

_READ_SOURCE = Permission.READ_SOURCE


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="source.status",
            description=(
                "Report whether Aphelion's own source code is available to you "
                "for reading, at what level, and how much of the retrieval "
                "budget is left. Call this before relying on source code, so "
                "you can explain the limitation instead of guessing."
            ),
            parameters={"type": "object", "properties": {}},
            permission=_READ_SOURCE,
            handler=_status,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.search",
            description=(
                "Search Aphelion's source tree for code relevant to a question "
                "(for example 'FloorTracker homography recovery'). Returns "
                "matching files, their symbols, and short code snippets marked "
                "as untrusted. Use this to learn how a feature actually works "
                "before explaining or configuring it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Words to search for, e.g. "
                                       "'surface tracking homography recovery'.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 40,
                        "description": "Maximum matches to report (default 10).",
                    },
                },
                "required": ["query"],
            },
            permission=_READ_SOURCE,
            handler=_search,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.read_file",
            description=(
                "Read a file from the Aphelion source tree (optionally a line "
                "range). Only source and documentation files inside the "
                "configured source root can be read. Use source.search first to "
                "find the right file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the source root, e.g. "
                                       "'src/core/nodes/transform_nodes.py'.",
                    },
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
            },
            permission=_READ_SOURCE,
            handler=_read_file,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.read_symbol",
            description=(
                "Read the definition of a class, function, or method by name "
                "(for example 'SurfaceTrackingEngine.update' or 'MergeNode'). "
                "Returns the exact source of that definition."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name, optionally qualified.",
                    },
                    "context": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 40,
                        "description": "Extra lines around the definition.",
                    },
                },
                "required": ["symbol"],
            },
            permission=_READ_SOURCE,
            handler=_read_symbol,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.find_references",
            description=(
                "Find where a symbol is used across the source tree. Useful for "
                "understanding how a node type, port, or tracker setting is "
                "actually consumed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["symbol"],
            },
            permission=_READ_SOURCE,
            handler=_references,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.describe_node_implementation",
            description=(
                "Return a node type's real inputs, outputs, properties, and "
                "where it is implemented (module, file, and declared "
                "ports/properties with line numbers). This is the authoritative "
                "answer to 'how does this node work' and prevents inventing "
                "nodes, ports, or properties."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "Registered node type name.",
                    }
                },
                "required": ["node_type"],
            },
            permission=_READ_SOURCE,
            handler=_describe_node,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.port_compatibility",
            description=(
                "Return which node outputs can legally feed which inputs, by "
                "port type. Call with a port type for one socket, or with no "
                "argument for the whole compatibility index. Use this before "
                "building a graph so the connections are valid."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "port_type": {
                        "type": "string",
                        "description": "Optional socket type, e.g. 'Frame'.",
                    }
                },
            },
            permission=_READ_SOURCE,
            handler=_compatibility,
            category="Source",
        )
    )

    registry.register(
        ToolSpec(
            name="source.architecture_digest",
            description=(
                "Return a short architectural overview of Aphelion: the graph "
                "engine, node registry, tracking, rendering, media, audio, "
                "project serialization, and plugin SDK, plus the live node "
                "category counts. Cheap, and available without a source "
                "checkout."
            ),
            parameters={"type": "object", "properties": {}},
            permission=_READ_SOURCE,
            handler=_digest,
            category="Source",
        )
    )


# ======================================================================
# Handlers
# ======================================================================


def _context(ctx: ToolContext) -> Any:
    """Return the run's :class:`SourceContext`, or raise a tool error."""
    source = (ctx.state or {}).get("source")
    if source is None or getattr(source, "retriever", None) is None:
        reason = getattr(source, "reason", "") or (
            "Source access is not available for this session."
        )
        raise SourceAccessError(reason, code="SOURCE_UNAVAILABLE")
    source.prepare()
    return source


def _status(ctx: ToolContext) -> ToolResult:
    source = (ctx.state or {}).get("source")
    if source is None:
        return ToolResult.failure(
            "SOURCE_UNAVAILABLE",
            "Source access is not configured for this session.",
        )
    payload = source.status()
    if not payload.get("enabled"):
        return ToolResult(
            ok=True,
            summary="Source access is unavailable; use the node registry instead.",
            data=payload,
        )
    stats = payload.get("retriever", {}).get("index", {})
    return ToolResult(
        ok=True,
        summary=(
            f"Source access: {payload.get('access_label')} "
            f"({stats.get('file_count', 0)} files indexed)."
        ),
        data=payload,
    )


def _search(ctx: ToolContext) -> ToolResult:
    source = _context(ctx)
    result = source.retriever.search(
        str(ctx.args["query"]), limit=int(ctx.args.get("limit", 10) or 10)
    )
    matches = result.get("matches", [])
    return ToolResult(
        ok=True,
        summary=(
            f"{len(matches)} source match(es) for '{result['query']}'."
            if matches
            else f"No source matched '{result['query']}'."
        ),
        data=result,
    )


def _read_file(ctx: ToolContext) -> ToolResult:
    source = _context(ctx)
    payload = source.retriever.read_file(
        str(ctx.args["path"]),
        start_line=int(ctx.args.get("start_line", 1) or 1),
        end_line=int(ctx.args.get("end_line", 0) or 0),
    )
    body = payload.to_dict()
    return ToolResult(
        ok=True,
        summary=(
            f"Read {payload.path}"
            + (f" lines {payload.line_start}-{payload.line_end}"
               if payload.line_start else "")
            + "."
        ),
        data={"file": body},
        warnings=([f"Suspected prompt injection markers: {', '.join(payload.injection)}"]
                  if payload.injection else []),
    )


def _read_symbol(ctx: ToolContext) -> ToolResult:
    source = _context(ctx)
    payloads = source.retriever.read_symbol(
        str(ctx.args["symbol"]), context=int(ctx.args.get("context", 0) or 0)
    )
    if not payloads:
        return ToolResult.failure(
            "SYMBOL_NOT_FOUND",
            f"No readable definition of '{ctx.args['symbol']}' was found.",
        )
    return ToolResult(
        ok=True,
        summary=f"Read {len(payloads)} definition(s) for '{ctx.args['symbol']}'.",
        data={"definitions": [payload.to_dict() for payload in payloads]},
    )


def _references(ctx: ToolContext) -> ToolResult:
    source = _context(ctx)
    result = source.retriever.find_references(
        str(ctx.args["symbol"]), limit=int(ctx.args.get("limit", 30) or 30)
    )
    return ToolResult(
        ok=True,
        summary=(
            f"{result['count']} reference(s) to '{result['symbol']}'."
        ),
        data=result,
    )


def _describe_node(ctx: ToolContext) -> ToolResult:
    source = _context(ctx)
    payload = source.retriever.describe_node_implementation(
        str(ctx.args["node_type"])
    )
    return ToolResult(
        ok=True,
        summary=(
            f"{payload['type']} ({payload['category']}): "
            f"{len(payload.get('inputs', []))} input(s), "
            f"{len(payload.get('outputs', []))} output(s), "
            f"{len(payload.get('properties', []))} property(ies)."
        ),
        data=payload,
    )


def _compatibility(ctx: ToolContext) -> ToolResult:
    source = _context(ctx)
    payload = source.retriever.compatibility(str(ctx.args.get("port_type", "") or ""))
    if "port_type" in payload:
        summary = (
            f"Port type {payload['port_type']}: "
            f"{len(payload.get('producers', []))} producer(s), "
            f"{len(payload.get('consumers', []))} consumer(s)."
        )
    else:
        summary = (
            f"{len(payload.get('port_types', {}))} port type(s) in the "
            "compatibility index."
        )
    return ToolResult(ok=True, summary=summary, data=payload)


def _digest(ctx: ToolContext) -> ToolResult:
    source = (ctx.state or {}).get("source")
    digest = source.digest() if source is not None else _fallback_digest()
    registry = digest.get("registry", {})
    return ToolResult(
        ok=True,
        summary=(
            f"Aphelion architecture digest: "
            f"{registry.get('node_type_count', 0)} node types across "
            f"{len(registry.get('categories', {}))} categories."
        ),
        data=digest,
    )


def _fallback_digest() -> dict[str, Any]:
    from ai.source.digest import architecture_digest

    return architecture_digest(None)


__all__ = ["register_tools"]
