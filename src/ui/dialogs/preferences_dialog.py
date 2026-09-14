"""Editor preferences dialog with settings, keybinds, theme, and node colors."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from app_io.theme_file import (APH_THEME_FILTER, ThemeFileError,
                               load_theme_file, save_theme_file)
from config.constants import (FRAME_CACHE_MAX_ALLOWED_MB, FRAME_CACHE_MIN_MB,
                              MAX_DECODE_CACHE_FRAMES, MAX_MAX_PREFETCH_FRAMES,
                              MAX_PREFETCH_MAX_MB)
from config.keybinds import KeyAction, KeybindStore, NodeCreateSlot
from config.theme_engine import build_theme_styles
from config.theme_tokens import BUILTIN_THEMES, ThemeTokens, builtin_theme
from core.nodes.registry import NodeInfo, global_node_registry
from core.perf.capabilities import detect_capabilities
from core.perf.frame_drop import FrameDropMode
from core.perf.presets import (PerformanceProfile, apply_profile,
                               recommend_profile)
from core.perf.scheduler import MAX_WORKER_THREADS
from core.preferences.models import (AppPreferences, AudioSettings,
                                     EditorSettings, PerformanceSettings,
                                     ThemeSettings)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                             QDialogButtonBox, QFileDialog, QFormLayout,
                             QFrame, QGroupBox, QHBoxLayout, QLabel,
                             QMessageBox, QPushButton, QScrollArea, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)
from ui.dialogs.plugin_preferences_tab import PluginPreferencesPage
from ui.node_graph import operations as node_ops
from ui.widgets.key_capture import KeyCaptureEdit


class PreferencesDialog(QDialog):
    """Modal preferences editor for settings, plugins, keybinds, themes, and node colors."""

    applied = pyqtSignal()
    #: Requested when the user presses "Clear All Caches". Handled by the
    #: editor, which owns the live project and decoder caches.
    clear_caches_requested = pyqtSignal()
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
        # Show an explicit resize grip and allow the dialog to shrink down to
        # a compact height; tab pages scroll instead of forcing a tall window.
        self.setSizeGripEnabled(True)
        self.setMinimumSize(520, 340)
        self.resize(700, 420)
        self._apply_dialog_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Preferences")
        title.setObjectName("PreferencesTitle")
        root.addWidget(title)
        tabs = QTabWidget()
        tabs.setObjectName("PreferencesTabs")
        tabs.addTab(self._scrollable(self._build_general_tab()), "General")
        tabs.addTab(self._scrollable(
            self._build_node_graph_tab()), "Node Graph")
        tabs.addTab(self._scrollable(
            self._build_performance_tab()), "Performance")
        tabs.addTab(self._scrollable(self._build_audio_tab()), "Audio")
        tabs.addTab(self._scrollable(self._plugin_page), "Plugins")
        tabs.addTab(self._build_keybinds_tab(), "Keybinds")
        tabs.addTab(self._scrollable(self._build_theme_tab()), "Appearance")
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
        from ui.widgets.tooltips import apply_form_tooltips
        help_text = {
            self._profile_combo: "Bundled performance postures. Eco favours responsiveness on modest hardware; Maximum uses extra RAM and workers on capable machines.",
            self._frame_cache_mb: "Maximum RAM for evaluated frames, including audio. Larger budgets retain more reusable frames; leave memory for the OS and other apps.",
            self._decode_cache_frames: "Decoded source frames retained per decoder. High values increase RAM usage, especially with multiple high-resolution clips.",
            self._max_prefetch: "Maximum future frames evaluated in the background. Lower this for heavy graphs; overloaded playback skips prefetch automatically.",
            self._drop_mode: "How aggressively playback skips late frames. Adaptive adjusts itself from measured frame cost; Off never drops (heavy graphs may play slowly).",
            self._high_quality_paused: "Show the fast preview immediately on pause, then render the current frame at full quality in the background.",
            self._scrub_quality: "Preview resolution used while dragging the playhead. Lower values make scrubbing more responsive.",
            self._high_quality_after_scrub: "Render the frame under the playhead at full quality after a drag ends.",
            self._worker_threads: "Worker threads for background jobs. Auto leaves capacity for the UI, decoder, FFmpeg, and OpenCV.",
            self._pause_background: "Hold low-priority jobs (media probing, cache warming) while playback is running.",
            self._use_proxies: "Decode from a generated all-intra proxy when one exists. Cuts seek and decode cost dramatically on long-GOP camera media.",
            self._generate_proxies: "Create proxies in the background as media enters a project. Generation yields to playback.",
            self._proxy_height: "Resolution of generated proxies. Lower is faster to scrub; 540p is a good default for 1080p and 4K sources.",
            self._render_cache_mode: "Off never caches. Smart detects branches that cannot meet the frame deadline and caches them. User caches what you mark.",
            self._disk_cache_limit: "Maximum disk space for generated proxies and render cache.",
            self._hardware_decode: "Request hardware video decoding where supported; unsupported codecs or devices may use software decoding.",
            self._show_overlay: "Show actual displayed FPS, preview dimensions, and frame-cache memory usage in the viewport.",
            self._adaptive_preview: "When rendering misses the frame budget, reduce preview resolution with hysteresis. Pausing restores the normal preview width. Exports are unaffected.",
            self._proxy_override_enabled: "Use the selected lower preview width during playback and restore the Viewer width when paused. Does not change export resolution.",
            self._proxy_width: "Maximum playback preview width in pixels. Smaller frames reduce decoding and effect-processing work.",
            self._latency_preset: "Lower latency responds sooner; a safer, larger audio buffer tolerates processing delays better.",
            self._buffer_size: "Number of audio chunks queued ahead. More chunks help absorb timing jitter but increase playback latency.",
            self._master_volume: "Master preview audio gain. 100% keeps the source level; values above 100% amplify it.",
        }
        for widget, text in help_text.items():
            widget.setToolTip(text)
        apply_form_tooltips(self)


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

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        """Wrap a tab page so the dialog can stay short and scroll its body."""
        scroll = QScrollArea()
        scroll.setObjectName("PreferencesScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

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

    def _build_node_graph_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)

        group = QGroupBox("Graph Layout")
        group.setObjectName("PreferencesGroup")
        form = QFormLayout(group)

        settings = self._working.editor

        # Combo box for layout mode
        self._graph_layout_combo = QComboBox()
        self._graph_layout_combo.setObjectName("PreferencesCombo")

        # Populate with enum values
        for mode in node_ops.GraphLayoutMode:
            self._graph_layout_combo.addItem(mode.name.replace("_", " ").title(), mode)

        # Set current value
        index = self._graph_layout_combo.findData(settings.graph_layout_mode)
        if index >= 0:
            self._graph_layout_combo.setCurrentIndex(index)

        form.addRow("Organization algorithm", self._graph_layout_combo)

        # Optional: show grid toggle (already exists in General tab)
        # But many editors put it here too
        self._graph_show_grid = QCheckBox("Show background grid")
        self._graph_show_grid.setChecked(settings.show_graph_grid)
        form.addRow(self._graph_show_grid)

        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _build_performance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        perf = self._working.performance

        # ------------------------------------------------------------------
        # Profile
        # ------------------------------------------------------------------
        profile_group = QGroupBox("Performance Profile")
        profile_group.setObjectName("PreferencesGroup")
        profile_form = QFormLayout(profile_group)

        self._profile_combo = QComboBox()
        for profile in PerformanceProfile:
            self._profile_combo.addItem(profile.label, profile.value)
        index = self._profile_combo.findData(perf.performance_profile)
        self._profile_combo.setCurrentIndex(max(0, index))
        self._profile_combo.currentIndexChanged.connect(
            self._on_profile_selected)
        profile_form.addRow("Profile", self._profile_combo)

        auto_button = QPushButton("Auto Configure for This Computer")
        auto_button.setToolTip(
            "Detect CPU, memory, GPU and FFmpeg hardware encoders, then pick"
            " the profile and cache sizes that suit this machine."
        )
        auto_button.clicked.connect(self._auto_configure_performance)
        profile_form.addRow(auto_button)

        self._hardware_summary = QLabel(self._hardware_summary_text())
        self._hardware_summary.setObjectName("PreferencesHint")
        self._hardware_summary.setWordWrap(True)
        profile_form.addRow(self._hardware_summary)

        low_lag = QPushButton("Use low-lag preset")
        low_lag.setToolTip(
            "Apply the Eco profile: reduced preview resolution and prefetch,"
            " aggressive frame dropping, and the performance overlay on."
        )
        low_lag.clicked.connect(self._use_low_lag_preset)
        profile_form.addRow(low_lag)

        self._native_button = QPushButton("Rebuild native kernels")
        self._native_button.setToolTip(
            "Recompile the C frame kernels in place and switch to them"
            " without restarting. Requires a C compiler; the editor keeps"
            " running on the reference implementations if it fails."
        )
        self._native_button.clicked.connect(self._rebuild_native_kernels)
        profile_form.addRow(self._native_button)

        layout.addWidget(profile_group)

        # ------------------------------------------------------------------
        # Cache
        # ------------------------------------------------------------------
        memory_group = QGroupBox("Cache")
        memory_group.setObjectName("PreferencesGroup")
        memory_form = QFormLayout(memory_group)

        self._frame_cache_mb = QSpinBox()
        self._frame_cache_mb.setObjectName("PreferencesSpin")
        self._frame_cache_mb.setRange(
            FRAME_CACHE_MIN_MB, FRAME_CACHE_MAX_ALLOWED_MB)
        self._frame_cache_mb.setSingleStep(256)
        self._frame_cache_mb.setSuffix(" MB")
        self._frame_cache_mb.setValue(perf.frame_cache_mb)
        memory_form.addRow("Total cache budget", self._frame_cache_mb)

        self._decode_cache_frames = QSpinBox()
        self._decode_cache_frames.setObjectName("PreferencesSpin")
        self._decode_cache_frames.setRange(1, MAX_DECODE_CACHE_FRAMES)
        self._decode_cache_frames.setSuffix(" frames")
        self._decode_cache_frames.setValue(perf.decode_cache_frames)
        memory_form.addRow("Source decode cache", self._decode_cache_frames)

        clear_caches = QPushButton("Clear All Caches")
        clear_caches.setToolTip("Drop cached frames immediately.")
        clear_caches.clicked.connect(self._clear_caches_requested)
        memory_form.addRow(clear_caches)

        layout.addWidget(memory_group)

        # ------------------------------------------------------------------
        # Playback
        # ------------------------------------------------------------------
        playback_group = QGroupBox("Playback")
        playback_group.setObjectName("PreferencesGroup")
        playback_form = QFormLayout(playback_group)

        self._adaptive_preview = QCheckBox(
            "Automatically reduce preview resolution when playback is slow"
        )
        self._adaptive_preview.setChecked(perf.adaptive_preview_enabled)
        playback_form.addRow(self._adaptive_preview)

        self._high_quality_paused = QCheckBox(
            "Render full quality once playback stops"
        )
        self._high_quality_paused.setChecked(perf.high_quality_when_paused)
        playback_form.addRow(self._high_quality_paused)

        self._drop_mode = QComboBox()
        for mode in FrameDropMode:
            self._drop_mode.addItem(mode.label, mode.name)
        drop_index = self._drop_mode.findData(perf.effective_drop_mode)
        self._drop_mode.setCurrentIndex(max(0, drop_index))
        playback_form.addRow("Drop frames", self._drop_mode)

        self._target_preview_fps = QSpinBox()
        self._target_preview_fps.setObjectName("PreferencesSpin")
        self._target_preview_fps.setRange(0, 240)
        self._target_preview_fps.setSpecialValueText("Follow project")
        self._target_preview_fps.setSuffix(" fps")
        self._target_preview_fps.setValue(perf.target_preview_fps)
        playback_form.addRow("Target preview rate", self._target_preview_fps)

        self._hardware_decode = QCheckBox(
            "Use hardware-accelerated decode (if available)"
        )
        self._hardware_decode.setChecked(perf.hardware_decode_enabled)
        playback_form.addRow(self._hardware_decode)

        layout.addWidget(playback_group)

        # ------------------------------------------------------------------
        # Scrubbing
        # ------------------------------------------------------------------
        scrub_group = QGroupBox("Scrubbing")
        scrub_group.setObjectName("PreferencesGroup")
        scrub_form = QFormLayout(scrub_group)

        self._auto_scrub_quality = QCheckBox(
            "Use reduced quality while dragging the playhead"
        )
        self._auto_scrub_quality.setChecked(perf.auto_scrub_quality)
        scrub_form.addRow(self._auto_scrub_quality)

        self._scrub_quality = QSpinBox()
        self._scrub_quality.setObjectName("PreferencesSpin")
        self._scrub_quality.setRange(5, 100)
        self._scrub_quality.setSingleStep(5)
        self._scrub_quality.setSuffix(" %")
        self._scrub_quality.setValue(perf.scrub_quality_percent)
        self._auto_scrub_quality.toggled.connect(
            self._scrub_quality.setEnabled)
        self._scrub_quality.setEnabled(perf.auto_scrub_quality)
        scrub_form.addRow("Scrub quality", self._scrub_quality)

        self._high_quality_after_scrub = QCheckBox(
            "Render full quality once the drag stops"
        )
        self._high_quality_after_scrub.setChecked(
            perf.high_quality_after_scrub)
        scrub_form.addRow(self._high_quality_after_scrub)

        layout.addWidget(scrub_group)

        # ------------------------------------------------------------------
        # Prefetch
        # ------------------------------------------------------------------
        prefetch_group = QGroupBox("Prefetch")
        prefetch_group.setObjectName("PreferencesGroup")
        prefetch_form = QFormLayout(prefetch_group)

        self._prefetch_enabled = QCheckBox("Enable prefetch")
        self._prefetch_enabled.setChecked(perf.prefetch_enabled)
        prefetch_form.addRow(self._prefetch_enabled)

        self._adaptive_prefetch = QCheckBox(
            "Skip prefetch while scrubbing or seeking"
        )
        self._adaptive_prefetch.setChecked(perf.adaptive_prefetch)
        prefetch_form.addRow(self._adaptive_prefetch)

        self._max_prefetch = QSpinBox()
        self._max_prefetch.setObjectName("PreferencesSpin")
        self._max_prefetch.setRange(0, MAX_MAX_PREFETCH_FRAMES)
        self._max_prefetch.setSuffix(" frames")
        self._max_prefetch.setValue(perf.max_prefetch_frames)
        prefetch_form.addRow("Max prefetch ahead", self._max_prefetch)

        layout.addWidget(prefetch_group)

        # ------------------------------------------------------------------
        # CPU
        # ------------------------------------------------------------------
        cpu_group = QGroupBox("CPU")
        cpu_group.setObjectName("PreferencesGroup")
        cpu_form = QFormLayout(cpu_group)

        self._worker_threads = QSpinBox()
        self._worker_threads.setObjectName("PreferencesSpin")
        self._worker_threads.setRange(0, MAX_WORKER_THREADS)
        self._worker_threads.setSpecialValueText("Auto")
        self._worker_threads.setSuffix(" threads")
        self._worker_threads.setValue(perf.worker_threads)
        cpu_form.addRow("Worker threads", self._worker_threads)

        self._pause_background = QCheckBox(
            "Pause background jobs during playback"
        )
        self._pause_background.setChecked(
            perf.pause_background_during_playback)
        cpu_form.addRow(self._pause_background)

        layout.addWidget(cpu_group)

        # ------------------------------------------------------------------
        # Playback Proxy Override
        # ------------------------------------------------------------------
        proxy_group = QGroupBox("Playback Proxy Override")
        proxy_group.setObjectName("PreferencesGroup")
        proxy_form = QFormLayout(proxy_group)

        self._proxy_override_enabled = QCheckBox(
            "Force a lower decode width while playing"
        )
        self._proxy_override_enabled.setChecked(
            perf.playback_proxy_override_enabled)
        proxy_form.addRow(self._proxy_override_enabled)

        self._proxy_width = QSpinBox()
        self._proxy_width.setObjectName("PreferencesSpin")
        self._proxy_width.setRange(160, 3840)
        self._proxy_width.setSingleStep(80)
        self._proxy_width.setSuffix(" px")
        self._proxy_width.setValue(perf.playback_proxy_width)
        self._proxy_width.setEnabled(perf.playback_proxy_override_enabled)
        self._proxy_override_enabled.toggled.connect(
            self._proxy_width.setEnabled)
        proxy_form.addRow("Playback width", self._proxy_width)

        proxy_hint = QLabel(
            "Applies only while actively playing; paused review still uses"
            " each Viewer's own Proxy Width."
        )
        proxy_hint.setObjectName("PreferencesHint")
        proxy_hint.setWordWrap(True)
        proxy_form.addRow(proxy_hint)

        layout.addWidget(proxy_group)

        # ------------------------------------------------------------------
        # Media engine: editing proxies and the render cache
        # ------------------------------------------------------------------
        media_group = QGroupBox("Media Engine")
        media_group.setObjectName("PreferencesGroup")
        media_form = QFormLayout(media_group)

        self._use_proxies = QCheckBox("Use generated editing proxies")
        self._use_proxies.setChecked(perf.use_editing_proxies)
        media_form.addRow(self._use_proxies)

        self._generate_proxies = QCheckBox(
            "Generate proxies automatically for new media"
        )
        self._generate_proxies.setChecked(perf.generate_proxies_automatically)
        media_form.addRow(self._generate_proxies)

        self._proxy_height = QComboBox()
        self._proxy_height.addItem("Auto", 0)
        self._proxy_height.addItem("720p", 720)
        self._proxy_height.addItem("540p", 540)
        self._proxy_height.addItem("360p", 360)
        proxy_index = self._proxy_height.findData(int(perf.proxy_height))
        self._proxy_height.setCurrentIndex(max(0, proxy_index))
        media_form.addRow("Proxy resolution", self._proxy_height)

        self._render_cache_mode = QComboBox()
        self._render_cache_mode.addItem("Off", "off")
        self._render_cache_mode.addItem("Smart (auto-cache heavy branches)", "smart")
        self._render_cache_mode.addItem("User (cache what you mark)", "user")
        cache_index = self._render_cache_mode.findData(perf.render_cache_mode)
        self._render_cache_mode.setCurrentIndex(max(0, cache_index))
        media_form.addRow("Render cache", self._render_cache_mode)

        self._disk_cache_limit = QSpinBox()
        self._disk_cache_limit.setObjectName("PreferencesSpin")
        self._disk_cache_limit.setRange(0, 262_144)
        self._disk_cache_limit.setSingleStep(512)
        self._disk_cache_limit.setSuffix(" MB")
        self._disk_cache_limit.setValue(perf.disk_cache_limit_mb)
        media_form.addRow("Disk cache limit", self._disk_cache_limit)

        clear_proxies = QPushButton("Clear Proxy Cache")
        clear_proxies.setToolTip(
            "Delete generated proxies. They are rebuilt in the background"
            " the next time their media is used."
        )
        clear_proxies.clicked.connect(self._clear_proxy_cache_requested)
        media_form.addRow(clear_proxies)

        media_hint = QLabel(
            "Proxies are all-intra, low-resolution copies of your media used"
            " only for editing. Originals are never modified and export always"
            " uses the original."
        )
        media_hint.setObjectName("PreferencesHint")
        media_hint.setWordWrap(True)
        media_form.addRow(media_hint)

        layout.addWidget(media_group)

        # ------------------------------------------------------------------
        # Debugging
        # ------------------------------------------------------------------
        diag_group = QGroupBox("Performance Diagnostics")
        diag_group.setObjectName("PreferencesGroup")
        diag_form = QFormLayout(diag_group)

        self._show_overlay = QCheckBox("Show performance overlay in viewport")
        self._show_overlay.setChecked(perf.show_performance_overlay)
        diag_form.addRow(self._show_overlay)

        self._performance_diagnostics = QCheckBox(
            "Record timing statistics (decode/graph/upload)"
        )
        self._performance_diagnostics.setChecked(perf.performance_diagnostics)
        diag_form.addRow(self._performance_diagnostics)

        layout.addWidget(diag_group)

        hint = QLabel(
            "Higher cache and prefetch values trade RAM for smoother scrubbing"
            " and playback. Changes apply when you click Apply or OK."
        )
        hint.setObjectName("PreferencesHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Performance tab helpers
    # ------------------------------------------------------------------

    def _hardware_summary_text(self) -> str:
        """Describe the detected machine in one short line.

        Includes the frame-kernel backend so it is unambiguous whether the
        native extension is actually in use — it is built automatically at
        boot, so the interesting question is never "was it built?" but "did
        the build succeed, and if not, why not?".
        """
        caps = detect_capabilities()
        parts = [
            f"{caps.cpu_logical} threads",
            f"{caps.ram_total_mb // 1024} GB RAM",
        ]
        if caps.gpu_name:
            parts.append(caps.gpu_name)
        parts.append(caps.platform or "unknown OS")
        parts.append(self._native_status_text())
        return "Detected: " + " · ".join(parts)

    @staticmethod
    def _native_status_text() -> str:
        """One phrase describing the native kernel state, with the reason."""
        from core.native import build_in_progress, last_build_outcome, probe

        if probe().available:
            return "native kernels"

        if build_in_progress():
            return "native kernels building…"

        outcome = last_build_outcome()
        if outcome is not None and outcome.message:
            return f"python kernels ({outcome.message})"
        return "python kernels"

    def _rebuild_native_kernels(self) -> None:
        """Kick off a rebuild and report the result when it lands.

        The build runs off the GUI thread, so the button returns straight
        away and the summary label is refreshed from the completion
        callback — which is why the callback is wrapped rather than
        connected directly.
        """
        from core.native import (add_build_listener, build_in_progress,
                                 ensure_available)
        from PyQt6.QtCore import QTimer

        if build_in_progress():
            QMessageBox.information(
                self, "Native Kernels", "A native build is already running."
            )
            return

        self._native_button.setEnabled(False)
        self._hardware_summary.setText(self._hardware_summary_text())

        def _on_complete(outcome) -> None:
            # Called from the build thread; hop to the GUI thread before
            # touching any widget.
            QTimer.singleShot(0, lambda: self._native_build_finished(outcome))

        add_build_listener(_on_complete)
        ensure_available(background=True, force_build=True)

        QMessageBox.information(
            self,
            "Native Kernels",
            "Rebuilding the native frame kernels in the background.\n\n"
            "Playback continues on the current kernels; the editor switches "
            "over automatically when the build finishes.",
        )

    def _native_build_finished(self, outcome) -> None:
        """Refresh the summary label after a background build completes."""
        self._native_button.setEnabled(True)
        if not self.isVisible():
            return
        self._hardware_summary.setText(self._hardware_summary_text())
        if outcome.built:
            QMessageBox.information(
                self,
                "Native Kernels",
                "Native frame kernels are built and active.\n\n"
                "No restart was needed.",
            )
        else:
            QMessageBox.warning(
                self,
                "Native Kernels",
                "The native build did not produce a usable module.\n\n"
                f"{outcome.message}\n\n"
                "The editor keeps running on the NumPy/OpenCV reference "
                "kernels, so nothing is broken — only slower. Install a C "
                "toolchain (Visual Studio Build Tools on Windows) and try "
                "again to get the native speed-up.",
            )

    def _auto_configure_performance(self) -> None:
        """Detect hardware and apply the recommended profile."""
        caps = detect_capabilities(refresh=True, include_expensive=True)
        profile = recommend_profile(caps)
        configured = apply_profile(PerformanceSettings(), profile, caps)
        self._working.performance = configured
        self._hardware_summary.setText(self._hardware_summary_text())
        QMessageBox.information(
            self,
            "Performance Configured",
            f"Applied the {profile.label} profile.\n\n"
            f"{self._hardware_summary_text()}",
        )

    def _on_profile_selected(self, _index: int) -> None:
        """Re-apply a named profile's values into the live controls."""
        data = self._profile_combo.currentData()
        profile = PerformanceProfile.from_value(data)
        if profile is PerformanceProfile.CUSTOM:
            return
        self._working.performance = apply_profile(
            self._working.performance, profile
        )
        self._reload_performance_controls()

    def _reload_performance_controls(self) -> None:
        """Push the working settings back into every performance widget."""
        perf = self._working.performance
        widgets = (
            self._frame_cache_mb,
            self._decode_cache_frames,
            self._max_prefetch,
            self._scrub_quality,
            self._worker_threads,
            self._proxy_width,
            self._target_preview_fps,
            self._disk_cache_limit,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self._frame_cache_mb.setValue(perf.frame_cache_mb)
            self._decode_cache_frames.setValue(perf.decode_cache_frames)
            self._max_prefetch.setValue(perf.max_prefetch_frames)
            self._scrub_quality.setValue(perf.scrub_quality_percent)
            self._worker_threads.setValue(perf.worker_threads)
            self._proxy_width.setValue(perf.playback_proxy_width)
            self._target_preview_fps.setValue(perf.target_preview_fps)
            self._disk_cache_limit.setValue(perf.disk_cache_limit_mb)

            self._use_proxies.setChecked(perf.use_editing_proxies)
            self._generate_proxies.setChecked(
                perf.generate_proxies_automatically)
            proxy_index = self._proxy_height.findData(int(perf.proxy_height))
            self._proxy_height.setCurrentIndex(max(0, proxy_index))
            cache_index = self._render_cache_mode.findData(
                perf.render_cache_mode)
            self._render_cache_mode.setCurrentIndex(max(0, cache_index))

            self._adaptive_preview.setChecked(perf.adaptive_preview_enabled)
            self._high_quality_paused.setChecked(perf.high_quality_when_paused)
            self._high_quality_after_scrub.setChecked(
                perf.high_quality_after_scrub
            )
            self._prefetch_enabled.setChecked(perf.prefetch_enabled)
            self._adaptive_prefetch.setChecked(perf.adaptive_prefetch)
            self._pause_background.setChecked(
                perf.pause_background_during_playback)
            self._auto_scrub_quality.setChecked(perf.auto_scrub_quality)
            self._hardware_decode.setChecked(perf.hardware_decode_enabled)
            self._proxy_override_enabled.setChecked(
                perf.playback_proxy_override_enabled
            )
            self._proxy_width.setEnabled(perf.playback_proxy_override_enabled)
            self._scrub_quality.setEnabled(perf.auto_scrub_quality)

            drop_index = self._drop_mode.findData(perf.effective_drop_mode)
            self._drop_mode.setCurrentIndex(max(0, drop_index))
            self._profile_combo.setCurrentIndex(
                max(0, self._profile_combo.findData(perf.performance_profile))
            )
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _clear_caches_requested(self) -> None:
        """Ask the editor to flush caches; the editor owns the live state."""
        self.clear_caches_requested.emit()

    def _clear_proxy_cache_requested(self) -> None:
        """Delete generated editing proxies and report how much was freed."""
        try:
            from core.media.proxy import get_proxy_manager

            manager = get_proxy_manager()
            freed = manager.cache_size_bytes()
            removed = manager.clear()
        except Exception as exc:  # noqa: BLE001 - never block on cleanup
            QMessageBox.warning(
                self, "Clear Proxy Cache", f"Could not clear the proxy cache.\n\n{exc}"
            )
            return

        QMessageBox.information(
            self,
            "Clear Proxy Cache",
            f"Removed {removed} file(s), freeing {freed / (1024 * 1024):.1f} MB.\n\n"
            "Proxies are regenerated in the background when their media is used again.",
        )

    def _use_low_lag_preset(self) -> None:
        """Apply the Eco profile, which is the modern low-lag preset."""
        self._working.performance = apply_profile(
            self._working.performance, PerformanceProfile.ECO
        )
        self._profile_combo.setCurrentIndex(
            max(0, self._profile_combo.findData(PerformanceProfile.ECO.value))
        )
        self._reload_performance_controls()
        self._show_overlay.setChecked(True)

    def _build_audio_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        audio = self._working.audio

        general_group = QGroupBox("Playback")
        general_group.setObjectName("PreferencesGroup")
        general_form = QFormLayout(general_group)

        self._audio_enabled = QCheckBox("Enable audio playback")
        self._audio_enabled.setChecked(audio.audio_enabled)
        general_form.addRow(self._audio_enabled)

        self._master_volume = QSpinBox()
        self._master_volume.setObjectName("PreferencesSpin")
        self._master_volume.setRange(0, 200)
        self._master_volume.setSingleStep(10)
        self._master_volume.setSuffix("%")
        self._master_volume.setValue(int(audio.master_volume * 100))
        general_form.addRow("Master volume", self._master_volume)

        self._latency_preset = QComboBox()
        self._latency_preset.setObjectName("PreferencesCombo")
        self._latency_preset.addItem("Low Latency", "low")
        self._latency_preset.addItem("Balanced", "balanced")
        self._latency_preset.addItem("Safe / Stable", "safe")
        latency_index = self._latency_preset.findData(audio.latency_preset)
        if latency_index >= 0:
            self._latency_preset.setCurrentIndex(latency_index)
        general_form.addRow("Latency preset", self._latency_preset)

        self._buffer_size = QSpinBox()
        self._buffer_size.setObjectName("PreferencesSpin")
        self._buffer_size.setRange(2, 20)
        self._buffer_size.setSuffix(" chunks")
        self._buffer_size.setValue(audio.buffer_size)
        general_form.addRow("Queue depth", self._buffer_size)

        self._stream_blocksize = QComboBox()
        self._stream_blocksize.setObjectName("PreferencesCombo")
        self._stream_blocksize.addItem("Automatic", 0)
        for size in (128, 256, 512, 1024, 2048):
            self._stream_blocksize.addItem(str(size), size)
        blocksize_index = self._stream_blocksize.findData(
            audio.stream_blocksize)
        if blocksize_index >= 0:
            self._stream_blocksize.setCurrentIndex(blocksize_index)
        general_form.addRow("Buffer size", self._stream_blocksize)

        self._output_sample_rate = QComboBox()
        self._output_sample_rate.setObjectName("PreferencesCombo")
        for rate in (44100, 48000, 96000):
            self._output_sample_rate.addItem(f"{rate} Hz", rate)
        sample_rate_index = self._output_sample_rate.findData(
            audio.output_sample_rate)
        if sample_rate_index >= 0:
            self._output_sample_rate.setCurrentIndex(sample_rate_index)
        general_form.addRow("Sample rate", self._output_sample_rate)

        self._output_channels = QComboBox()
        self._output_channels.setObjectName("PreferencesCombo")
        self._output_channels.addItem("Mono", 1)
        self._output_channels.addItem("Stereo", 2)
        channels_index = self._output_channels.findData(audio.output_channels)
        if channels_index >= 0:
            self._output_channels.setCurrentIndex(channels_index)
        general_form.addRow("Output channels", self._output_channels)

        playback_hint = QLabel(
            "Recommended starting point: Safe / Stable, 512 or 1024 buffer, "
            "48 kHz, Stereo, queue depth 10–12. WASAPI is usually the best "
            "Windows choice here."
        )
        playback_hint.setObjectName("PreferencesHint")
        playback_hint.setWordWrap(True)
        general_form.addRow(playback_hint)

        layout.addWidget(general_group)

        device_group = QGroupBox("Playback Device")
        device_group.setObjectName("PreferencesGroup")
        device_form = QFormLayout(device_group)

        self._audio_driver = QComboBox()
        self._audio_driver.setObjectName("PreferencesCombo")
        self._audio_driver.currentIndexChanged.connect(
            self._on_audio_driver_changed)
        device_form.addRow("Driver", self._audio_driver)

        self._audio_device = QComboBox()
        self._audio_device.setObjectName("PreferencesCombo")
        self._reload_audio_devices(
            preferred_host_api=audio.host_api_name, preferred_device_index=audio.default_device_index)
        device_form.addRow("Output device", self._audio_device)

        button_row = QHBoxLayout()
        self._refresh_audio_devices_btn = QPushButton("Refresh Devices")
        self._refresh_audio_devices_btn.setObjectName(
            "PreferencesSecondaryButton")
        self._refresh_audio_devices_btn.clicked.connect(
            self._reload_audio_devices)
        button_row.addWidget(self._refresh_audio_devices_btn)

        self._test_audio_device_btn = QPushButton("Test Device")
        self._test_audio_device_btn.setObjectName("PreferencesSecondaryButton")
        self._test_audio_device_btn.clicked.connect(self._test_audio_device)
        button_row.addWidget(self._test_audio_device_btn)
        button_row.addStretch(1)
        device_form.addRow(button_row)

        device_hint = QLabel(
            "Select the audio output device for playback, then use Test Device "
            "to play a short tone through the selected output."
        )
        device_hint.setObjectName("PreferencesHint")
        device_hint.setWordWrap(True)
        device_form.addRow(device_hint)

        layout.addWidget(device_group)

        export_group = QGroupBox("Export")
        export_group.setObjectName("PreferencesGroup")
        export_form = QFormLayout(export_group)

        self._export_audio_enabled = QCheckBox(
            "Include audio in video exports")
        self._export_audio_enabled.setChecked(audio.export_audio_enabled)
        export_form.addRow(self._export_audio_enabled)

        self._export_sample_rate = QComboBox()
        self._export_sample_rate.setObjectName("PreferencesCombo")
        for rate in (44100, 48000, 96000):
            self._export_sample_rate.addItem(f"{rate} Hz", rate)
        export_sample_rate_index = self._export_sample_rate.findData(
            audio.export_sample_rate)
        if export_sample_rate_index >= 0:
            self._export_sample_rate.setCurrentIndex(export_sample_rate_index)
        export_form.addRow("Export sample rate", self._export_sample_rate)

        self._export_channels = QComboBox()
        self._export_channels.setObjectName("PreferencesCombo")
        self._export_channels.addItem("Mono", 1)
        self._export_channels.addItem("Stereo", 2)
        export_channels_index = self._export_channels.findData(
            audio.export_channels)
        if export_channels_index >= 0:
            self._export_channels.setCurrentIndex(export_channels_index)
        export_form.addRow("Export channels", self._export_channels)

        export_hint = QLabel(
            "Recommended export settings: 48 kHz Stereo for general video delivery."
        )
        export_hint.setObjectName("PreferencesHint")
        export_hint.setWordWrap(True)
        export_form.addRow(export_hint)

        layout.addWidget(export_group)

        hint = QLabel(
            "Driver lists come from PortAudio via sounddevice. If ASIO is not shown, "
            "it is not available through the installed PortAudio build on this system."
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
            self._theme_combo.setCurrentIndex(
                self._theme_combo.findData("custom"))
        self._theme_combo.currentIndexChanged.connect(
            self._on_theme_preset_changed)
        form.addRow("Preset", self._theme_combo)

        self._accent_btn = self._color_button(self._theme_tokens.accent)
        self._accent_btn.clicked.connect(
            lambda: self._pick_theme_color("accent"))
        form.addRow("Accent", self._accent_btn)

        self._window_btn = self._color_button(self._theme_tokens.window_bg)
        self._window_btn.clicked.connect(
            lambda: self._pick_theme_color("window_bg"))
        form.addRow("Window background", self._window_btn)

        self._panel_btn = self._color_button(self._theme_tokens.panel_bg)
        self._panel_btn.clicked.connect(
            lambda: self._pick_theme_color("panel_bg"))
        form.addRow("Panel background", self._panel_btn)

        self._graph_btn = self._color_button(
            self._rgb_hex(self._theme_tokens.graph_bg_rgb))
        self._graph_btn.clicked.connect(
            lambda: self._pick_theme_color("graph_bg_rgb"))
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
        button.clicked.connect(lambda _checked=False, k=key,
                               d=info.color: self._pick_node_color(k, d))
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
        button.setStyleSheet(
            f"background-color: {hex_color}; border: 1px solid #555;")
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
            self._theme_tokens.graph_bg_rgb = (
                picked.red(), picked.green(), picked.blue())
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

    def _reload_audio_devices(
        self,
        preferred_host_api: str | None = None,
        preferred_device_index: int | None = None,
    ) -> None:
        """Refresh the list of available audio output devices."""
        current_driver = preferred_host_api if preferred_host_api is not None else (
            str(self._audio_driver.currentData()) if hasattr(
                self, "_audio_driver") and self._audio_driver.count() > 0 else ""
        )
        current_device = preferred_device_index if preferred_device_index is not None else (
            int(self._audio_device.currentData()) if hasattr(self, "_audio_device") and self._audio_device.count(
            ) > 0 and self._audio_device.currentData() is not None else -1
        )

        self._audio_driver.blockSignals(True)
        self._audio_device.blockSignals(True)
        self._audio_driver.clear()
        self._audio_device.clear()
        try:
            from render.audio_playback import AudioPlaybackEngine

            devices = AudioPlaybackEngine.get_available_devices()
            host_apis: list[str] = []
            for device in devices:
                if device.host_api_name not in host_apis:
                    host_apis.append(device.host_api_name)

            self._audio_driver.addItem("All Drivers", "")
            for host_api in host_apis:
                if host_api and host_api != "System Default":
                    self._audio_driver.addItem(host_api, host_api)

            driver_index = self._audio_driver.findData(current_driver)
            if driver_index < 0:
                driver_index = 0
            self._audio_driver.setCurrentIndex(driver_index)
            selected_driver = str(self._audio_driver.currentData())

            for device in devices:
                if selected_driver and device.host_api_name != selected_driver:
                    continue
                self._audio_device.addItem(device.name, device.index)
        except Exception as exc:  # noqa: BLE001
            self._audio_driver.addItem("All Drivers", "")
            self._audio_device.addItem("Default System Device", -1)
            QMessageBox.warning(
                self,
                "Audio Devices",
                f"Failed to enumerate audio devices.\n\n{exc}",
            )
        finally:
            self._audio_driver.blockSignals(False)
            self._audio_device.blockSignals(False)

        current_index = self._audio_device.findData(current_device)
        if current_index < 0:
            current_index = self._audio_device.findData(-1)
        if current_index >= 0:
            self._audio_device.setCurrentIndex(current_index)

    def _on_audio_driver_changed(self) -> None:
        self._reload_audio_devices(preferred_host_api=str(
            self._audio_driver.currentData()))

    def _test_audio_device(self) -> None:
        """Play a short tone through the selected output device."""
        try:
            from render.audio_playback import AudioPlaybackEngine

            device_index = int(self._audio_device.currentData())
            host_api_name = str(self._audio_driver.currentData())
            selected = None
            for device in AudioPlaybackEngine.get_available_devices():
                if host_api_name and device.host_api_name != host_api_name:
                    continue
                if device.index == device_index:
                    selected = device
                    break
            AudioPlaybackEngine().test_device(selected)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Test Audio Device",
                f"Could not play test audio.\n\n{exc}",
            )

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
            graph_layout_mode=node_ops.GraphLayoutMode(
                self._graph_layout_combo.currentData()),
            show_pin_bar=self._working.editor.show_pin_bar,
        )
        # Every persisted field must be written back, otherwise editing any
        # unrelated tab would silently reset it to its factory default.
        previous_perf = self._working.performance
        self._working.performance = replace(
            previous_perf,
            performance_profile=str(self._profile_combo.currentData()),
            use_editing_proxies=self._use_proxies.isChecked(),
            generate_proxies_automatically=self._generate_proxies.isChecked(),
            proxy_height=int(self._proxy_height.currentData() or 0),
            render_cache_mode=str(self._render_cache_mode.currentData()),
            disk_cache_limit_mb=int(self._disk_cache_limit.value()),
            frame_cache_mb=int(self._frame_cache_mb.value()),
            decode_cache_frames=int(self._decode_cache_frames.value()),
            prefetch_enabled=self._prefetch_enabled.isChecked(),
            adaptive_prefetch=self._adaptive_prefetch.isChecked(),
            max_prefetch_frames=int(self._max_prefetch.value()),
            adaptive_preview_enabled=self._adaptive_preview.isChecked(),
            playback_proxy_override_enabled=self._proxy_override_enabled.isChecked(),
            playback_proxy_width=int(self._proxy_width.value()),
            high_quality_when_paused=self._high_quality_paused.isChecked(),
            drop_frames_during_playback=str(
                self._drop_mode.currentData()) != "OFF",
            drop_frames_mode=str(self._drop_mode.currentData()),
            target_preview_fps=int(self._target_preview_fps.value()),
            scrub_quality_percent=int(self._scrub_quality.value()),
            auto_scrub_quality=self._auto_scrub_quality.isChecked(),
            high_quality_after_scrub=self._high_quality_after_scrub.isChecked(),
            worker_threads=int(self._worker_threads.value()),
            pause_background_during_playback=self._pause_background.isChecked(),
            hardware_decode_enabled=self._hardware_decode.isChecked(),
            show_performance_overlay=self._show_overlay.isChecked(),
            performance_diagnostics=self._performance_diagnostics.isChecked(),
        )
        self._working.audio = AudioSettings(
            audio_enabled=self._audio_enabled.isChecked(),
            master_volume=float(self._master_volume.value()) / 100.0,
            host_api_name=str(self._audio_driver.currentData()),
            default_device_index=int(self._audio_device.currentData()),
            latency_preset=str(self._latency_preset.currentData()),
            buffer_size=int(self._buffer_size.value()),
            stream_blocksize=int(self._stream_blocksize.currentData()),
            output_sample_rate=int(self._output_sample_rate.currentData()),
            output_channels=int(self._output_channels.currentData()),
            export_audio_enabled=self._export_audio_enabled.isChecked(),
            export_sample_rate=int(self._export_sample_rate.currentData()),
            export_channels=int(self._export_channels.currentData()),
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
