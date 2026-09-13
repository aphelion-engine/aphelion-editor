"""Compiled execution plan for the node graph.

Why this exists
---------------
The evaluator used to re-derive the same structural facts on every single
frame: which nodes feed the Viewer, in what order, which of them can share
a pixel representation, and which are independent enough to run in
parallel. Those answers only change when the *topology* changes — adding a
node, rewiring an input, or switching the active Viewer.

This module answers them once, when topology changes, and hands the
evaluator an immutable :class:`RenderPlan` it can consume without touching
the live graph. Project/scene state is deliberately *not* imported here:
the plan is compiled from a duck-typed project so it stays testable and
free of import cycles.

What the plan decides
---------------------
``order``
    Topological evaluation order (upstream first).
``u8_source_ids``
    Nodes allowed to hand over their raw 8-bit frames instead of eagerly
    promoting to float32. A source is only eligible when *every* node
    reachable from it — inside the Viewer's own closure — has declared
    ``accepts_u8_frame``. This is the safety gate for the single largest
    interactive win: bare ``Video Input → Viewer`` playback stops doing a
    uint8 → float32 → uint8 round trip that produced identical pixels.
``parallel_groups``
    Nodes grouped by dependency depth. Nodes in the same group have no
    dependency on each other and may be evaluated concurrently.
``total_cost``
    Longest-path weighted preview cost, used by the governor to predict
    whether the next frame can meet its deadline.

Invalidation
------------
The plan is rebuilt when ``Project.topology_revision`` changes, and also
when the node/connection counts differ from the compiled plan — a cheap
O(1) guard against a code path that mutates the graph without bumping the
revision (for example a bulk project load).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from core.nodes.base import PreviewCost

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.project import Project

__all__ = [
    "PlanNode",
    "RenderPlan",
    "RenderPlanCache",
    "compile_render_plan",
]


@dataclass(frozen=True, slots=True)
class PlanNode:
    """One node's compiled participation in the plan."""

    node_id: str
    node_type: str
    name: str
    #: Longest upstream path length; sources are 0.
    depth: int
    #: ``(input_slot, upstream_node_id, upstream_output_slot)``
    inputs: tuple[tuple[str, str, str], ...]
    #: Upstream node ids feeding a frame-carrying socket.
    frame_inputs: tuple[str, ...]
    accepts_u8: bool
    can_emit_u8: bool
    preserves_dtype: bool
    is_static: bool
    is_temporal: bool
    preview_cost: int

    @property
    def cost_class(self) -> PreviewCost:
        """Return the declared preview cost class."""
        return PreviewCost(self.preview_cost)

    @property
    def is_source(self) -> bool:
        """Return whether this node has no frame inputs."""
        return not self.frame_inputs


@dataclass(frozen=True, slots=True)
class RenderPlan:
    """Immutable, reusable execution plan for one Viewer."""

    viewer_id: str
    revision: int
    node_count: int
    connection_count: int
    order: tuple[str, ...]
    nodes: Mapping[str, PlanNode]
    #: Nodes permitted to emit raw 8-bit frames for this plan.
    u8_source_ids: frozenset[str]
    #: Dependency-depth groups; members of a group are mutually independent.
    parallel_groups: tuple[tuple[str, ...], ...]
    #: Node ids in evaluation order grouped by cost class.
    heavy_nodes: tuple[str, ...]
    #: Longest weighted upstream path, in declared cost units.
    total_cost: int

    # ------------------------------------------------------------------
    # Queries used by the evaluator
    # ------------------------------------------------------------------

    def __contains__(self, node_id: object) -> bool:
        return node_id in self.nodes

    def get(self, node_id: str) -> PlanNode | None:
        """Return the compiled entry for ``node_id``, if it is in the plan."""
        return self.nodes.get(node_id)

    def may_emit_u8(self, node_id: str) -> bool:
        """Whether ``node_id`` may hand over a raw 8-bit frame."""
        return node_id in self.u8_source_ids

    def execution_order(self) -> tuple[str, ...]:
        """Return node ids in topological order (upstream first)."""
        return self.order

    def describe(self) -> str:
        """Return a short human-readable summary for diagnostics."""
        heavy = ", ".join(
            self.nodes[node_id].node_type for node_id in self.heavy_nodes
        ) or "none"
        return (
            f"{len(self.nodes)} node(s), {len(self.u8_source_ids)} raw-8-bit source(s), "
            f"cost {self.total_cost}, heavy: {heavy}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for traces."""
        return {
            "viewer_id": self.viewer_id,
            "revision": self.revision,
            "node_count": len(self.nodes),
            "u8_source_ids": sorted(self.u8_source_ids),
            "order": list(self.order),
            "total_cost": self.total_cost,
            "heavy_nodes": [self.nodes[n].node_type for n in self.heavy_nodes],
            "parallel_groups": [list(group) for group in self.parallel_groups],
        }


# ----------------------------------------------------------------------
# Compilation
# ----------------------------------------------------------------------


def _socket_type_is_frame(socket: Any) -> bool:
    """Return whether a socket carries a pixel frame.

    Imported lazily: this keeps the plan module importable in isolation and
    avoids pulling the whole node package into unrelated call sites.
    """
    try:
        from core.nodes.base import NodeSocketType

        return getattr(socket, "socket_type", None) == NodeSocketType.Frame
    except Exception:  # noqa: BLE001 - never let a capability probe raise
        return False


def _upstream_closure(project: "Project", viewer_id: str) -> set[str]:
    """Return every node that feeds ``viewer_id`` (inclusive)."""
    graph = project.dependency_graph
    seen: set[str] = set()
    pending: deque[str] = deque([viewer_id])

    while pending:
        node_id = pending.popleft()
        if node_id in seen or node_id not in project.nodes:
            continue
        seen.add(node_id)
        for connection in graph.get_input_connections(node_id):
            upstream = connection.output_node_id
            if upstream not in seen:
                pending.append(upstream)

    return seen


def _u8_eligible_sources(
    nodes: Mapping[str, PlanNode],
    consumers: Mapping[str, tuple[str, ...]],
    candidates: Iterable[str],
) -> frozenset[str]:
    """Return sources whose raw frames are safe all the way to the Viewer.

    A candidate qualifies only when every node reachable from it — staying
    inside the compiled closure — declares ``accepts_u8_frame``. Nodes that
    do not are the ones that would silently misinterpret a 0-255 buffer as
    a normalized float, so the default is to refuse rather than to hope.
    """
    eligible: set[str] = set()

    for source_id in candidates:
        safe = True
        visited: set[str] = {source_id}
        pending: deque[str] = deque(consumers.get(source_id, ()))

        while pending:
            node_id = pending.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)

            plan_node = nodes.get(node_id)
            if plan_node is None:
                # A consumer outside the plan closure: refuse rather than
                # guess what it does with the frame.
                safe = False
                break

            if not plan_node.accepts_u8:
                safe = False
                break

            pending.extend(consumers.get(node_id, ()))

        if safe:
            eligible.add(source_id)

    return frozenset(eligible)


