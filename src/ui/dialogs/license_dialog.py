"""Friendly, non-blocking license reminder dialog."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
                             QWidget)

from core.license import LICENSE_SITE_URL, LicenseStore, LicenseStatus


class LicenseDialog(QDialog):
    """Show trial status and provide online license activation."""

    def __init__(self, store: LicenseStore, status: LicenseStatus, parent: QWidget) -> None:
        super().__init__(parent)
        self._store = store
        self._close_locked = status.trial_expired
        self._seconds_left = 5 if self._close_locked else 0
        self.setWindowTitle("Aphelion Editor License")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        title = QLabel("Aphelion Editor remains free to use")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        if status.trial_expired:
            message = QLabel(
                "Your seven-day trial has ended. You can keep using the editor; "
                "purchase a lifetime license to stop this reminder."
            )
        else:
            message = QLabel(
                f"You have {status.days_remaining} trial day(s) remaining. "
                "The editor will remain fully usable after the trial."
            )
        message.setWordWrap(True)
        layout.addWidget(message)

        form = QFormLayout()
        self._key = QLineEdit()
        self._key.setPlaceholderText("APHL-XXXXXX-XXXXXX-XXXXXX")
        form.addRow("License key", self._key)
        layout.addLayout(form)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buy = QPushButton("Purchase lifetime license")
        buy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"{LICENSE_SITE_URL}/license")))
        layout.addWidget(buy)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close_button.clicked.connect(self.close)
        layout.addWidget(buttons)

        activate = QPushButton("Activate key")
        activate.clicked.connect(self._activate)
        form.addRow("", activate)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if self._close_locked:
            self._close_button.setEnabled(False)
            self._timer.start(1000)
            self._update_countdown()

    def _activate(self) -> None:
        try:
            ok, message = self._store.activate(self._key.text())
        except ValueError as exc:
            ok, message = False, str(exc)
        if ok:
            QMessageBox.information(self, "License activated", message)
            self.accept()
            return
        self._status.setText(message)

    def _tick(self) -> None:
        self._seconds_left -= 1
        if self._seconds_left <= 0:
            self._timer.stop()
            self._close_locked = False
            self._close_button.setEnabled(True)
        else:
            self._update_countdown()

    def _update_countdown(self) -> None:
        self._status.setText(f"Close available in {self._seconds_left} seconds.")

    def accept(self) -> None:
        if not self._close_locked:
            super().accept()

    def reject(self) -> None:
        if not self._close_locked:
            super().reject()

    def done(self, result: int) -> None:
        if not self._close_locked:
            super().done(result)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._close_locked:
            event.ignore()
            return
        super().closeEvent(event)
