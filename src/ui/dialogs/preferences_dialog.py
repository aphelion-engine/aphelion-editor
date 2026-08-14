"""Editor preferences dialog with settings, keybinds, theme, and node colors."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_io.theme_file import APH_THEME_FILTER, ThemeFileError, load_theme_file, save_theme_file
from config.constants import (
    FRAME_CACHE_MAX_ALLOWED_MB,
    FRAME_CACHE_MIN_MB,
    MAX_DECODE_CACHE_FRAMES,
    MAX_MAX_PREFETCH_FRAMES,
)
from config.keybinds import KeyAction, KeybindStore, NodeCreateSlot
from config.theme_engine import build_theme_styles
from config.theme_tokens import BUILTIN_THEMES, ThemeTokens, builtin_theme
from core.nodes.registry import NodeInfo, global_node_registry
from core.preferences.models import (
    AppPreferences,
    EditorSettings,
    PerformanceSettings,
    ThemeSettings,
)
from ui.dialogs.plugin_preferences_tab import PluginPreferencesPage
from ui.widgets.key_capture import KeyCaptureEdit


class PreferencesDialog(QDialog):
    """Modal preferences editor for settings, plugins, keybinds, themes, and node colors."""

    applied = pyqtSignal()
    plugins_reloaded = pyqtSignal(int)

    def __init__(
        self,
        preferences: AppPreferences,
        keybinds: KeybindStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._working = deepcopy(preferences)
        self._keybinds = keybinds
        self._draft_keybinds = self._clone_keybinds(keybinds)
        self._theme_tokens = self._working.theme.resolved_tokens()
        self._node_color_widgets: dict[str, QPushButton] = {}
        self._key_fields: dict[KeyAction, KeyCaptureEdit] = {}
        self._slot_fields: dict[str, KeyCaptureEdit] = {}
        self._plugin_page = PluginPreferencesPage(self._working.plugins)
        self._plugin_page.plugins_reloaded.connect(self.plugins_reloaded.emit)

        self.setObjectName("PreferencesDialog")
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.resize(640, 560)
        self._apply_dialog_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Preferences")
        title.setObjectName("PreferencesTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.setObjectName("PreferencesTabs")
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_performance_tab(), "Performance")
        tabs.addTab(self._plugin_page, "Plugins")
        tabs.addTab(self._build_keybinds_tab(), "Keybinds")
        tabs.addTab(self._build_theme_tab(), "Appearance")
        tabs.addTab(self._build_node_colors_tab(), "Node Colors")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.clicked.connect(self._on_apply_clicked)
        root.addWidget(buttons)

    @property
    def preferences(self) -> AppPreferences:
        """Return the edited preference document."""
        return self._working

    @property
    def keybinds(self) -> KeybindStore:
        """Return the draft keybind store edited in the dialog."""
        return self._draft_keybinds

    @property
    def plugins_were_reloaded(self) -> bool:
        """Return whether the user reloaded plugins during this session."""
        return self._plugin_page.did_reload

    def _apply_dialog_style(self) -> None:
        styles = build_theme_styles(self._theme_tokens)
        self.setStyleSheet(styles.preferences)

    def _clone_keybinds(self, source: KeybindStore) -> KeybindStore:
        clone = KeybindStore()
        for action in KeyAction:
            clone.set_sequence(action, source.sequence(action))
        for slot in source.node_create_slots():
            clone.set_node_create_sequence(slot.slot_id, slot.sequence)
            if slot.target.is_bound:
                clone.set_node_create_target(
                    slot.slot_id,
                    slot.target.node_type,
                    slot.target.node_category,
                )
            else:
                clone.clear_node_create_target(slot.slot_id)
        return clone

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)

        group = QGroupBox("Editor")
        group.setObjectName("PreferencesGroup")
        form = QFormLayout(group)
        settings = self._working.editor

        self._font_family = QComboBox()
        self._font_family.setObjectName("PreferencesCombo")
        self._font_family.setEditable(True)
        for family in ("JetBrains Mono", "Cascadia Mono", "Consolas", "Segoe UI"):
            self._font_family.addItem(family)
        self._font_family.setCurrentText(settings.editor_font_family)
        form.addRow("Font family", self._font_family)

        self._font_size = QSpinBox()
        self._font_size.setObjectName("PreferencesSpin")
        self._font_size.setRange(9, 24)
        self._font_size.setValue(settings.editor_font_size)
        form.addRow("Font size", self._font_size)

        self._show_grid = QCheckBox("Show node graph grid")
        self._show_grid.setChecked(settings.show_graph_grid)
        form.addRow(self._show_grid)

        self._show_hints = QCheckBox("Show status bar key hints")
        self._show_hints.setChecked(settings.show_status_key_hints)
        form.addRow(self._show_hints)

        self._autosave_enabled = QCheckBox("Enable project autosave")
        self._autosave_enabled.setChecked(settings.autosave_enabled)
        form.addRow(self._autosave_enabled)

        self._autosave_interval = QSpinBox()
        self._autosave_interval.setObjectName("PreferencesSpin")
        self._autosave_interval.setRange(5, 600)
        self._autosave_interval.setSuffix(" sec")
        self._autosave_interval.setValue(max(5, settings.autosave_interval_ms // 1000))
        form.addRow("Autosave interval", self._autosave_interval)

        layout.addWidget(group)
        hint = QLabel("Changes apply when you click Apply or OK.")
        hint.setObjectName("PreferencesHint")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_performance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        perf = self._working.performance

        memory_group = QGroupBox("Memory")
        memory_group.setObjectName("PreferencesGroup")
        memory_form = QFormLayout(memory_group)

        self._frame_cache_mb = QSpinBox()
        self._frame_cache_mb.setObjectName("PreferencesSpin")
        self._frame_cache_mb.setRange(FRAME_CACHE_MIN_MB, FRAME_CACHE_MAX_ALLOWED_MB)
        self._frame_cache_mb.setSingleStep(256)
        self._frame_cache_mb.setSuffix(" MB")
        self._frame_cache_mb.setValue(perf.frame_cache_mb)
        memory_form.addRow("Frame cache budget", self._frame_cache_mb)

        self._decode_cache_frames = QSpinBox()
        self._decode_cache_frames.setObjectName("PreferencesSpin")
        self._decode_cache_frames.setRange(1, MAX_DECODE_CACHE_FRAMES)
        self._decode_cache_frames.setSuffix(" frames")
        self._decode_cache_frames.setValue(perf.decode_cache_frames)
        memory_form.addRow("Source decode cache", self._decode_cache_frames)

        layout.addWidget(memory_group)

        playback_group = QGroupBox("Playback")
        playback_group.setObjectName("PreferencesGroup")
        playback_form = QFormLayout(playback_group)

        self._max_prefetch = QSpinBox()
        self._max_prefetch.setObjectName("PreferencesSpin")
        self._max_prefetch.setRange(0, MAX_MAX_PREFETCH_FRAMES)
        self._max_prefetch.setSuffix(" frames")
        self._max_prefetch.setValue(perf.max_prefetch_frames)
        playback_form.addRow("Max prefetch ahead", self._max_prefetch)

        self._drop_frames = QCheckBox("Drop frames to keep playback fluid")
        self._drop_frames.setChecked(perf.drop_frames_during_playback)
        playback_form.addRow(self._drop_frames)

        self._hardware_decode = QCheckBox("Use hardware-accelerated decode (if available)")
        self._hardware_decode.setChecked(perf.hardware_decode_enabled)
        playback_form.addRow(self._hardware_decode)

        self._show_overlay = QCheckBox("Show performance overlay in viewport")
        self._show_overlay.setChecked(perf.show_performance_overlay)
        playback_form.addRow(self._show_overlay)

        layout.addWidget(playback_group)

        proxy_group = QGroupBox("Playback Proxy Override")
        proxy_group.setObjectName("PreferencesGroup")
        proxy_form = QFormLayout(proxy_group)

        self._proxy_override_enabled = QCheckBox(
            "Force a lower decode width while playing"
        )
        self._proxy_override_enabled.setChecked(perf.playback_proxy_override_enabled)
        proxy_form.addRow(self._proxy_override_enabled)

        self._proxy_width = QSpinBox()
        self._proxy_width.setObjectName("PreferencesSpin")
        self._proxy_width.setRange(160, 1920)
        self._proxy_width.setSingleStep(80)
        self._proxy_width.setSuffix(" px")
        self._proxy_width.setValue(perf.playback_proxy_width)
        self._proxy_width.setEnabled(perf.playback_proxy_override_enabled)
        self._proxy_override_enabled.toggled.connect(self._proxy_width.setEnabled)
        proxy_form.addRow("Playback width", self._proxy_width)

        proxy_hint = QLabel(
            "Applies only while actively playing; paused review still uses"
            " each Viewer's own Proxy Width."
        )
        proxy_hint.setObjectName("PreferencesHint")
        proxy_hint.setWordWrap(True)
        proxy_form.addRow(proxy_hint)

        layout.addWidget(proxy_group)
        hint = QLabel(
            "Higher cache and prefetch values trade RAM for smoother scrubbing"
            " and playback. Changes apply when you click Apply or OK."
        )
        hint.setObjectName("PreferencesHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_keybinds_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("PreferencesScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        for category, specs in self._draft_keybinds.specs_by_category():
            header = QLabel(category)
            header.setObjectName("PreferencesHint")
            layout.addWidget(header)
            for spec in specs:
                layout.addWidget(self._keybind_row(spec.action, spec.label))

        slot_header = QLabel("Create Node")
        slot_header.setObjectName("PreferencesHint")
        layout.addWidget(slot_header)
        for slot in self._draft_keybinds.node_create_slots():
            layout.addWidget(self._slot_row(slot))

        reset = QPushButton("Reset All Keybinds to Defaults")
        reset.setObjectName("PreferencesSecondaryButton")
        reset.clicked.connect(self._reset_keybinds)
        layout.addWidget(reset)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _keybind_row(self, action: KeyAction, label: str) -> QFrame:
        row = QFrame()
        row.setObjectName("PreferencesRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.addWidget(QLabel(label), 1)
        field = KeyCaptureEdit(self._draft_keybinds.sequence(action))
        field.sequence_changed.connect(
            lambda seq, act=action: self._draft_keybinds.set_sequence(act, seq)
        )
        self._key_fields[action] = field
        row_layout.addWidget(field)
        return row

    def _slot_row(self, slot: NodeCreateSlot) -> QFrame:
        row = QFrame()
        row.setObjectName("PreferencesRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.addWidget(QLabel(slot.display_label()), 1)
        field = KeyCaptureEdit(slot.sequence)
        field.sequence_changed.connect(
            lambda seq, sid=slot.slot_id: self._draft_keybinds.set_node_create_sequence(
                sid, seq
            )
        )
        self._slot_fields[slot.slot_id] = field
        row_layout.addWidget(field)
        return row

    def _build_theme_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)

        group = QGroupBox("Theme")
        group.setObjectName("PreferencesGroup")
        form = QFormLayout(group)

        self._theme_combo = QComboBox()
        self._theme_combo.setObjectName("PreferencesCombo")
        for theme_id, tokens in BUILTIN_THEMES.items():
            self._theme_combo.addItem(tokens.display_name, theme_id)
        self._theme_combo.addItem("Custom", "custom")
        index = self._theme_combo.findData(self._working.theme.active_theme_id)
        if index >= 0:
            self._theme_combo.setCurrentIndex(index)
        elif self._working.theme.custom_tokens is not None:
            self._theme_combo.setCurrentIndex(self._theme_combo.findData("custom"))
        self._theme_combo.currentIndexChanged.connect(self._on_theme_preset_changed)
        form.addRow("Preset", self._theme_combo)

        self._accent_btn = self._color_button(self._theme_tokens.accent)
        self._accent_btn.clicked.connect(lambda: self._pick_theme_color("accent"))
        form.addRow("Accent", self._accent_btn)

        self._window_btn = self._color_button(self._theme_tokens.window_bg)
        self._window_btn.clicked.connect(lambda: self._pick_theme_color("window_bg"))
        form.addRow("Window background", self._window_btn)

        self._panel_btn = self._color_button(self._theme_tokens.panel_bg)
        self._panel_btn.clicked.connect(lambda: self._pick_theme_color("panel_bg"))
        form.addRow("Panel background", self._panel_btn)

        self._graph_btn = self._color_button(self._rgb_hex(self._theme_tokens.graph_bg_rgb))
        self._graph_btn.clicked.connect(lambda: self._pick_theme_color("graph_bg_rgb"))
        form.addRow("Graph background", self._graph_btn)

        layout.addWidget(group)

        file_row = QHBoxLayout()
        import_btn = QPushButton("Import .aph.theme…")
        import_btn.setObjectName("PreferencesSecondaryButton")
        import_btn.clicked.connect(self._import_theme)
        export_btn = QPushButton("Export .aph.theme…")
        export_btn.setObjectName("PreferencesSecondaryButton")
        export_btn.clicked.connect(self._export_theme)
        file_row.addWidget(import_btn)
        file_row.addWidget(export_btn)
        file_row.addStretch(1)
        layout.addLayout(file_row)
        layout.addStretch(1)
        return page

    def _build_node_colors_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("PreferencesScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        hint = QLabel("Customize header accent colors per node type.")
        hint.setObjectName("PreferencesHint")
        layout.addWidget(hint)

        grouped: dict[str, list[NodeInfo]] = {}
        for info in global_node_registry.get_all_nodes().values():
            grouped.setdefault(info.category, []).append(info)

        for category in sorted(grouped):
            header = QLabel(category)
            header.setObjectName("PreferencesHint")
            layout.addWidget(header)
            for info in sorted(grouped[category], key=lambda item: item.name):
                layout.addWidget(self._node_color_row(info))

        reset = QPushButton("Reset Node Colors to Defaults")
        reset.setObjectName("PreferencesSecondaryButton")
        reset.clicked.connect(self._reset_node_colors)
        layout.addWidget(reset)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _node_color_row(self, info: NodeInfo) -> QFrame:
        key = f"{info.category}.{info.name}"
        rgb = self._resolve_node_color(key, info.color)
        row = QFrame()
        row.setObjectName("PreferencesRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.addWidget(QLabel(info.name), 1)
        button = self._color_button(self._rgb_hex(rgb))
        button.clicked.connect(lambda _checked=False, k=key, d=info.color: self._pick_node_color(k, d))
        self._node_color_widgets[key] = button
        row_layout.addWidget(button)
        return row

    def _resolve_node_color(
        self,
        key: str,
        default: tuple[int, int, int],
    ) -> tuple[int, int, int]:
        override = self._working.node_colors.get(key)
        if override and len(override) >= 3:
            return (int(override[0]), int(override[1]), int(override[2]))
        return default

    @staticmethod
    def _color_button(hex_color: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("PreferencesSecondaryButton")
        button.setFixedSize(72, 24)
        button.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #555;")
        return button

    @staticmethod
    def _rgb_hex(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    def _on_theme_preset_changed(self) -> None:
        theme_id = str(self._theme_combo.currentData())
        if theme_id == "custom":
            return
        preset = builtin_theme(theme_id)
        if preset is None:
            return
        self._theme_tokens = preset
        self._refresh_theme_buttons()

    def _refresh_theme_buttons(self) -> None:
        self._accent_btn.setStyleSheet(
            f"background-color: {self._theme_tokens.accent}; border: 1px solid #555;"
        )
        self._window_btn.setStyleSheet(
            f"background-color: {self._theme_tokens.window_bg}; border: 1px solid #555;"
        )
        self._panel_btn.setStyleSheet(
            f"background-color: {self._theme_tokens.panel_bg}; border: 1px solid #555;"
        )
        self._graph_btn.setStyleSheet(
            f"background-color: {self._rgb_hex(self._theme_tokens.graph_bg_rgb)}; border: 1px solid #555;"
        )
        self._apply_dialog_style()

    def _pick_theme_color(self, field: str) -> None:
        if field == "graph_bg_rgb":
            current = QColor(*self._theme_tokens.graph_bg_rgb)
        else:
            current = QColor(str(getattr(self._theme_tokens, field)))
        picked = QColorDialog.getColor(current, self, "Pick Color")
        if not picked.isValid():
            return
        if field == "graph_bg_rgb":
            self._theme_tokens.graph_bg_rgb = (picked.red(), picked.green(), picked.blue())
        else:
            setattr(self._theme_tokens, field, picked.name())
        self._theme_combo.setCurrentIndex(self._theme_combo.findData("custom"))
        self._theme_tokens.theme_id = "custom"
        self._theme_tokens.display_name = "Custom"
        self._refresh_theme_buttons()

    def _pick_node_color(self, key: str, default: tuple[int, int, int]) -> None:
        rgb = self._resolve_node_color(key, default)
        picked = QColorDialog.getColor(QColor(*rgb), self, "Pick Node Color")
        if not picked.isValid():
            return
        self._working.node_colors[key] = [
            picked.red(),
            picked.green(),
            picked.blue(),
        ]
        button = self._node_color_widgets.get(key)
        if button is not None:
            button.setStyleSheet(
                f"background-color: {picked.name()}; border: 1px solid #555;"
            )

    def _reset_keybinds(self) -> None:
        self._draft_keybinds.reset_to_defaults()
        for action, field in self._key_fields.items():
            field.set_sequence(self._draft_keybinds.sequence(action))
        for slot_id, field in self._slot_fields.items():
            slot = self._draft_keybinds.get_node_create_slot(slot_id)
            if slot is not None:
                field.set_sequence(slot.sequence)

    def _reset_node_colors(self) -> None:
        self._working.node_colors.clear()
        for key, button in self._node_color_widgets.items():
            category, name = key.split(".", 1)
            info = global_node_registry.get_node_info(category, name)
            if info is None:
                continue
            button.setStyleSheet(
                f"background-color: {self._rgb_hex(info.color)}; border: 1px solid #555;"
            )

    def _import_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Theme",
            "",
            APH_THEME_FILTER,
        )
        if not path:
            return
        try:
            tokens = load_theme_file(Path(path))
        except ThemeFileError as exc:
            return
        self._theme_tokens = tokens
        self._theme_combo.setCurrentIndex(self._theme_combo.findData("custom"))
        self._refresh_theme_buttons()
        if tokens.node_colors:
            self._working.node_colors.update(tokens.node_colors)

    def _export_theme(self) -> None:
        self._collect_preferences()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Theme",
            f"{self._theme_tokens.display_name}.aph.theme",
            APH_THEME_FILTER,
        )
        if not path:
            return
        export_path = Path(path)
        if export_path.suffix != ".theme":
            export_path = export_path.with_suffix(".aph.theme")
        tokens = ThemeTokens.from_dict(self._theme_tokens.to_dict())
        tokens.node_colors = dict(self._working.node_colors)
        save_theme_file(export_path, tokens)

    def _collect_preferences(self) -> None:
        self._working.editor = EditorSettings(
            editor_font_family=self._font_family.currentText().strip() or "JetBrains Mono",
            editor_font_size=int(self._font_size.value()),
            show_graph_grid=self._show_grid.isChecked(),
            autosave_enabled=self._autosave_enabled.isChecked(),
            autosave_interval_ms=int(self._autosave_interval.value()) * 1000,
            show_status_key_hints=self._show_hints.isChecked(),
            # Not edited by any control in this dialog (toggled from the
            # toolbar instead) — carry the current value forward so saving
            # Preferences can never silently reset pin-bar visibility.
            show_pin_bar=self._working.editor.show_pin_bar,
        )
        self._working.performance = PerformanceSettings(
            frame_cache_mb=int(self._frame_cache_mb.value()),
            decode_cache_frames=int(self._decode_cache_frames.value()),
            max_prefetch_frames=int(self._max_prefetch.value()),
            hardware_decode_enabled=self._hardware_decode.isChecked(),
            playback_proxy_override_enabled=self._proxy_override_enabled.isChecked(),
            playback_proxy_width=int(self._proxy_width.value()),
            drop_frames_during_playback=self._drop_frames.isChecked(),
            show_performance_overlay=self._show_overlay.isChecked(),
        )
        theme_id = str(self._theme_combo.currentData())
        if theme_id == "custom":
            custom = ThemeTokens.from_dict(self._theme_tokens.to_dict())
            self._working.theme = ThemeSettings(
                active_theme_id="aphelion_dark",
                custom_tokens=custom,
            )
        else:
            self._working.theme = ThemeSettings(
                active_theme_id=theme_id,
                custom_tokens=None,
            )
        self._working.plugins = self._plugin_page.collect_settings()

    def _on_apply_clicked(self) -> None:
        self._collect_preferences()
        self.applied.emit()

    def accept(self) -> None:
        self._collect_preferences()
        super().accept()
