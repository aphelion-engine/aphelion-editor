"""Shared QSS theme definitions for the application UI."""

DARK_THEME = """
    QMainWindow {
        background-color: #1e1e1e;
        color: #ffffff;
    }
    QMainWindow::separator {
        background-color: #121212;
        width: 1px;
        height: 1px;
    }
    QDockWidget {
        background-color: #2a2a2a;
        color: #ffffff;
        border: 1px solid #121212;
        titlebar-close-icon: url(none);
        titlebar-normal-icon: url(none);
    }
    QDockWidget::title {
        background-color: #3a3a3a;
        color: #ffffff;
        padding: 6px;
        border: none;
        border-bottom: 1px solid #121212;
        font-weight: bold;
        font-size: 12px;
    }
    QDockWidget::close-button, QDockWidget::float-button {
        background-color: #3a3a3a;
        border: none;
        padding: 0px;
        margin-right: 2px;
    }
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {
        background-color: #444444;
    }
    QMenuBar {
        background-color: #2a2a2a;
        color: #ffffff;
        border-bottom: 1px solid #3a3a3a;
        spacing: 8px;
    }
    QMenuBar::item:selected {
        background-color: #0078d4;
        padding: 4px 12px;
        border-radius: 0px;
    }
    QMenu {
        background-color: #2a2a2a;
        color: #ffffff;
        border: 1px solid #3a3a3a;
        padding: 4px 0px;
    }
    QMenu::item:selected {
        background-color: #0078d4;
        padding: 4px 16px;
    }
    QMenu::separator {
        background-color: #3a3a3a;
        height: 1px;
        margin: 4px 0px;
    }
    QScrollBar:vertical {
        width: 12px;
        background-color: #2a2a2a;
    }
    QScrollBar::handle:vertical {
        background-color: #555555;
        border-radius: 6px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #666666;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        border: none;
        background: none;
    }
"""

CONTEXT_MENU_STYLE = """
    QMenu {
        background-color: #1e1e1e;
        color: #e6e6e6;
        border: 1px solid #333333;
        border-radius: 6px;
        padding: 6px 4px;
        font-size: 12px;
    }
    QMenu::item {
        padding: 6px 28px 6px 10px;
        margin: 1px 4px;
        border-radius: 4px;
        min-height: 22px;
    }
    QMenu::item:selected {
        background-color: #2b6ea8;
        color: #ffffff;
    }
    QMenu::item:pressed {
        background-color: #245f91;
    }
    QMenu::item:disabled {
        color: #666666;
    }
    QMenu::icon {
        padding-left: 6px;
        width: 14px;
        height: 14px;
    }
    QMenu::separator {
        background-color: #333333;
        height: 1px;
        margin: 5px 8px;
    }
    QMenu::right-arrow {
        width: 8px;
        height: 8px;
        margin-right: 6px;
    }
"""

DOCK_STYLE = """
    QDockWidget {
        background-color: #2a2a2a;
        color: #ffffff;
        border: 1px solid #121212;
    }
    QDockWidget::title {
        background-color: #3a3a3a;
        color: #ffffff;
        padding: 6px;
        border: none;
        font-weight: bold;
        font-size: 12px;
        border-bottom: 1px solid #121212;
    }
    QDockWidget > QWidget {
        border: 1px solid #121212;
    }
"""

MENUBAR_STYLE = """
    QMenuBar {
        background-color: #2a2a2a;
        color: #ffffff;
        border-bottom: 1px solid #3a3a3a;
        spacing: 12px;
        padding: 0px 8px;
    }
    QMenuBar::item {
        background-color: transparent;
        padding: 4px 12px;
        border-radius: 4px;
        font-weight: 500;
    }
    QMenuBar::item:selected {
        background-color: #0078d4;
        border-radius: 4px;
    }
    QMenuBar::item:pressed {
        background-color: #006abb;
    }
"""

TIMELINE_STYLE = """
    TimelineWidget {
        background-color: #1a1a1a;
    }
    QLabel#TimelineTimecodeLabel {
        color: #e8e8e8;
        font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
        font-size: 13px;
        font-weight: 600;
        padding: 2px 8px;
        background-color: #141414;
        border: 1px solid #2a2a2a;
        border-radius: 3px;
        min-width: 96px;
    }
    QLabel#TimelineFrameLabel {
        color: #8a8a8a;
        font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
        font-size: 11px;
        padding: 2px 6px;
    }
    QLabel#TimelineMetaLabel {
        color: #6e6e6e;
        font-size: 10px;
        padding: 0px 4px;
    }
    QPushButton#TimelineTransportButton {
        background-color: #252525;
        color: #d0d0d0;
        border: 1px solid #333333;
        border-radius: 4px;
        padding: 5px;
        min-width: 30px;
        max-width: 30px;
        min-height: 28px;
        max-height: 28px;
    }
    QPushButton#TimelineTransportButton:hover {
        background-color: #303030;
        border-color: #454545;
    }
    QPushButton#TimelineTransportButton:pressed {
        background-color: #1c1c1c;
        border-color: #2a2a2a;
    }
    QPushButton#TimelinePlayButton {
        background-color: #252525;
        color: #d0d0d0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 5px;
        min-width: 36px;
        max-width: 36px;
        min-height: 28px;
        max-height: 28px;
    }
    QPushButton#TimelinePlayButton:hover {
        background-color: #2e2e2e;
        border-color: #4a4a4a;
    }
    QPushButton#TimelinePlayButton:pressed {
        background-color: #1c1c1c;
    }
    QPushButton#TimelinePlayButton[playing="true"] {
        background-color: #1e3a52;
        border-color: #2b6ea8;
    }
    QPushButton#TimelineToggleButton {
        background-color: #252525;
        color: #9a9a9a;
        border: 1px solid #333333;
        border-radius: 4px;
        padding: 5px;
        min-width: 30px;
        max-width: 30px;
        min-height: 28px;
        max-height: 28px;
    }
    QPushButton#TimelineToggleButton:hover {
        background-color: #303030;
        border-color: #454545;
    }
    QPushButton#TimelineToggleButton:checked {
        background-color: #243528;
        border-color: #3d6b45;
    }
    QComboBox#TimelineSpeedCombo {
        background-color: #252525;
        color: #c8c8c8;
        border: 1px solid #333333;
        border-radius: 4px;
        padding: 3px 8px;
        min-height: 26px;
        min-width: 64px;
        font-size: 11px;
    }
    QComboBox#TimelineSpeedCombo:hover {
        border-color: #454545;
        color: #ffffff;
    }
    QComboBox#TimelineSpeedCombo::drop-down {
        border: none;
        width: 16px;
    }
    QComboBox#TimelineSpeedCombo QAbstractItemView {
        background-color: #1e1e1e;
        color: #d0d0d0;
        border: 1px solid #333333;
        selection-background-color: #2b6ea8;
        outline: none;
    }
    QFrame#TimelineToolbar {
        background-color: #1a1a1a;
        border: none;
        border-bottom: 1px solid #121212;
    }
"""
