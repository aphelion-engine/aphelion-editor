"""Keyboard shortcuts reference dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.keybinds import KeybindStore
from config.theme import SHORTCUTS_DIALOG_STYLE


class ShortcutsDialog(QDialog):
    """Scrollable, categorized list of current keybindings."""

    def __init__(self, store: KeybindStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsDialog")
        self.setWindowTitle("Keyboard Shortcuts")
        self.setStyleSheet(SHORTCUTS_DIALOG_STYLE)
        self.setModal(True)
        self.resize(460, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Keyboard Shortcuts")
        title.setObjectName("ShortcutsDialogTitle")
        root.addWidget(title)

        subtitle = QLabel("Quick actions available throughout the editor.")
        subtitle.setObjectName("ShortcutsDialogSubtitle")
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("ShortcutsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("ShortcutsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(14)

        for category, rows in store.display_rows_by_category():
            header = QLabel(category)
            header.setObjectName("ShortcutsCategory")
            content_layout.addWidget(header)

            for row_data in rows:
                row = QFrame()
                row.setObjectName("ShortcutsRow")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(8, 6, 8, 6)
                row_layout.setSpacing(12)

                label = QLabel(row_data.label)
                label.setObjectName("ShortcutsActionLabel")
                if row_data.description:
                    label.setToolTip(row_data.description)
                row_layout.addWidget(label, 1)

                key = QLabel(row_data.sequence)
                key.setObjectName("ShortcutsKeyBadge")
                key.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(key)

                content_layout.addWidget(row)

        content_layout.addStretch(1)
        scroll.setWidget(content)
