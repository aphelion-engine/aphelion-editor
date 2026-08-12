"""Build runtime QSS bundles from theme tokens."""

from __future__ import annotations

from dataclasses import dataclass

from config.property_style import build_properties_style
from config.theme_tokens import ThemeTokens


@dataclass(frozen=True, slots=True)
class ThemeStyles:
    """Resolved QSS strings for the live editor chrome."""

    main: str
    dock: str
    menubar: str
    context_menu: str
    timeline: str
    properties: str
    preferences: str


def build_theme_styles(tokens: ThemeTokens) -> ThemeStyles:
    """Generate all editor stylesheets from ``tokens``."""
    t = tokens
    return ThemeStyles(
        main=_main_theme(t),
        dock=_dock_style(t),
        menubar=_menubar_style(t),
        context_menu=_context_menu_style(t),
        timeline=_timeline_style(t),
        properties=build_properties_style(t),
        preferences=_preferences_style(t),
    )


def _main_theme(t: ThemeTokens) -> str:
    return f"""
    QMainWindow {{
        background-color: {t.window_bg};
        color: {t.text_primary};
    }}
    QLabel#StatusKeyHints {{
        color: {t.text_muted};
        font-size: 11px;
        padding-right: 8px;
    }}
    QMainWindow::separator {{
        background-color: {t.border_subtle};
        width: 1px;
        height: 1px;
    }}
    QDockWidget {{
        background-color: {t.panel_bg};
        color: {t.text_primary};
        border: 1px solid {t.border_subtle};
        border-right: 1px solid {t.border};
        border-bottom: 1px solid {t.border};
        titlebar-close-icon: url(none);
        titlebar-normal-icon: url(none);
    }}
    QDockWidget::title {{
        background-color: {t.surface_bg};
        color: {t.text_secondary};
        padding: 1px 8px;
        border: none;
        border-bottom: 1px solid {t.border_subtle};
        border-top: 1px solid {t.border};
        font-weight: 600;
        font-size: 10px;
        text-transform: uppercase;
    }}
    QDockWidget::close-button, QDockWidget::float-button {{
        background-color: transparent;
        border: none;
        padding: 0px;
        margin: 1px 2px 0px 0px;
        width: 12px;
        height: 12px;
    }}
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
        background-color: {t.surface_elevated};
    }}
    QScrollBar:vertical {{
        width: 12px;
        background-color: {t.scrollbar_track};
    }}
    QScrollBar::handle:vertical {{
        background-color: {t.scrollbar_handle};
        border-radius: 6px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {t.text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
    }}
    """


def _dock_style(t: ThemeTokens) -> str:
    return f"""
    QDockWidget {{
        background-color: {t.panel_bg};
        color: {t.text_secondary};
        border: 1px solid {t.border_subtle};
        border-right: 1px solid {t.border};
        border-bottom: 1px solid {t.border};
    }}
    QDockWidget::title {{
        background-color: {t.surface_bg};
        color: {t.text_secondary};
        padding: 1px 8px;
        border: none;
        border-top: 1px solid {t.border};
        border-bottom: 1px solid {t.border_subtle};
        font-weight: 600;
        font-size: 10px;
    }}
    QDockWidget > QWidget {{
        background-color: {t.panel_bg};
        border: none;
        border-top: 1px solid {t.border_subtle};
    }}
    """


def _menubar_style(t: ThemeTokens) -> str:
    return f"""
    QMenuBar {{
        background-color: {t.window_bg};
        color: {t.text_secondary};
        border-bottom: 1px solid {t.border_subtle};
        spacing: 4px;
        padding: 4px 10px;
        font-size: 12px;
    }}
    QMenuBar::item {{
        background-color: transparent;
        color: {t.text_secondary};
        padding: 5px 12px;
        border-radius: 4px;
        font-weight: 500;
    }}
    QMenuBar::item:selected {{
        background-color: {t.accent};
        color: {t.text_primary};
    }}
    QMenuBar::item:pressed {{
        background-color: {t.accent_pressed};
        color: {t.text_primary};
    }}
    """


def _context_menu_style(t: ThemeTokens) -> str:
    return f"""
    QMenu {{
        background-color: {t.menu_bg};
        color: {t.text_primary};
        border: 1px solid {t.border};
        padding: 4px 0px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 16px;
    }}
    QMenu::item:selected {{
        background-color: {t.menu_selected};
    }}
    QMenu::separator {{
        background-color: {t.border};
        height: 1px;
        margin: 4px 8px;
    }}
    """


