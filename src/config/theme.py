"""Shared QSS theme definitions for the application UI."""

from config.property_style import build_properties_style

DARK_THEME = """
    QMainWindow {
        background-color: #1e1e1e;
        color: #ffffff;
    }
    QLabel#StatusKeyHints {
        color: #8a8a94;
        font-size: 11px;
        padding-right: 8px;
    }
    QMainWindow::separator {
        background-color: #121212;
        width: 1px;
        height: 1px;
    }
    QDockWidget {
        background-color: #1a1a1a;
        color: #ffffff;
        border: 1px solid #0a0a0a;
        border-right: 1px solid #2e2e2e;
        border-bottom: 1px solid #2e2e2e;
        titlebar-close-icon: url(none);
        titlebar-normal-icon: url(none);
    }
    QDockWidget::title {
        background-color: #252525;
        color: #c8c8c8;
        padding: 1px 8px;
        border: none;
        border-bottom: 1px solid #0a0a0a;
        border-top: 1px solid #323232;
        font-weight: 600;
        font-size: 10px;
        text-transform: uppercase;
    }
    QDockWidget::close-button, QDockWidget::float-button {
        background-color: transparent;
        border: none;
        padding: 0px;
        margin: 1px 2px 0px 0px;
        width: 12px;
        height: 12px;
    }
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {
        background-color: #3a3a3a;
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

SHORTCUTS_DIALOG_STYLE = """
    QDialog#ShortcutsDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QLabel#ShortcutsDialogTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#ShortcutsDialogSubtitle {
        color: #9a9aa4;
        font-size: 12px;
        padding-bottom: 4px;
    }
    QScrollArea#ShortcutsScroll {
        background: transparent;
        border: none;
    }
    QWidget#ShortcutsContent {
        background: transparent;
    }
    QLabel#ShortcutsCategory {
        color: #8ab4d8;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 4px 2px 2px 2px;
    }
    QFrame#ShortcutsRow {
        background-color: #222228;
        border: 1px solid #2e2e36;
        border-radius: 5px;
    }
    QLabel#ShortcutsActionLabel {
        color: #e6e6ec;
        font-size: 12px;
    }
    QLabel#ShortcutsKeyBadge {
        background-color: #141418;
        color: #d0d0d8;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 3px 8px;
        font-size: 11px;
        font-family: Consolas, "Cascadia Mono", monospace;
        min-width: 72px;
    }
    QLabel#StatusKeyHints {
        color: #8a8a94;
        font-size: 11px;
        padding-right: 8px;
    }
"""

LAUNCHER_STYLE = """
    QWidget#ProjectLauncher {
        background-color: #16161a;
        color: #e8e8ee;
    }
    QLabel#LauncherBrand {
        color: #f2f2f6;
        font-size: 28px;
        font-weight: 700;
        letter-spacing: 1px;
    }
    QLabel#LauncherSubtitle {
        color: #8e8e98;
        font-size: 13px;
        padding-bottom: 8px;
    }
    QPushButton#LauncherPrimaryButton {
        background-color: #2b6ea8;
        color: #ffffff;
        border: 1px solid #3d7eb8;
        border-radius: 6px;
        padding: 12px 18px;
        font-size: 13px;
        font-weight: 600;
        text-align: left;
    }
    QPushButton#LauncherPrimaryButton:hover {
        background-color: #347ebc;
    }
    QPushButton#LauncherPrimaryButton:pressed {
        background-color: #245f92;
    }
    QPushButton#LauncherSecondaryButton {
        background-color: #222228;
        color: #e0e0e8;
        border: 1px solid #34343c;
        border-radius: 6px;
        padding: 12px 18px;
        font-size: 13px;
        font-weight: 600;
        text-align: left;
    }
    QPushButton#LauncherSecondaryButton:hover {
        background-color: #2a2a32;
        border-color: #45454f;
    }
    QLabel#LauncherRecentHeader {
        color: #9ecfff;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.6px;
        padding-top: 10px;
    }
    QListWidget#LauncherRecentList {
        background-color: #121216;
        border: 1px solid #2c2c34;
        border-radius: 6px;
        color: #e0e0e8;
        outline: none;
        padding: 4px;
    }
    QListWidget#LauncherRecentList::item {
        padding: 10px 12px;
        border-radius: 4px;
        margin: 2px 0px;
    }
    QListWidget#LauncherRecentList::item:selected {
        background-color: #2b6ea8;
        color: #ffffff;
    }
    QListWidget#LauncherRecentList::item:hover {
        background-color: #222228;
    }
    QLabel#LauncherEmptyRecent {
        color: #6e6e78;
        font-size: 12px;
        padding: 18px 8px;
    }
