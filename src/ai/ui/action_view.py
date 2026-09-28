"""Agent activity log.

Tool calls are shown the way a person would describe them::

    ✓ Created Floor Tracker
    ✓ Connected Video → Floor Tracker
    ~ Set Floor Tracker.region_size → 12

Each row can be expanded to reveal the technical detail — the tool name, the
exact arguments, how long it took, and the structured result — so an advanced
user can audit what the assistant actually did without the default view being
a wall of JSON.
"""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QToolButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

_OK_COLOR = QColor(126, 217, 148)
_FAIL_COLOR = QColor(240, 140, 140)
_PENDING_COLOR = QColor(220, 200, 120)
_DETAIL_COLOR = QColor(170, 176, 188)


class ActionLogView(QWidget):
    """Collapsible list of everything the assistant did."""

    focus_nodes = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, QTreeWidgetItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 6, 0)
        self._title = QLabel("Agent activity")
        self._title.setObjectName("AIActivityTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._toggle = QToolButton()
        self._toggle.setText("Hide")
        self._toggle.setAutoRaise(True)
        self._toggle.clicked.connect(self._toggle_body)
        header.addWidget(self._toggle)
        root.addLayout(header)

        self._tree = QTreeWidget()
        self._tree.setObjectName("AIActivityTree")
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._focus_action)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(14)
        self._tree.setUniformRowHeights(True)
        self._tree.setMinimumHeight(90)
        root.addWidget(self._tree, 1)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def add_status(self, text: str) -> None:
        """Append a plain status line (not a tool call)."""
        item = QTreeWidgetItem([text])
        item.setForeground(0, QBrush(_DETAIL_COLOR))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._tree.addTopLevelItem(item)
        self._tree.scrollToItem(item)

    def begin_action(self, call: Any) -> None:
        """Add a pending row for a tool call that has started."""
        key = self._key(call)
        item = QTreeWidgetItem([f"… {call.name}"])
        item.setForeground(0, QBrush(_PENDING_COLOR))
        self._add_detail(item, "Tool", call.name)
        if call.arguments:
            self._add_detail(item, "Arguments", _pretty(call.arguments))
        self._rows[key] = item
        self._tree.addTopLevelItem(item)
        self._tree.scrollToItem(item)

    def finish_action(
        self,
        call: Any,
        result: Any,
        *,
        duration_ms: float | None = None,
    ) -> None:
        """Update the pending row with the authoritative tool result."""
        key = self._key(call)
        item = self._rows.pop(key, None)
        if item is None:
            item = QTreeWidgetItem([""])
            self._tree.addTopLevelItem(item)

        prefix = "✓" if result.ok else "✕"
        item.setText(0, f"{prefix} {result.summary}")
        item.setForeground(0, QBrush(_OK_COLOR if result.ok else _FAIL_COLOR))
        if not result.ok:
            font = QFont()
            font.setBold(True)
            item.setFont(0, font)

        if result.details:
            self._add_detail(item, "Reported actions", "\n".join(result.details))
        if result.data:
            self._add_detail(item, "Result", _pretty(result.data))
        if result.error_code:
            self._add_detail(item, "Error code", result.error_code)
        if result.warnings:
            self._add_detail(item, "Warnings", "\n".join(result.warnings))
        if result.changed_node_ids:
            item.setData(0, Qt.ItemDataRole.UserRole, list(result.changed_node_ids))
            item.setToolTip(0, "Double-click to focus changed nodes")
            self._add_detail(item, "Changed nodes", ", ".join(result.changed_node_ids))
        if duration_ms is not None:
            self._add_detail(item, "Duration", f"{duration_ms:.0f} ms")

        item.setExpanded(False)
        self._tree.scrollToItem(item)

    def _focus_action(self, item, _column):
        while item is not None:
            ids = item.data(0, Qt.ItemDataRole.UserRole)
            if ids:
                self.focus_nodes.emit(ids)
                return
            item = item.parent()

    def clear(self) -> None:
        self._tree.clear()
        self._rows.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _toggle_body(self) -> None:
        visible = not self._tree.isVisible()
        self._tree.setVisible(visible)
        self._toggle.setText("Hide" if visible else "Show")

    @staticmethod
    def _key(call: Any) -> str:
        return str(getattr(call, "call_id", "") or getattr(call, "name", ""))

    @staticmethod
    def _add_detail(parent: QTreeWidgetItem, label: str, value: str) -> None:
        child = QTreeWidgetItem([f"{label}: {value}"])
        child.setForeground(0, QBrush(_DETAIL_COLOR))
        child.setToolTip(0, value)
        parent.addChild(child)


def _pretty(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


__all__ = ["ActionLogView"]
