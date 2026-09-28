"""The "Show AI context" audit view.

Answers the developer question "what did the assistant actually look at?"
without ever revealing anything the user must not see: it lists retrieval
events and their provenance, whether the provider was local or remote, which
secrets were redacted, how much of the retrieval budget was spent, and the
token estimate that implies. System prompts and provider credentials are
deliberately absent — this view is about *data sent*, not instructions.
"""

from __future__ import annotations

from typing import Any

from ai.source.security import SECURITY_LOG
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QGroupBox, QHBoxLayout, QLabel,
                             QPushButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

#: Rough characters-per-token used for the estimate.
_CHARS_PER_TOKEN: int = 4

_EVENT_LABELS: dict[str, str] = {
    "secret_redacted": "Secret redacted",
    "injection_suspected": "Prompt injection flagged",
    "path_rejected": "Path refused",
    "source_file_denied": "File refused",
    "source_access_blocked": "Blocked by access level",
    "source_sharing_blocked": "Blocked by sharing policy",
    "source_read_blocked": "Read refused",
    "source_sharing_decision": "Sharing decision",
}


def collect_audit(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gather the current source-access picture for display."""
    retriever_status = (status or {}).get("retriever", {}) if status else {}
    budget = retriever_status.get("budget", {}) if retriever_status else {}
    index = retriever_status.get("index", {}) if retriever_status else {}
    spent = int(budget.get("spent_chars", 0) or 0)
    return {
        "access_label": (status or {}).get("access_label", "Off"),
        "enabled": bool((status or {}).get("enabled", False)),
        "reason": (status or {}).get("reason", ""),
        "scope": retriever_status.get("provider", "—"),
        "raw_allowed": bool(retriever_status.get("raw_source_allowed", False)),
        "indexed_files": int(index.get("file_count", 0) or 0),
        "spent_chars": spent,
        "token_estimate": spent // _CHARS_PER_TOKEN,
        "events": SECURITY_LOG.to_dicts(),
    }


class ContextAuditDialog(QDialog):
    """A read-only report of what the assistant retrieved, and what was refused."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        status: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AIContextAudit")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setWindowTitle("AI context")

        audit = collect_audit(status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        headline = QLabel("What the assistant can (and cannot) see")
        font = QFont(headline.font().family(), headline.font().pointSize())
        font.setBold(True)
        headline.setFont(font)
        layout.addWidget(headline)

        layout.addWidget(self._summary_group(audit))
        layout.addWidget(self._events_group(audit), 1)
        layout.addWidget(self._note_label())

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------

    @staticmethod
    def _summary_group(audit: dict[str, Any]) -> QGroupBox:
        group = QGroupBox("Retrieval")
        layout = QVBoxLayout(group)
        rows = [
            ("Source access", str(audit["access_label"])),
            (
                "Provider",
                "LOCAL — nothing leaves this machine"
                if audit["scope"] == "LOCAL"
                else f"{audit['scope']} — content is sent to a remote service",
            ),
            (
                "Raw source allowed",
                "yes" if audit["raw_allowed"] else "no (metadata only)",
            ),
            ("Indexed files", str(audit["indexed_files"])),
            (
                "Source retrieved this session",
                f"{audit['spent_chars']} chars ≈ {audit['token_estimate']} tokens",
            ),
        ]
        for label, value in rows:
            row = QLabel(f"<b>{label}:</b> {value}")
            row.setWordWrap(True)
            layout.addWidget(row)
        if audit.get("reason"):
            reason = QLabel(str(audit["reason"]))
            reason.setWordWrap(True)
            reason.setObjectName("AIHint")
            layout.addWidget(reason)
        return group

    @staticmethod
    def _events_group(audit: dict[str, Any]) -> QGroupBox:
        group = QGroupBox("Security events")
        layout = QVBoxLayout(group)
        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Event", "Path", "Detail"])
        tree.setUniformRowHeights(True)
        tree.setMinimumHeight(160)

        events = list(audit.get("events", []))
        if not events:
            empty = QTreeWidgetItem(["Nothing recorded yet.", "", ""])
            tree.addTopLevelItem(empty)
        for event in reversed(events):
            label = _EVENT_LABELS.get(str(event.get("kind")), str(event.get("kind")))
            detail_parts: list[str] = []
            for key, value in event.items():
                if key in {"kind", "detail", "path"}:
                    continue
                if isinstance(value, list):
                    detail_parts.append(f"{key}={', '.join(map(str, value))}")
                else:
                    detail_parts.append(f"{key}={value}")
            if event.get("detail"):
                detail_parts.insert(0, str(event["detail"]))
            tree.addTopLevelItem(
                QTreeWidgetItem([label, str(event.get("path", "")), "; ".join(detail_parts)])
            )
        for column in range(3):
            tree.resizeColumnToContents(column)
        layout.addWidget(tree, 1)
        return group

    @staticmethod
    def _note_label() -> QLabel:
        note = QLabel(
            "System instructions and provider credentials are never shown here "
            "or sent as source context. Source text is always treated as "
            "untrusted data."
        )
        note.setWordWrap(True)
        note.setObjectName("AIHint")
        note.setTextFormat(Qt.TextFormat.PlainText)
        return note


#: A read-only text fallback used by tests and headless diagnostics.
def audit_report_text(status: dict[str, Any] | None = None) -> str:
    audit = collect_audit(status)
    lines = [
        f"access={audit['access_label']}",
        f"provider={audit['scope']}",
        f"raw_source={audit['raw_allowed']}",
        f"indexed_files={audit['indexed_files']}",
        f"retrieved_chars={audit['spent_chars']}",
        f"token_estimate={audit['token_estimate']}",
    ]
    for event in audit["events"]:
        lines.append(f"{event.get('kind')} {event.get('path', '')}")
    return "\n".join(lines)


__all__ = ["ContextAuditDialog", "audit_report_text", "collect_audit"]