"""

BOOTLOADER_STYLE = """
    QWidget#BootloaderWindow {
        background-color: #121216;
        color: #e6e6ec;
    }
    QLabel#BootloaderTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#BootloaderStage {
        color: #9ecfff;
        font-size: 12px;
        font-weight: 600;
    }
    QPlainTextEdit#BootloaderLog {
        background-color: #0c0c10;
        color: #c8c8d0;
        border: 1px solid #2a2a32;
        border-radius: 6px;
        padding: 8px;
        font-family: Consolas, "Cascadia Mono", monospace;
        font-size: 12px;
        selection-background-color: #2b6ea8;
    }
    QProgressBar#BootloaderProgress {
        background-color: #1a1a20;
        border: 1px solid #2e2e36;
        border-radius: 4px;
        text-align: center;
        color: #d0d0d8;
        min-height: 16px;
        max-height: 16px;
    }
    QProgressBar#BootloaderProgress::chunk {
        background-color: #2b6ea8;
        border-radius: 3px;
    }
    QLabel#BootloaderStatus {
        color: #8a8a94;
        font-size: 11px;
    }
    QPushButton#BootloaderCancelButton {
        background-color: #222228;
        color: #d0d0d8;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 6px 14px;
        font-size: 12px;
    }
    QPushButton#BootloaderCancelButton:hover {
        background-color: #2c2c34;
    }
    QPushButton#BootloaderCancelButton:disabled {
        color: #666670;
        border-color: #2a2a32;
    }
"""

NODE_SEARCH_STYLE = """
    QFrame#NodeSearchPalette {
        background-color: #1e1e1e;
        border: 1px solid #3a3a42;
        border-radius: 8px;
    }
    QLabel#NodeSearchTitle {
        color: #c8c8d0;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.4px;
        padding-left: 2px;
    }
    QLineEdit#NodeSearchField {
        background-color: #141416;
        color: #eaeaf0;
        border: 1px solid #33333a;
        border-radius: 5px;
        padding: 7px 10px;
        selection-background-color: #2b6ea8;
        font-size: 13px;
    }
    QLineEdit#NodeSearchField:focus {
        border: 1px solid #3d7eb8;
    }
    QListWidget#NodeSearchList {
        background-color: #18181c;
        color: #e6e6e6;
        border: 1px solid #2c2c32;
        border-radius: 5px;
        outline: none;
        font-size: 12px;
        padding: 2px;
    }
    QListWidget#NodeSearchList::item {
        padding: 7px 8px;
        border-radius: 4px;
        margin: 1px 2px;
    }
    QListWidget#NodeSearchList::item:selected {
        background-color: #2b6ea8;
        color: #ffffff;
    }
    QListWidget#NodeSearchList::item:hover:!selected {
        background-color: #2a2a32;
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
        background-color: #1a1a1a;
        color: #d8d8d8;
        border: 1px solid #0a0a0a;
        border-right: 1px solid #2c2c2c;
        border-bottom: 1px solid #2c2c2c;
    }
    QDockWidget::title {
        background-color: #252525;
        color: #b8b8b8;
        padding: 1px 8px;
        border: none;
        border-top: 1px solid #343434;
        border-bottom: 1px solid #080808;
        font-weight: 600;
        font-size: 10px;
    }
    QDockWidget > QWidget {
        background-color: #1a1a1a;
        border: none;
        border-top: 1px solid #0a0a0a;
    }
