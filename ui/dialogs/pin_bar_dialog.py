"""Dialog letting the user choose which actions appear on the pin bar."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.keybinds import KeyAction, KeybindStore
from config.theme import PIN_BAR_DIALOG_STYLE


class PinBarDialog(QDialog):
    """Scrollable, categorized checklist of actions eligible for pinning."""

    def __init__(
        self,
        store: KeybindStore,
        pinned: list[KeyAction],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._checkboxes: dict[KeyAction, QCheckBox] = {}

        self.setObjectName("PinBarDialog")
        self.setWindowTitle("Customize Pin Bar")
        self.setStyleSheet(PIN_BAR_DIALOG_STYLE)
        self.setModal(True)
        self.resize(420, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Customize Pin Bar")
        title.setObjectName("PinBarDialogTitle")
        root.addWidget(title)

        subtitle = QLabel("Choose the actions you want pinned for quick access.")
        subtitle.setObjectName("PinBarDialogSubtitle")
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("PinBarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("PinBarContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(10)

        pinned_set = set(pinned)
        for category, specs in store.specs_by_category():
            header = QLabel(category)
            header.setObjectName("PinBarCategory")
            content_layout.addWidget(header)
            for spec in specs:
                checkbox = QCheckBox(spec.label)
                checkbox.setObjectName("PinBarCheckbox")
                checkbox.setChecked(spec.action in pinned_set)
                checkbox.setToolTip(spec.description or spec.label)
                content_layout.addWidget(checkbox)
                self._checkboxes[spec.action] = checkbox

        content_layout.addStretch(1)
        scroll.setWidget(content)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_actions(self) -> list[KeyAction]:
        """Return the checked actions in display order."""
        return [
            action
            for action, checkbox in self._checkboxes.items()
            if checkbox.isChecked()
        ]
