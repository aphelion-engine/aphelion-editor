"""Shared UI styling."""

DARK_THEME = """
    QMainWindow {
        background-color: #1e1e1e;
        color: #ffffff;
    }
    QDockWidget {
        background-color: #2a2a2a;
        color: #ffffff;
        border: 1px solid #3a3a3a;
        titlebar-close-icon: url(none);
        titlebar-normal-icon: url(none);
    }
    QDockWidget::title {
        background-color: #3a3a3a;
        color: #ffffff;
        padding: 6px;
        border: none;
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
        background-color: #2a2a2a;
        color: #ffffff;
        border: 1px solid #444444;
        border-radius: 4px;
        padding: 4px 0px;
    }
    QMenu::item {
        padding: 6px 16px;
        margin: 2px 4px;
        border-radius: 3px;
    }
    QMenu::item:selected {
        background-color: #0078d4;
        color: #ffffff;
    }
    QMenu::item:pressed {
        background-color: #006abb;
    }
    QMenu::separator {
        background-color: #444444;
        height: 1px;
        margin: 4px 8px;
    }
"""

DOCK_STYLE = """
    QDockWidget {
        background-color: #2a2a2a;
        color: #ffffff;
        border: 1px solid #3a3a3a;
    }
    QDockWidget::title {
        background-color: #3a3a3a;
        color: #ffffff;
        padding: 6px;
        border: none;
        font-weight: bold;
        font-size: 12px;
        border-bottom: 1px solid #4a4a4a;
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