"""

MENUBAR_STYLE = """
    QMenuBar {
        background-color: #1e1e1e;
        color: #e8e8e8;
        border-bottom: 1px solid #121212;
        spacing: 4px;
        padding: 4px 10px;
        font-size: 12px;
    }
    QMenuBar::item {
        background-color: transparent;
        color: #d0d0d0;
        padding: 5px 12px;
        border-radius: 4px;
        font-weight: 500;
    }
    QMenuBar::item:selected {
        background-color: #2b6ea8;
        color: #ffffff;
    }
    QMenuBar::item:pressed {
        background-color: #245f91;
        color: #ffffff;
    }
"""

TIMELINE_STYLE = """
    TimelineWidget {
        background-color: #1a1a1a;
    }
    QLabel#TimelineTimecodeLabel {
        color: #e8e8e8;
        font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
        font-size: 11px;
        font-weight: 600;
        padding: 1px 6px;
        background-color: #141414;
        border: 1px solid #2a2a2a;
        border-radius: 3px;
        min-width: 84px;
        max-height: 22px;
    }
    QLabel#TimelineFrameLabel {
        color: #8a8a8a;
        font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
        font-size: 10px;
        padding: 1px 4px;
        max-height: 22px;
    }
    QLabel#TimelineMetaLabel {
        color: #6e6e6e;
        font-size: 9px;
        padding: 0px 4px;
        max-height: 22px;
    }
    QPushButton#TimelineTransportButton {
        background-color: #252525;
        color: #d0d0d0;
        border: 1px solid #333333;
        border-radius: 3px;
        padding: 2px;
        min-width: 24px;
        max-width: 24px;
        min-height: 22px;
        max-height: 22px;
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
        border-radius: 3px;
        padding: 2px;
        min-width: 28px;
        max-width: 28px;
        min-height: 22px;
        max-height: 22px;
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
        border-radius: 3px;
        padding: 2px;
        min-width: 24px;
        max-width: 24px;
        min-height: 22px;
        max-height: 22px;
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
        border-radius: 3px;
        padding: 1px 6px;
        min-height: 22px;
        max-height: 22px;
        min-width: 56px;
        font-size: 10px;
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

PROPERTIES_STYLE = build_properties_style()

KEYFRAMES_PANEL_STYLE = """
    QWidget#KeyframesPanelWidget {
        background-color: #18181c;
    }
    QLabel#KeyframesHeader {
        color: #e8e8ec;
        font-size: 12px;
        font-weight: 600;
    }
    QWidget#KeyframesToolbar {
        background-color: #141418;
        border: 1px solid #2a2a32;
        border-radius: 4px;
        padding: 2px;
    }
    QComboBox#KeyframesPropertyCombo {
        background-color: #222228;
        color: #e0e0e8;
        border: 1px solid #34343c;
        border-radius: 4px;
        padding: 2px 6px;
        min-height: 22px;
        font-size: 11px;
    }
    QComboBox#KeyframesPropertyCombo::drop-down {
        border: none;
        width: 16px;
    }
    QPushButton#KeyframesActionButton {
        background-color: #222228;
        color: #d8d8e0;
        border: 1px solid #34343c;
        border-radius: 4px;
        padding: 2px 10px;
        min-height: 22px;
        font-size: 11px;
    }
    QPushButton#KeyframesActionButton:hover {
        background-color: #2a2a34;
        border-color: #45454f;
    }
    QPushButton#KeyframesActionButton:disabled {
        color: #666670;
        border-color: #2a2a30;
    }
    QFrame#KeyframesDivider {
        color: #2a2a32;
    }
    QScrollArea#KeyframesScroll {
        background-color: transparent;
        border: none;
    }
    QWidget#KeyframesContent {
        background-color: transparent;
    }
    QLabel#KeyframesEmptyState,
    QLabel#KeyframesHintLabel,
    QLabel#KeyframesEmptyLabel {
        color: #888890;
        font-size: 11px;
    }
    QLabel#KeyframePropertyLabel {
        color: #c8c8d0;
        font-size: 11px;
        font-weight: 600;
    }
    QPushButton#KeyframeFrameChip {
        background-color: #222228;
        color: #ffbe3c;
        border: 1px solid #8a7030;
        border-radius: 3px;
        padding: 0 8px;
        font-size: 10px;
        min-width: 28px;
    }
    QPushButton#KeyframeFrameChip:hover {
        background-color: #2c2c36;
        border-color: #ffbe3c;
    }
    QPushButton#KeyframeFrameChip[current="true"] {
        background-color: #ffbe3c;
        color: #141418;
        border-color: #ffd878;
        font-weight: 600;
    }
    QPushButton#KeyframeMiniButton {
        background-color: #222228;
        color: #ffbe3c;
        border: 1px solid #34343c;
        border-radius: 3px;
        font-size: 12px;
        font-weight: 600;
    }
    QPushButton#KeyframeMiniButton:hover {
        border-color: #ffbe3c;
    }
"""

