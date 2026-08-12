"""Project timeline and format settings dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.theme import PROJECT_SETTINGS_STYLE
from core.project import Project
from core.project_settings import ProjectSettings


class ProjectSettingsDialog(QDialog):
    """Edit project name, resolution, frame rate, and duration."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectSettingsDialog")
        self.setWindowTitle("Project Settings")
        self.setStyleSheet(PROJECT_SETTINGS_STYLE)
        self.setModal(True)
        self.resize(380, 320)

        current = project.project_settings()
        self._result: ProjectSettings | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Project Settings")
        title.setObjectName("ProjectSettingsTitle")
        root.addWidget(title)

        general = QGroupBox("General")
        general_form = QFormLayout(general)
        self._name = QLineEdit(current.name)
        general_form.addRow("Name", self._name)
        root.addWidget(general)

        timeline = QGroupBox("Timeline")
        timeline_form = QFormLayout(timeline)
        self._width = QSpinBox()
        self._width.setRange(16, 7680)
        self._width.setValue(current.width)
        self._height = QSpinBox()
        self._height.setRange(16, 4320)
        self._height.setValue(current.height)
        self._fps = QSpinBox()
        self._fps.setRange(1, 240)
        self._fps.setValue(current.fps)
        self._duration = QDoubleSpinBox()
        self._duration.setRange(0.1, 86400.0)
        self._duration.setDecimals(2)
        self._duration.setSingleStep(0.5)
        self._duration.setValue(current.duration)
        timeline_form.addRow("Width", self._width)
        timeline_form.addRow("Height", self._height)
        timeline_form.addRow("Frame Rate", self._fps)
        timeline_form.addRow("Duration (s)", self._duration)
        root.addWidget(timeline)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def settings(self) -> ProjectSettings | None:
        """Accepted settings, or ``None`` when the dialog was cancelled."""
        return self._result

    def _accept(self) -> None:
        self._result = ProjectSettings(
            name=self._name.text(),
            fps=self._fps.value(),
            width=self._width.value(),
            height=self._height.value(),
            duration=self._duration.value(),
        )
        self.accept()
