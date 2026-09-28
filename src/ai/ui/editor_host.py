"""Live-editor implementation of the agent host.

The agent runs on a worker thread. Qt widgets are not thread-safe, so every
visual effect (highlight, focus, selection, status message, region overlay)
is *enqueued* here and drained by a timer on the main thread. The worker only
ever touches the project model and the history stack, which is exactly where
the model and undo state belong.

This is the concrete form of the architecture rule: the model never reaches a
``QGraphicsItem``; it reaches a queue that the UI owns.
"""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.windows.editor import Editor


class EditorAgentHost:
    """Bridges the agent to the running editor."""

    #: How long the assistant highlight stays on a changed node.
    HIGHLIGHT_MS: int = 3200

    def __init__(self, editor: Editor) -> None:
        self.editor = editor
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._pending_proposal: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    @property
    def project(self) -> Any:
        return self.editor.project

    @property
    def history(self) -> Any:
        return self.editor.history

    def save_project(self) -> bool:
        try:
            return bool(self.editor.save_project())
        except Exception:  # noqa: BLE001 - saving must not break a tool call
            return False

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def selected_node_ids(self) -> list[str]:
        graph = getattr(self.editor, "node_graph", None)
        if graph is None:
            return []
        return [item.node_id for item in graph.selected_nodes()]

    def select_nodes(self, node_ids: Iterable[str], *, focus: bool = False) -> None:
        ids = [str(node_id) for node_id in node_ids]
        self._enqueue(lambda: self._apply_selection(ids, focus))

    def _apply_selection(self, node_ids: list[str], focus: bool) -> None:
        graph = getattr(self.editor, "node_graph", None)
        if graph is None:
            return
        scene = graph.scene
        scene.clearSelection()
        for node_id in node_ids:
            item = graph.node_items.get(node_id)
            if item is not None:
                item.setSelected(True)
        if focus and node_ids:
            graph.focus_nodes(node_ids)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def next_free_position(self, category: str | None = None) -> tuple[float, float]:
        """Reuse the headless placement algorithm against the live project."""
        from ai.host import HeadlessAgentHost

        helper = HeadlessAgentHost(self.project, self.history)
        return helper.next_free_position(category)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def graph_sections(self) -> list[dict[str, Any]]:
        return [
            dict(section) for section in getattr(self.project, "_ai_sections", [])
        ]

    def set_graph_sections(self, sections: list[dict[str, Any]]) -> None:
        normalised: list[dict[str, Any]] = []
        for section in sections:
            name = str(section.get("name", "")).strip()
            if not name:
                continue
            normalised.append(
                {
                    "name": name,
                    "node_ids": [str(n) for n in section.get("node_ids", [])],
                }
            )
        self.project._ai_sections = normalised

    # ------------------------------------------------------------------
    # Visual hooks
    # ------------------------------------------------------------------

    def highlight_nodes(
        self,
        node_ids: Iterable[str],
        *,
        label: str = "",
        focus: bool = False,
    ) -> None:
        ids = [str(node_id) for node_id in node_ids]
        if not ids:
            return
        self._enqueue(
            lambda: self._apply_highlight(ids, label, focus)
        )

    def _apply_highlight(self, node_ids: list[str], label: str, focus: bool) -> None:
        graph = getattr(self.editor, "node_graph", None)
        if graph is None:
            return
        graph.highlight_nodes(
            node_ids,
            label=label,
            focus=focus,
            duration_ms=self.HIGHLIGHT_MS,
        )

    def clear_highlights(self) -> None:
        self._enqueue(self._apply_clear_highlights)

    def _apply_clear_highlights(self) -> None:
        graph = getattr(self.editor, "node_graph", None)
        if graph is not None:
            graph.clear_ai_highlights()

    def show_region_proposal(self, proposal: dict[str, Any]) -> None:
        self._pending_proposal = dict(proposal)
        self.notify(
            f"AI proposed region '{proposal.get('label', '')}' — review it in the "
            "assistant panel.",
            5000,
        )

    def take_region_proposal(self) -> dict[str, Any] | None:
        proposal = self._pending_proposal
        self._pending_proposal = None
        return proposal

    def notify(self, message: str, timeout_ms: int = 3000) -> None:
        self._enqueue(lambda: self._apply_notify(message, timeout_ms))

    def _apply_notify(self, message: str, timeout_ms: int) -> None:
        status = self.editor.statusBar()
        if status is not None:
            status.showMessage(message, int(timeout_ms))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_graph_snapshot(self, node_ids: list[str] | None = None) -> str | None:
        from ai.rendering import graph_snapshot_data_url

        try:
            return graph_snapshot_data_url(self.project, node_ids=node_ids)
        except Exception:  # noqa: BLE001
            return None

    def render_preview_frame(
        self,
        *,
        frame: int | None = None,
        max_width: int = 640,
    ) -> str | None:
        from ai.rendering import preview_frame_data_url

        try:
            return preview_frame_data_url(
                self.project, frame=frame, max_width=max_width
            )
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def timeline_range(self) -> tuple[int | None, int | None]:
        timeline = getattr(self.editor, "timeline", None)
        controller = getattr(timeline, "controller", None)
        if controller is None:
            return None, None
        try:
            return int(controller.in_point), int(controller.out_point)
        except Exception:  # noqa: BLE001
            return None, None

    def set_current_frame(self, frame: int) -> None:
        self.project.set_frame(int(frame))
        self._enqueue(self._refresh_viewport)

    def _refresh_viewport(self) -> None:
        viewport = getattr(self.editor, "viewport", None)
        if viewport is not None:
            viewport.request_update()

    # ------------------------------------------------------------------
    # Queue plumbing
    # ------------------------------------------------------------------

    def _enqueue(self, action: Callable[[], None]) -> None:
        self._queue.put(action)

    def drain(self) -> int:
        """Run queued UI actions on the main thread. Returns how many ran."""
        ran = 0
        while True:
            try:
                action = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                action()
            except Exception:  # noqa: BLE001 - a UI hiccup must not kill the panel
                continue
            ran += 1
        return ran

    def poll_ui(self) -> None:
        """Kept for parity with the headless host; the panel drives draining."""
        return None