LOG_VIEWER_STYLE = """
    QWidget#LogViewerWidget {
        background-color: #121216;
    }
    QWidget#LogViewerToolbar {
        background-color: #18181c;
        border-bottom: 1px solid #2a2a32;
    }
    QPlainTextEdit#LogViewerTerminal {
        background-color: #0c0c10;
        color: #c8c8d0;
        border: none;
        padding: 6px 8px;
        font-family: Consolas, "Cascadia Mono", monospace;
        font-size: 11px;
        selection-background-color: #2b6ea8;
    }
    QCheckBox#LogViewerAutoScroll {
        color: #b0b0b8;
        font-size: 11px;
        spacing: 5px;
    }
    QCheckBox#LogViewerAutoScroll::indicator {
        width: 13px;
        height: 13px;
        border-radius: 2px;
        border: 1px solid #3a3a3a;
        background-color: #141414;
    }
    QCheckBox#LogViewerAutoScroll::indicator:checked {
        background-color: #2b6ea8;
        border-color: #3d7eb8;
    }
    QPushButton#LogViewerClearButton {
        background-color: #222228;
        color: #d8d8e0;
        border: 1px solid #34343c;
        border-radius: 4px;
        padding: 2px 10px;
        min-height: 20px;
        max-height: 22px;
        font-size: 11px;
    }
    QPushButton#LogViewerClearButton:hover {
        background-color: #2a2a32;
        border-color: #45454f;
    }
    QPushButton#LogViewerClearButton:pressed {
        background-color: #1a1a20;
    }
"""

TOOLBAR_STYLE = """
    QToolBar#PinBar {
        background-color: #252525;
        border: none;
        border-bottom: 1px solid #3a3a3a;
        spacing: 2px;
        padding: 3px 8px;
    }
    QToolBar#PinBar::separator {
        background-color: #3a3a3a;
        width: 1px;
        margin: 4px 6px;
    }
    QToolBar#PinBar QToolButton {
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px 6px;
        margin: 0px 1px;
        color: #d8d8d8;
    }
    QToolBar#PinBar QToolButton:hover {
        background-color: #333333;
        border-color: #444444;
    }
    QToolBar#PinBar QToolButton:pressed {
        background-color: #0078d4;
        border-color: #0078d4;
    }
    QToolBar#PinBar QToolButton:disabled {
        color: #666666;
    }
"""

PIN_BAR_DIALOG_STYLE = """
    QDialog#PinBarDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QLabel#PinBarDialogTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#PinBarDialogSubtitle {
        color: #9a9aa4;
        font-size: 12px;
        padding-bottom: 4px;
    }
    QScrollArea#PinBarScroll {
        background: transparent;
        border: none;
    }
    QWidget#PinBarContent {
        background: transparent;
    }
    QLabel#PinBarCategory {
        color: #8ab4d8;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 4px 2px 2px 2px;
    }
    QCheckBox#PinBarCheckbox {
        color: #e6e6ec;
        font-size: 12px;
        padding: 5px 8px;
        background-color: #222228;
        border: 1px solid #2e2e36;
        border-radius: 5px;
    }
    QCheckBox#PinBarCheckbox:hover {
        border-color: #444450;
    }
"""

STATUS_BAR_STYLE = """
    QStatusBar {
        background-color: #007acc;
        color: #ffffff;
        font-size: 11px;
        border-top: 1px solid #005a9e;
    }
    QStatusBar::item {
        border: none;
    }
    QLabel#StatusProjectInfo {
        color: #e8f4ff;
        font-size: 11px;
        padding-left: 4px;
    }
    QLabel#StatusPlayhead {
        color: #ffffff;
        font-size: 11px;
        font-weight: 600;
        padding: 0px 8px;
    }
    QLabel#StatusCacheInfo {
        color: #c8e4ff;
        font-size: 11px;
        padding-right: 8px;
    }
    QLabel#StatusSeparator {
        color: #66b3ff;
        padding: 0px 4px;
    }
"""

