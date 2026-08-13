"""Widget that captures a keyboard shortcut sequence."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QLineEdit


class KeyCaptureEdit(QLineEdit):
    """Read-only field that records the next key chord pressed."""

    sequence_changed = pyqtSignal(str)

    def __init__(self, sequence: str = "", parent: QLineEdit | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KeyCaptureField")
        self.setReadOnly(True)
        self.setPlaceholderText("Click then press keys…")
        self.set_sequence(sequence)
        self._capturing: bool = False

    def set_sequence(self, sequence: str) -> None:
        """Display ``sequence`` as the active binding."""
        self.setText(sequence.strip())

    def sequence(self) -> str:
        """Return the captured binding string."""
        return self.text().strip()

    def mousePressEvent(self, event: object | None) -> None:
        self._capturing = True
        self.setPlaceholderText("Press shortcut…")
        self.selectAll()
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def focusOutEvent(self, event: object | None) -> None:
        self._capturing = False
        self.setPlaceholderText("Click then press keys…")
        super().focusOutEvent(event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: object | None) -> None:
        if event is None:
            return
        key_event = event
        key = key_event.key()  # type: ignore[attr-defined]
        if key in (Qt.Key.Key_Escape,):
            self._capturing = False
            self.clearFocus()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.set_sequence("")
            self.sequence_changed.emit("")
            return
        modifiers = key_event.modifiers()  # type: ignore[attr-defined]
        combo = QKeySequence(int(modifiers) | int(key))
        text = combo.toString(QKeySequence.SequenceFormat.NativeText)
        if text:
            self.set_sequence(text)
            self.sequence_changed.emit(text)
            self._capturing = False
            self.clearFocus()
