"""Floating quick-action bar for the current node-graph selection.

Rather than hiding multi-node actions in a right-click menu, the graph shows a
small always-visible bar whenever something is selected. Buttons enable and
disable themselves from the selection size, so align needs two nodes while
distribute needs three.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import ui.node_graph.operations as node_ops
import ui.node_graph.selection_ops as selection_ops
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget
from ui.icons import AppIcon, make_icon
from ui.node_graph.constants import MENU_ICON_SIZE_PX

if TYPE_CHECKING:
    from ui.node_graph.node_item import NodeItem
    from ui.node_graph.view import NodeGraphView

_BAR_MARGIN_PX: int = 12

SELECTION_BAR_STYLE = """
    QFrame#SelectionActionBar {
        background-color: rgba(26, 26, 32, 235);
        border: 1px solid #383842;
        border-radius: 8px;
    }
    QLabel#SelectionActionCount {
        color: #eaeaf0;
        font-size: 11px;
        font-weight: 600;
        padding: 0 4px 0 2px;
    }
    QLabel#SelectionActionDivider {
        background-color: #3a3a44;
        max-width: 1px;
        min-width: 1px;
    }
    QToolButton#SelectionActionButton {
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 3px;
    }
    QToolButton#SelectionActionButton:hover:enabled {
        background-color: #2b6ea8;
        border-color: #3d84c0;
    }
    QToolButton#SelectionActionButton:checked {
        background-color: #2b6ea8;
        border-color: #4a95d6;
    }
    QToolButton#SelectionActionButton:disabled {
        background-color: transparent;
    }
"""


class SelectionActionBar(QFrame):
    """Compact toolbar exposing the actions that make sense right now."""

    def __init__(
        self,
        view: NodeGraphView,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view = view
        self.setObjectName("SelectionActionBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(SELECTION_BAR_STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self._count_label = QLabel("0 selected")
        self._count_label.setObjectName("SelectionActionCount")
        layout.addWidget(self._count_label)
        layout.addWidget(_divider())

        self._spotlight_button: QToolButton | None = None
        self._buttons: list[tuple[str, QToolButton, int]] = []
        for key, icon, tooltip, minimum, handler in _button_specs():
            button = QToolButton(self)
            button.setObjectName("SelectionActionButton")
            button.setIcon(make_icon(icon, size=MENU_ICON_SIZE_PX))
            button.setToolTip(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if key == "spotlight":
                button.setCheckable(True)
                self._spotlight_button = button
            button.clicked.connect(
                lambda _checked=False, h=handler: self._run(h)
            )
            self._buttons.append((key, button, minimum))
            layout.addWidget(button)

        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self, items: Sequence[NodeItem]) -> None:
        """Update the label and per-button availability for ``items``."""
        count = len(items)
        self._count_label.setText(
            "1 node selected" if count == 1 else f"{count} nodes selected"
        )
        for _key, button, minimum in self._buttons:
            button.setEnabled(count >= minimum)
        spotlight = self._spotlight_button
        if spotlight is not None:
            spotlight.setChecked(self._view.is_spotlight_enabled())
            spotlight.setEnabled(count > 0)

    def enabled_states(self) -> dict[str, bool]:
        """Return each button's enabled state keyed by action name."""
        return {key: button.isEnabled() for key, button, _ in self._buttons}

    def reposition(self) -> None:
        """Dock the bar to the top center of the viewport."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        x = max(_BAR_MARGIN_PX, (parent.width() - self.width()) // 2)
        self.move(x, _BAR_MARGIN_PX)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run(self, handler: Callable[[NodeGraphView, list[NodeItem]], None]) -> None:
        handler(self._view, self._view.selected_nodes())


def _divider() -> QLabel:
    """Return a thin vertical separator between button groups."""
    divider = QLabel()
    divider.setObjectName("SelectionActionDivider")
    divider.setFixedWidth(1)
    divider.setFixedHeight(18)
    return divider


def _button_specs() -> list[
    tuple[str, AppIcon, str, int, Callable[[NodeGraphView, list[NodeItem]], None]]
]:
    """Return the ordered button definitions for the bar."""

    def align(handler: Callable[..., None], hint: str) -> Callable[
        [NodeGraphView, list[NodeItem]], None
    ]:
        def run(view: NodeGraphView, items: list[NodeItem]) -> None:
            handler(view, items)
            view.notify(hint)

        return run

    def spotlight(view: NodeGraphView, items: list[NodeItem]) -> None:
        del items
        view.toggle_spotlight()

    return [
        ("align_left", AppIcon.ALIGN_LEFT, "Align Left", 2,
         align(node_ops.align_left, "Aligned selection left")),
        ("align_center_h", AppIcon.ALIGN_CENTER_H, "Align Horizontal Centers", 2,
         align(node_ops.align_center_h, "Centered selection horizontally")),
        ("align_top", AppIcon.ALIGN_TOP, "Align Top", 2,
         align(node_ops.align_top, "Aligned selection to top")),
        ("align_center_v", AppIcon.ALIGN_CENTER_V, "Align Vertical Centers", 2,
         align(node_ops.align_center_v, "Centered selection vertically")),
        ("distribute_h", AppIcon.DISTRIBUTE_H, "Distribute Horizontally", 3,
         align(node_ops.distribute_horizontal, "Distributed selection horizontally")),
        ("distribute_v", AppIcon.DISTRIBUTE_V, "Distribute Vertically", 3,
         align(node_ops.distribute_vertical, "Distributed selection vertically")),
        ("tidy", AppIcon.TIDY, "Tidy Selection into a Grid", 2,
         align(_tidy, "Tidied selection")),
        ("fit", AppIcon.FIT_VIEW, "Fit Selection to View", 1,
         align(_fit, "Framed selection")),
        ("spotlight", AppIcon.SPOTLIGHT, "Spotlight Selection (dim the rest)", 1,
         spotlight),
        ("bypass", AppIcon.BYPASS, "Toggle Bypass on Selection", 1,
         align(_bypass, "Toggled selected nodes")),
        ("duplicate", AppIcon.DUPLICATE, "Duplicate Selection", 1,
         align(_duplicate, "Duplicated selection")),
        ("delete", AppIcon.DELETE, "Delete Selection", 1,
         align(_delete, "Deleted selection")),
    ]


def _tidy(view: NodeGraphView, items: list[NodeItem]) -> None:
    selection_ops.tidy_selection(view, items)


def _fit(view: NodeGraphView, items: list[NodeItem]) -> None:
    selection_ops.fit_selection(view, items)


def _bypass(view: NodeGraphView, items: list[NodeItem]) -> None:
    selection_ops.toggle_selection_bypass(view, items)


def _duplicate(view: NodeGraphView, items: list[NodeItem]) -> None:
    node_ops.duplicate_items(view, items)


def _delete(view: NodeGraphView, items: list[NodeItem]) -> None:
    node_ops.delete_items(view, items)