def compile_render_plan(
    project: "Project",
    viewer_id: str | None = None,
) -> RenderPlan:
    """Compile the execution plan for ``viewer_id`` (or the active Viewer).

    This runs on topology change only, so it is allowed to be clear rather
    than clever. It performs no pixel work and allocates nothing per frame.
    """
    revision = int(getattr(project, "topology_revision", 0))

    if viewer_id is None:
        viewer_id = project.active_viewer

    if not viewer_id or viewer_id not in project.nodes:
        return RenderPlan(
            viewer_id="",
            revision=revision,
            node_count=len(project.nodes),
            connection_count=len(getattr(project, "connections", ()) or ()),
            order=(),
            nodes={},
            u8_source_ids=frozenset(),
            parallel_groups=(),
            heavy_nodes=(),
            total_cost=0,
        )

    graph = project.dependency_graph
    closure = _upstream_closure(project, viewer_id)

    # ------------------------------------------------------------------
    # Per-node entries + consumer index
    # ------------------------------------------------------------------

    build: dict[str, dict[str, Any]] = {}
    consumers: dict[str, list[str]] = {}

    for node_id in closure:
        node = project.nodes.get(node_id)
        if node is None:
            continue

        inputs: list[tuple[str, str, str]] = []
        frame_inputs: list[str] = []

        for connection in graph.get_input_connections(node_id):
            upstream_id = connection.output_node_id
            if upstream_id not in closure:
                continue
            inputs.append(
                (connection.input_slot, upstream_id, connection.output_slot)
            )
            consumers.setdefault(upstream_id, []).append(node_id)

            socket = node.inputs.get(connection.input_slot)
            if socket is not None and _socket_type_is_frame(socket):
                frame_inputs.append(upstream_id)

        build[node_id] = {
            "node": node,
            "inputs": tuple(inputs),
            "frame_inputs": tuple(dict.fromkeys(frame_inputs)),
        }

    if not build:
        return RenderPlan(
            viewer_id=viewer_id,
            revision=revision,
            node_count=len(project.nodes),
            connection_count=len(getattr(project, "connections", ()) or ()),
            order=(),
            nodes={},
            u8_source_ids=frozenset(),
            parallel_groups=(),
            heavy_nodes=(),
            total_cost=0,
        )

    consumer_map: dict[str, tuple[str, ...]] = {
        node_id: tuple(dict.fromkeys(items)) for node_id, items in consumers.items()
    }

    # ------------------------------------------------------------------
    # Topological order (Kahn) + dependency depth
    # ------------------------------------------------------------------

    indegree: dict[str, int] = {}
    for node_id, entry in build.items():
        # Only count edges that actually matter for ordering.
        deps = [
            upstream
            for _slot, upstream, _out in entry["inputs"]
            if upstream in build
        ]
        indegree[node_id] = len(set(deps))

    ready: deque[str] = deque(nid for nid, degree in indegree.items() if degree == 0)
    order: list[str] = []
    depth: dict[str, int] = {}

    while ready:
        node_id = ready.popleft()
        order.append(node_id)

        own_depth = depth.get(node_id, 0)
        for consumer_id in consumer_map.get(node_id, ()):
            if consumer_id not in indegree:
                continue
            candidate = own_depth + 1
            if candidate > depth.get(consumer_id, 0):
                depth[consumer_id] = candidate
            indegree[consumer_id] -= 1
            if indegree[consumer_id] <= 0:
                ready.append(consumer_id)

    # A cycle should be impossible (the project rejects them) but never
    # return a partial order silently.
    if len(order) != len(build):
        for node_id in build:
            if node_id not in depth:
                depth[node_id] = 0
            if node_id not in order:
                order.append(node_id)

    # ------------------------------------------------------------------
    # Plan nodes
    # ------------------------------------------------------------------

    nodes: dict[str, PlanNode] = {}

    for node_id in order:
        entry = build[node_id]
        node = entry["node"]
        nodes[node_id] = PlanNode(
            node_id=node_id,
            node_type=str(getattr(node, "node_type", type(node).__name__)),
            name=str(getattr(node, "name", "") or node_id),
            depth=int(depth.get(node_id, 0)),
            inputs=entry["inputs"],
            frame_inputs=entry["frame_inputs"],
            accepts_u8=bool(getattr(node, "accepts_u8_frame", False)),
            can_emit_u8=bool(getattr(node, "can_emit_u8_frame", False)),
            preserves_dtype=bool(getattr(node, "preserves_frame_dtype", False)),
            is_static=bool(getattr(node, "is_static_output", False)),
            is_temporal=bool(getattr(node, "is_temporal", False)),
            preview_cost=int(getattr(node, "preview_cost", PreviewCost.MEDIUM)),
        )

    # ------------------------------------------------------------------
    # Raw-8-bit source eligibility
    # ------------------------------------------------------------------

    candidates = [
        node_id
        for node_id, plan_node in nodes.items()
        if plan_node.can_emit_u8 and plan_node.is_source
    ]
    u8_source_ids = _u8_eligible_sources(nodes, consumer_map, candidates)

    # ------------------------------------------------------------------
    # Parallel groups (same dependency depth => mutually independent)
    # ------------------------------------------------------------------

    by_depth: dict[int, list[str]] = {}
    for node_id in order:
        by_depth.setdefault(nodes[node_id].depth, []).append(node_id)

    parallel_groups = tuple(
        tuple(by_depth[level])
        for level in sorted(by_depth)
        if level > 0
    )

    # ------------------------------------------------------------------
    # Longest weighted path + heavy node list
    # ------------------------------------------------------------------

    path_cost: dict[str, int] = {}
    for node_id in order:
        plan_node = nodes[node_id]
        upstream_best = max(
            (path_cost.get(up, 0) for up in plan_node.frame_inputs),
            default=0,
        )
        path_cost[node_id] = upstream_best + max(0, plan_node.preview_cost)

    total_cost = max(path_cost.values(), default=0)

    heavy_nodes = tuple(
        node_id
        for node_id in order
        if nodes[node_id].preview_cost >= int(PreviewCost.HEAVY)
    )

    return RenderPlan(
        viewer_id=viewer_id,
        revision=revision,
        node_count=len(project.nodes),
        connection_count=len(getattr(project, "connections", ()) or ()),
        order=tuple(order),
        nodes=nodes,
        u8_source_ids=u8_source_ids,
        parallel_groups=parallel_groups,
        heavy_nodes=heavy_nodes,
        total_cost=total_cost,
    )