PLUGIN_SURFACE_STYLE = """
    QWidget#PluginSurface {
        background-color: transparent;
        color: #e6e6e6;
    }
    QLabel#PluginSurfaceLabel {
        color: #c8c8d0;
        font-size: 12px;
    }
    QPushButton#PluginSurfaceButton {
        background-color: #2a2a32;
        color: #e6e6e6;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 4px 10px;
        min-height: 24px;
    }
    QPushButton#PluginSurfaceButton:hover {
        background-color: #3a3a44;
    }
    QLineEdit#PluginSurfaceText {
        background-color: #1a1a1e;
        color: #e6e6e6;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 24px;
    }
    QFrame#PluginSurfaceDivider {
        color: #3a3a44;
    }
"""

PLUGIN_DIALOG_STYLE = """
    QDialog#PluginPopupDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
"""

ABOUT_DIALOG_STYLE = """
    QDialog#AboutDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QLabel#AboutTitle {
        color: #f0f0f4;
        font-size: 20px;
        font-weight: 600;
    }
    QLabel#AboutVersion {
        color: #8ab4d8;
        font-size: 12px;
    }
    QLabel#AboutBody {
        color: #b0b0b8;
        font-size: 12px;
        line-height: 1.4;
    }
"""

PROJECT_SETTINGS_STYLE = """
    QDialog#ProjectSettingsDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QLabel#ProjectSettingsTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QGroupBox {
        color: #c8c8d0;
        border: 1px solid #34343c;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 12px;
        font-size: 11px;
        font-weight: 600;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }
"""

EXPORT_DIALOG_STYLE = """
    QDialog#ExportDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QLabel#ExportDialogTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#ExportStatusLabel {
        color: #b8b8c0;
    }
    QProgressBar#ExportProgress {
        background-color: #141418;
        border: 1px solid #34343c;
        border-radius: 4px;
        text-align: center;
        color: #d0d0d8;
        min-height: 18px;
    }
    QProgressBar#ExportProgress::chunk {
        background-color: #0078d4;
        border-radius: 3px;
    }
"""

# Shares the export dialog's visual language (dark surface, same progress
# bar look) for the tracking progress dialog's own object names.
TRACKING_DIALOG_STYLE = """
    QDialog#TrackingProgressDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QLabel#ExportDialogTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#ExportStatusLabel {
        color: #b8b8c0;
    }
    QProgressBar#ExportProgress {
        background-color: #141418;
        border: 1px solid #34343c;
        border-radius: 4px;
        text-align: center;
        color: #d0d0d8;
        min-height: 18px;
    }
    QProgressBar#ExportProgress::chunk {
        background-color: #0078d4;
        border-radius: 3px;
    }
"""

MEDIA_POOL_STYLE = """
    QWidget#MediaPoolWidget {
        background-color: #1a1a1a;
        color: #e0e0e0;
    }
    QListWidget#MediaPoolList {
        background-color: #141414;
        border: 1px solid #2a2a2a;
        border-radius: 4px;
        outline: none;
        font-size: 12px;
    }
    QListWidget#MediaPoolList::item {
        padding: 6px 8px;
        border-bottom: 1px solid #222222;
    }
    QListWidget#MediaPoolList::item:selected {
        background-color: #0078d4;
        color: #ffffff;
    }
    QListWidget#MediaPoolList::item:hover:!selected {
        background-color: #252528;
    }
    QLabel#MediaPoolEmpty {
        color: #777777;
        font-size: 11px;
        padding: 8px;
    }
    QPushButton#MediaPoolRefreshButton {
        background-color: #222228;
        color: #d8d8e0;
        border: 1px solid #34343c;
        border-radius: 4px;
        padding: 2px 10px;
        min-height: 20px;
        font-size: 11px;
    }
    QPushButton#MediaPoolRefreshButton:hover {
        background-color: #2a2a32;
    }
"""
