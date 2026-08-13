"""Read-only in-editor log viewer backed by the application logger."""

from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.theme import LOG_VIEWER_STYLE
from utils.logging_setup import get_logger, log_file_path

_MAX_BLOCKS: Final[int] = 2000
_TAIL_LINES: Final[int] = 400


class _LogBridge(QObject):
    """Thread-safe bridge from ``logging`` records to the UI thread."""

    line_ready = pyqtSignal(str)

    def publish(self, line: str) -> None:
        """Emit one formatted log line on the Qt event loop."""
        self.line_ready.emit(line)


class _QtLogHandler(logging.Handler):
    """Forward Aphelion log records to a ``_LogBridge``."""

    def __init__(self, bridge: _LogBridge) -> None:
        super().__init__()
        self._bridge: _LogBridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        """Format and publish one log record."""
        try:
            message: str = self.format(record)
        except Exception:  # noqa: BLE001
            self.handleError(record)
            return
        self._bridge.publish(message)


class LogViewerWidget(QWidget):
    """Terminal-style read-only view of live application logs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogViewerWidget")
        self.setStyleSheet(LOG_VIEWER_STYLE)

        self._autoscroll: bool = True
        self._bridge: _LogBridge = _LogBridge(self)
        self._handler: _QtLogHandler = _QtLogHandler(self._bridge)
        self._handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        self._terminal: QPlainTextEdit
        self._autoscroll_toggle: QCheckBox
        self._build_ui()
        self._bridge.line_ready.connect(self._append_line)
        self.attach_to_logger()
        self._load_log_tail()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = QWidget()
        toolbar.setObjectName("LogViewerToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(6, 4, 6, 4)
        bar.setSpacing(6)

        self._autoscroll_toggle = QCheckBox("Auto-scroll")
        self._autoscroll_toggle.setObjectName("LogViewerAutoScroll")
        self._autoscroll_toggle.setChecked(True)
        self._autoscroll_toggle.toggled.connect(self._on_autoscroll_toggled)
        bar.addWidget(self._autoscroll_toggle)

        clear_button = QPushButton("Clear")
        clear_button.setObjectName("LogViewerClearButton")
        clear_button.clicked.connect(self.clear)
        bar.addWidget(clear_button)
        bar.addStretch(1)
        root.addWidget(toolbar)

        self._terminal = QPlainTextEdit()
        self._terminal.setObjectName("LogViewerTerminal")
        self._terminal.setReadOnly(True)
        self._terminal.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._terminal.setMaximumBlockCount(_MAX_BLOCKS)
        root.addWidget(self._terminal, 1)

    def attach_to_logger(self) -> None:
        """Subscribe to the Aphelion root logger."""
        logger: logging.Logger = get_logger()
        if self._handler not in logger.handlers:
            logger.addHandler(self._handler)

    def detach_from_logger(self) -> None:
        """Unsubscribe from the Aphelion root logger."""
        logger: logging.Logger = get_logger()
        logger.removeHandler(self._handler)

    def clear(self) -> None:
        """Remove all visible log lines."""
        self._terminal.clear()

    def shutdown(self) -> None:
        """Release logging hooks before application exit."""
        self.detach_from_logger()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Keep the handler attached while the dock is merely hidden."""
        super().closeEvent(a0)

    def _on_autoscroll_toggled(self, checked: bool) -> None:
        self._autoscroll = bool(checked)

    def _append_line(self, line: str) -> None:
        """Append one formatted log line and optionally follow the tail."""
        self._terminal.appendPlainText(line)
        if self._autoscroll:
            cursor: QTextCursor = self._terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._terminal.setTextCursor(cursor)

    def _load_log_tail(self) -> None:
        """Seed the viewer with recent on-disk log history."""
        path = log_file_path()
        if not path.is_file():
            return
        try:
            text: str = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        lines: list[str] = text.splitlines()
        if not lines:
            return
        tail: list[str] = lines[-_TAIL_LINES:]
        self._terminal.setPlainText("\n".join(tail))
        if self._autoscroll:
            cursor: QTextCursor = self._terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._terminal.setTextCursor(cursor)