class RenderPlanCache:
    """Memoizes the compiled plan for one project.

    Kept as an object rather than a module-level dict so plans die with the
    project and never leak across documents.
    """

    __slots__ = ("_plan",)

    def __init__(self) -> None:
        self._plan: RenderPlan | None = None

    @property
    def plan(self) -> RenderPlan | None:
        """Return the currently cached plan, if any."""
        return self._plan

    def invalidate(self) -> None:
        """Drop the cached plan; the next request recompiles."""
        self._plan = None

    def get(self, project: "Project", viewer_id: str | None = None) -> RenderPlan:
        """Return a valid plan, compiling it only when required."""
        cached = self._plan

        if cached is not None and viewer_id in (None, cached.viewer_id) and _is_fresh(
            cached, project
        ):
            return cached

        plan = compile_render_plan(project, viewer_id)
        self._plan = plan
        return plan


def _is_fresh(plan: RenderPlan, project: "Project") -> bool:
    """Return whether ``plan`` still describes ``project``.

    The revision check is the fast path. The count checks are O(1) belts
    and braces for graph mutations that forget to bump the revision — for
    example a bulk load that writes ``project.nodes`` directly.
    """
    if plan.revision != int(getattr(project, "topology_revision", 0)):
        return False
    if plan.node_count != len(project.nodes):
        return False
    if plan.connection_count != len(getattr(project, "connections", ()) or ()):
        return False
    if plan.viewer_id and plan.viewer_id not in project.nodes:
        return False
    return True
