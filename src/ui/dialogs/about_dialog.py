"""About dialog with application metadata."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from config.constants import APP_NAME, APP_VERSION
from config.theme import ABOUT_DIALOG_STYLE


class AboutDialog(QDialog):
    """Modal about box for Aphelion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AboutDialog")
        self.setWindowTitle(f"About {APP_NAME}")
        self.setStyleSheet(ABOUT_DIALOG_STYLE)
        self.setModal(True)
        self.resize(420, 260)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setObjectName("AboutTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("AboutVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(version)

        body = QLabel(
            "Enterprise node-based video editor.\n\n"
            "Compose effects in the node graph, preview in real time, "
            "and export finished sequences from any Viewer."
        )
        body.setObjectName("AboutBody")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(body)

        root.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
