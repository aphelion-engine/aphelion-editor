"""Shared properties-panel QSS builder for consistent themed text."""

from __future__ import annotations

from config.theme_tokens import ThemeTokens, aphelion_dark


def build_properties_style(tokens: ThemeTokens | None = None) -> str:
    """Return full properties-panel stylesheet with readable text colors."""
    t = tokens or aphelion_dark()
    return f"""
    QWidget#PropertiesPanel,
    QWidget#PropertiesContent,
    QScrollArea#PropertiesScroll {{
        background-color: {t.panel_bg};
        color: {t.text_secondary};
    }}
    QWidget#PropertiesPanel QLabel {{
        color: {t.text_secondary};
    }}
    QLabel#PropertiesNodeTitle {{
        color: {t.text_primary};
        font-size: 12px;
        font-weight: 700;
        padding: 1px 1px 0px 1px;
    }}
    QLabel#PropertiesNodeMeta {{
        color: {t.text_muted};
        font-size: 9px;
        padding: 0px 1px 3px 1px;
    }}
    QFrame#PropertiesDivider {{
        background-color: {t.border};
        max-height: 1px;
        min-height: 1px;
        border: none;
    }}
    QLabel#PropertiesEmptyLabel {{
        color: {t.text_muted};
        font-style: italic;
        font-size: 11px;
    }}
    QWidget#PropertyRow {{
        background-color: transparent;
        border: none;
        min-height: 24px;
        max-height: 28px;
    }}
    QLabel#PropertyRowLabel {{
        color: {t.text_secondary};
        font-size: 10px;
        font-weight: 500;
    }}
    QLabel#PropertySectionLabel {{
        color: {t.accent_text};
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.5px;
        padding: 6px 1px 1px 1px;
    }}
    QDoubleSpinBox#PropertySpin,
    QSpinBox#PropertySpin,
    QLineEdit#PropertyField,
    QComboBox#PropertyCombo {{
        background-color: {t.border_subtle};
        color: {t.text_primary};
        border: 1px solid {t.border};
        border-top: 1px solid #050505;
        border-left: 1px solid #080808;
        border-right: 1px solid #303030;
        border-bottom: 1px solid #404040;
        border-radius: 4px;
        padding: 2px 6px;
        min-height: 20px;
        max-height: 24px;
        font-size: 11px;
        selection-background-color: {t.accent};
        selection-color: {t.text_primary};
    }}
    QDoubleSpinBox#PropertySpin:focus,
    QSpinBox#PropertySpin:focus,
    QLineEdit#PropertyField:focus,
    QComboBox#PropertyCombo:focus {{
        background-color: {t.surface_bg};
        border: 1px solid {t.accent};
        color: {t.text_primary};
    }}
    QDoubleSpinBox#PropertySpin::up-button,
    QDoubleSpinBox#PropertySpin::down-button,
    QSpinBox#PropertySpin::up-button,
    QSpinBox#PropertySpin::down-button {{
        background-color: {t.surface_bg};
        border: none;
        width: 14px;
    }}
    QComboBox#PropertyCombo::drop-down {{
        border: none;
        width: 16px;
    }}
    QComboBox#PropertyCombo QAbstractItemView {{
        background-color: {t.panel_bg};
        color: {t.text_primary};
        border: 1px solid {t.border};
        selection-background-color: {t.accent};
        selection-color: {t.text_primary};
        outline: none;
    }}
    QWidget#PropertyColorSwatch {{
        border: 1px solid {t.border};
        border-radius: 4px;
    }}
    QLabel#PropertyColorHex {{
        color: {t.text_secondary};
        font-size: 10px;
        font-family: Consolas, "Cascadia Mono", monospace;
    }}
    QPushButton#PropertyBrowseButton {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {t.surface_elevated}, stop:1 {t.surface_bg});
        color: {t.text_primary};
        border: 1px solid {t.border};
        border-top: 1px solid #555555;
        border-bottom: 2px solid {t.border_subtle};
        border-radius: 4px;
        min-width: 26px;
        max-width: 26px;
        min-height: 22px;
        font-weight: 700;
    }}
    QPushButton#PropertyBrowseButton:hover {{
        color: {t.text_primary};
        border-color: {t.accent_hover};
    }}
    QSlider#PropertySlider {{
        min-height: 24px;
    }}
    QSlider#PropertySlider::groove:horizontal {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #0a0a0a, stop:0.15 {t.border_subtle}, stop:1 {t.surface_bg});
        border-top: 1px solid #050505;
        border-bottom: 1px solid #404040;
        height: 7px;
        border-radius: 4px;
    }}
    QSlider#PropertySlider::sub-page:horizontal {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {t.accent_hover}, stop:1 {t.accent});
        border-radius: 4px;
    }}
    QSlider#PropertySlider::handle:horizontal {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #f4f4f4, stop:1 #a8a8a8);
        border: 1px solid #1a1a1a;
        border-top: 1px solid #ffffff;
        width: 13px;
        height: 13px;
        margin: -5px -1px;
        border-radius: 7px;
    }}
    QCheckBox#PropertyCheck {{
        color: {t.text_secondary};
        font-size: 10px;
        spacing: 6px;
    }}
    QCheckBox#PropertyCheck::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid {t.border};
        background-color: {t.border_subtle};
    }}
    QCheckBox#PropertyCheck::indicator:checked {{
        background-color: {t.accent};
        border-color: {t.accent_hover};
    }}
    QLabel#PropertySliderValue {{
        color: {t.accent_text};
        font-size: 10px;
        font-weight: 600;
        min-width: 36px;
        padding: 2px 5px;
        background-color: {t.border_subtle};
        border: 1px solid {t.border};
        border-radius: 4px;
    }}
    """
