"""Changes preview dialog.

The assistant shows what it is about to do *before* it becomes permanent::

    AI wants to:

    + Add Floor Tracker
    + Add Perspective Warp
    + Add Grid Generator
    ~ Change Tracking Quality -> Accurate

    [Apply]  [Reject]

For destructive actions the same dialog switches to a warning tone and the
reject button becomes the default, so an accidental Enter cannot delete a
branch.
"""

from __future__ import annotations

from typing import Any

from ai.types import PendingChanges
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
                             QVBoxLayout, QWidget)


class ChangesPreviewDialog(QDialog):
    """Modal preview with Apply / Reject for a pending change set."""

    def __init__(
        self,
        pending: PendingChanges,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AIChangesDialog")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowTitle(
            "Confirm destructive action" if pending.destructive else "Review changes"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        headline = QLabel(
            "The AI wants to make a destructive change:"
            if pending.destructive
            else "The AI wants to:"
        )
        headline.setFont(QFont(headline.font().family(), headline.font().pointSize(), QFont.Weight.Bold))
        layout.addWidget(headline)

        summary = QLabel(pending.label or "AI changes")
        summary.setObjectName("AIHint")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText("\n".join(pending.actions) or "(no changes)")
        body.setMinimumHeight(140)
        layout.addWidget(body, 1)

        if pending.destructive:
            warning = QLabel(
                "This removes or replaces existing work. It is still undoable "
                "with Ctrl+Z, but review the list carefully."
            )
            warning.setWordWrap(True)
            warning.setObjectName("AIWarning")
            layout.addWidget(warning)

        buttons = QDialogButtonBox()
        apply_button = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        reject_button = buttons.addButton("Reject", QDialogButtonBox.ButtonRole.RejectRole)
        apply_button.clicked.connect(self.accept)
        reject_button.clicked.connect(self.reject)
        if pending.destructive:
            apply_button.setDefault(False)
            reject_button.setDefault(True)
            reject_button.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            apply_button.setDefault(True)
        layout.addWidget(buttons)

    @property
    def approved(self) -> bool:
        return self.result() == QDialog.DialogCode.Accepted


def preview_changes(pending: PendingChanges, parent: QWidget | None = None) -> bool:
    """Show the preview and return whether the user approved it."""
    dialog = ChangesPreviewDialog(pending, parent)
    dialog.exec()
    return dialog.approved


def describe_region_proposal(proposal: dict[str, Any]) -> str:
    """Return a readable one-line summary of a vision region proposal."""
    rect = proposal.get("rect") or [0, 0, 0, 0]
    return (
        f"{proposal.get('label', 'region')}: x={rect[0]:.3f} y={rect[1]:.3f} "
        f"w={rect[2]:.3f} h={rect[3]:.3f}"
    )


__all__ = ["ChangesPreviewDialog", "describe_region_proposal", "preview_changes"]
