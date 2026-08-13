"""Qt window placement and presentation helpers."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget


def center_on_primary_screen(window: QWidget) -> None:
    """Move ``window`` to the center of the primary screen's available area.

    Parameters:
        window: Top-level widget to reposition.

    Side effects:
        Updates the widget geometry.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(available.center())
    window.move(frame.topLeft())


def present_window(window: QWidget) -> None:
    """Show a top-level window centered, raised, and focused.

    Parameters:
        window: Top-level widget to present.

    Side effects:
        Shows and focuses the widget without pumping ``processEvents``.
    """
    state = window.windowState()
    if state & Qt.WindowState.WindowMinimized:
        window.setWindowState(state & ~Qt.WindowState.WindowMinimized)
    window.show()
    center_on_primary_screen(window)
    window.raise_()
    window.activateWindow()
