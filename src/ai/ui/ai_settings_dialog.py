"""Standalone AI settings dialog.

The same widget is embedded as a tab in Preferences; this dialog exists so the
assistant can be configured from its own gear button and from View → AI
without opening the full preferences window.
"""

from __future__ import annotations

from ai.credentials import CredentialStore
from ai.settings import AISettingsStore
from ai.ui.ai_settings_widget import AISettingsWidget
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
                             QWidget)


class AISettingsDialog(QDialog):
    """Modal editor for :class:`~ai.settings.AISettings`."""

    def __init__(
        self,
        settings_store: AISettingsStore,
        credentials: CredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AISettingsDialog")
        self.setWindowTitle("AI Settings")
        self.setModal(True)
        self.setMinimumSize(640, 520)
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("AI Providers")
        title.setObjectName("PreferencesTitle")
        layout.addWidget(title)

        self.page = AISettingsWidget(settings_store, credentials, self)
        layout.addWidget(self.page, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(lambda: self.page.commit())
        layout.addWidget(buttons)

    def accept(self) -> None:
        """Persist the edited settings before closing."""
        self.page.commit()
        super().accept()


__all__ = ["AISettingsDialog"]
