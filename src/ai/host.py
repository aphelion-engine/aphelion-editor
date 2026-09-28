"""The host bridge between the agent and the running editor.

Tools never import Qt and never reach into a ``QGraphicsItem``. Everything the
agent needs from the *application* — the current selection, a place to put a
new node, a rendered image, a status message — goes through this interface.

Two implementations exist:

* :class:`HeadlessAgentHost` — used by tests and by any non-GUI embedding. It
  is fully functional: created nodes land in the real project through real
  commands, and only the purely visual hooks are no-ops.
* :class:`ai.ui.editor_host.EditorAgentHost` — the live editor, wired to the
  node graph view.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ai.sections import (CATEGORY_SECTIONS, DEFAULT_SECTION, SECTION_ORDER,
                         next_section_name)

#: Horizontal distance between section columns (kept in sync with graph_tools).
SECTION_COLUMN_WIDTH_PX: float = 480.0
SECTION_ORIGIN_X: float = 120.0
SECTION_ORIGIN_Y: float = 80.0
SECTION_ROW_GAP_PX: float = 140.0


class HeadlessAgentHost:
    """Non-GUI host that still drives the real project and history stack."""

    def __init__(self, project: Any, history: Any) -> None:
        self.project = project
        self.history = history
        self._selection: list[str] = []
        self._region_proposal: dict[str, Any] | None = None
        self.messages: list[tuple[str, int]] = []

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def selected_node_ids(self) -> list[str]:
        return [node_id for node_id in self._selection if node_id in self.project.nodes]

    def select_nodes(self, node_ids: Iterable[str], *, focus: bool = False) -> None:
        self._selection = [str(node_id) for node_id in node_ids]

    def set_selection(self, node_ids: Iterable[str]) -> None:
        """Test helper: pretend the user selected these nodes."""
        self._selection = [str(node_id) for node_id in node_ids]

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def next_free_position(self, category: str | None = None) -> tuple[float, float]:
        """Return a clear spot in the correct section column."""
        section = CATEGORY_SECTIONS.get(str(category or ""), DEFAULT_SECTION)
        index = SECTION_ORDER.index(section) if section in SECTION_ORDER else len(
            SECTION_ORDER
        )
        x = SECTION_ORIGIN_X + index * SECTION_COLUMN_WIDTH_PX

        lowest = 0.0
        for node in self.project.nodes.values():
            node_section = CATEGORY_SECTIONS.get(node.node_category, DEFAULT_SECTION)
            if node_section != section:
                continue
            lowest = max(lowest, float(node.y) + float(getattr(node, "height", 100) or 100))
        y = SECTION_ORIGIN_Y if lowest <= 0 else lowest + 40.0
        return x, y

    # ------------------------------------------------------------------
    # Sections (Aphelion's group equivalent)
    # ------------------------------------------------------------------

    def graph_sections(self) -> list[dict[str, Any]]:
        return [dict(section) for section in getattr(self.project, "_ai_sections", [])]

    def set_graph_sections(self, sections: list[dict[str, Any]]) -> None:
        existing = [str(section.get("name", "")) for section in sections]
        normalised: list[dict[str, Any]] = []
        for section in sections:
            name = str(section.get("name", "")).strip() or next_section_name(existing)
            normalised.append(
                {"name": name, "node_ids": [str(n) for n in section.get("node_ids", [])]}
            )
        self.project._ai_sections = normalised

    # ------------------------------------------------------------------
    # Visual hooks (no-ops without a UI)
    # ------------------------------------------------------------------

    def highlight_nodes(
        self,
        node_ids: Iterable[str],
        *,
        label: str = "",
        focus: bool = False,
    ) -> None:
        return None

    def clear_highlights(self) -> None:
        return None

    def show_region_proposal(self, proposal: dict[str, Any]) -> None:
        self._region_proposal = dict(proposal)

    def take_region_proposal(self) -> dict[str, Any] | None:
        proposal = self._region_proposal
        self._region_proposal = None
        return proposal

    def notify(self, message: str, timeout_ms: int = 3000) -> None:
        self.messages.append((message, int(timeout_ms)))

    # ------------------------------------------------------------------
    # Rendering (vision)
    # ------------------------------------------------------------------

    def render_graph_snapshot(self, node_ids: list[str] | None = None) -> str | None:
        """Return a PNG data URL, or ``None`` when rendering is unavailable."""
        try:
            from ai.rendering import graph_snapshot_data_url

            return graph_snapshot_data_url(self.project, node_ids=node_ids)
        except Exception:  # noqa: BLE001 - rendering is optional
            return None

    def render_preview_frame(
        self,
        *,
        frame: int | None = None,
        max_width: int = 640,
    ) -> str | None:
        """Return the current preview as a PNG data URL, when possible."""
        try:
            from ai.ui.frame_grab import preview_frame_data_url
        except Exception:  # noqa: BLE001 - GUI-only helper
            return None
        try:
            return preview_frame_data_url(
                self.project,
                frame=frame,
                max_width=max_width,
            )
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def timeline_range(self) -> tuple[int | None, int | None]:
        return None, None

    def set_current_frame(self, frame: int) -> None:
        self.project.set_frame(int(frame))

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def save_project(self) -> bool:
        path = getattr(self.project, "file_path", None)
        if not path:
            return False
        try:
            from app_io.aph_format import save_aph

            save_aph(path, self.project)
            return True
        except Exception:  # noqa: BLE001 - saving is best-effort from a tool
            return False

    def poll_ui(self) -> None:
        """Give a GUI host a chance to process events. Always safe to call."""
        return None