def _timeline_style(t: ThemeTokens) -> str:
    return f"""
    TimelineWidget {{
        background-color: {t.panel_bg};
    }}
    QLabel#TimelineTimecodeLabel {{
        color: {t.text_secondary};
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 11px;
        font-weight: 600;
        padding: 1px 6px;
        background-color: {t.border_subtle};
        border: 1px solid {t.border};
        border-radius: 3px;
        min-width: 84px;
        max-height: 22px;
    }}
    QLabel#TimelineFrameLabel {{
        color: {t.text_muted};
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 10px;
        padding: 1px 4px;
        max-height: 22px;
    }}
    QPushButton#TimelineTransportButton,
    QPushButton#TimelinePlayButton,
    QPushButton#TimelineToggleButton {{
        background-color: {t.surface_bg};
        color: {t.text_secondary};
        border: 1px solid {t.border};
        border-radius: 3px;
        padding: 2px;
        min-height: 22px;
        max-height: 22px;
    }}
    QPushButton#TimelineTransportButton:hover,
    QPushButton#TimelinePlayButton:hover,
    QPushButton#TimelineToggleButton:hover {{
        background-color: {t.surface_elevated};
        border-color: {t.text_muted};
    }}
    QPushButton#TimelinePlayButton[playing="true"] {{
        background-color: {t.accent_pressed};
        border-color: {t.accent};
    }}
    QComboBox#TimelineSpeedCombo {{
        background-color: {t.surface_bg};
        color: {t.text_secondary};
        border: 1px solid {t.border};
        border-radius: 3px;
        padding: 1px 6px;
        min-height: 22px;
        max-height: 22px;
        font-size: 10px;
    }}
    QComboBox#TimelineSpeedCombo QAbstractItemView {{
        background-color: {t.window_bg};
        color: {t.text_secondary};
        border: 1px solid {t.border};
        selection-background-color: {t.accent};
    }}
    QFrame#TimelineToolbar {{
        background-color: {t.panel_bg};
        border: none;
        border-bottom: 1px solid {t.border_subtle};
    }}
    """


def _preferences_style(t: ThemeTokens) -> str:
    return f"""
    QDialog#PreferencesDialog {{
        background-color: {t.panel_bg};
        color: {t.text_primary};
    }}
    QLabel#PreferencesTitle {{
        color: {t.text_primary};
        font-size: 16px;
        font-weight: 600;
    }}
    QTabWidget#PreferencesTabs::pane {{
        border: 1px solid {t.border};
        border-radius: 6px;
        background-color: {t.window_bg};
        top: -1px;
    }}
    QTabWidget#PreferencesTabs QTabBar::tab {{
        background-color: {t.surface_bg};
        color: {t.text_secondary};
        border: 1px solid {t.border};
        border-bottom: none;
        padding: 8px 16px;
        margin-right: 2px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }}
    QTabWidget#PreferencesTabs QTabBar::tab:selected {{
        background-color: {t.window_bg};
        color: {t.text_primary};
        border-bottom: 1px solid {t.window_bg};
    }}
    QGroupBox#PreferencesGroup {{
        color: {t.accent_text};
        font-weight: 600;
        border: 1px solid {t.border};
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 14px;
    }}
    QGroupBox#PreferencesGroup::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }}
    QLabel#PreferencesHint {{
        color: {t.text_muted};
        font-size: 11px;
    }}
    QLineEdit#KeyCaptureField,
    QSpinBox#PreferencesSpin,
    QComboBox#PreferencesCombo,
    QLineEdit#PreferencesField {{
        background-color: {t.border_subtle};
        color: {t.text_secondary};
        border: 1px solid {t.border};
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 24px;
    }}
    QLineEdit#KeyCaptureField:focus,
    QSpinBox#PreferencesSpin:focus,
    QComboBox#PreferencesCombo:focus,
    QLineEdit#PreferencesField:focus {{
        border: 1px solid {t.accent};
    }}
    QPushButton#PreferencesPrimaryButton {{
        background-color: {t.accent};
        color: {t.text_primary};
        border: 1px solid {t.accent_hover};
        border-radius: 5px;
        padding: 7px 16px;
        font-weight: 600;
    }}
    QPushButton#PreferencesPrimaryButton:hover {{
        background-color: {t.accent_hover};
    }}
    QPushButton#PreferencesSecondaryButton {{
        background-color: {t.surface_bg};
        color: {t.text_secondary};
        border: 1px solid {t.border};
        border-radius: 5px;
        padding: 7px 16px;
    }}
    QPushButton#PreferencesSecondaryButton:hover {{
        background-color: {t.surface_elevated};
    }}
    QFrame#PreferencesRow {{
        background-color: {t.surface_bg};
        border: 1px solid {t.border};
        border-radius: 5px;
    }}
    QScrollArea#PreferencesScroll {{
        background: transparent;
        border: none;
    }}
    """
