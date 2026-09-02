"""Apply persisted preferences to the live editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.theme_engine import ThemeStyles, build_theme_styles
from core.nodes.registry import global_node_registry
from core.preferences.models import AppPreferences, AudioSettings, PerformanceSettings
from render import video_decoder
from ui.node_graph.theme_state import apply_graph_palette

if TYPE_CHECKING:
    from ui.windows.editor import Editor


def apply_preferences_to_editor(editor: "Editor", preferences: AppPreferences) -> None:
    """Push preference values to editor widgets and services.

    Parameters:
        editor: Live editor window.
        preferences: Preference document to apply.

    Side effects:
        Updates stylesheets, timers, keybinds, node colors, and playback
        performance knobs (frame cache budget, decode strategy, prefetch).
    """
    tokens = preferences.theme.resolved_tokens()
    if preferences.node_colors:
        overrides: dict[str, tuple[int, int, int]] = {}
        for key, rgb in preferences.node_colors.items():
            if len(rgb) >= 3:
                overrides[key] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        global_node_registry.set_color_overrides(overrides)

    styles = build_theme_styles(tokens)
    apply_graph_palette(tokens)
    _apply_styles(editor, styles, tokens.window_bg)
    _apply_editor_settings(editor, preferences)
    _apply_performance_settings(editor, preferences.performance)
    _apply_audio_settings(editor, preferences.audio)
    editor.node_graph.set_show_grid(preferences.editor.show_graph_grid)
    editor.node_graph.refresh_theme()
    editor.node_graph.layout_mode = preferences.editor.graph_layout_mode
    editor.refresh_node_colors()


def _apply_performance_settings(
    editor: "Editor", performance: PerformanceSettings
) -> None:
    """Push global playback-performance knobs to the project, decoders, and viewport."""
    editor.project.set_frame_cache_budget_mb(performance.frame_cache_mb)
    video_decoder.set_decode_cache_frames(performance.decode_cache_frames)
    video_decoder.set_hardware_decode_enabled(performance.hardware_decode_enabled)
    editor.viewport.apply_performance_settings(performance)


def _apply_audio_settings(editor: "Editor", audio: AudioSettings) -> None:
    """Push audio preferences into the shared preview playback engine."""
    del editor
    from render.audio_playback import AudioPlaybackEngine, get_audio_engine

    engine = get_audio_engine()
    engine.set_enabled(audio.audio_enabled)
    engine.set_volume(audio.master_volume)
    engine.set_buffer_size(audio.buffer_size)
    engine.set_stream_config(
        sample_rate=audio.output_sample_rate,
        channels=audio.output_channels,
        blocksize=audio.stream_blocksize,
        latency_preset=audio.latency_preset,
    )

    selected_device = None
    for device in AudioPlaybackEngine.get_available_devices():
        if audio.host_api_name and device.host_api_name != audio.host_api_name:
            continue
        if device.index == audio.default_device_index:
            selected_device = device
            break
    engine.set_device(selected_device)


def _apply_styles(editor: "Editor", styles: ThemeStyles, window_bg: str) -> None:
    editor.setStyleSheet(styles.main)
    editor.theme_styles = styles
    central = editor.centralWidget()
    if central is not None:
        central.setStyleSheet(f"background-color: {window_bg};")
    for dock in (
        editor.docks.viewport,
        editor.docks.timeline,
        editor.docks.node_graph,
        editor.docks.properties,
    ):
        dock.setStyleSheet(styles.dock)
    menubar = editor.menuBar()
    if menubar is not None:
        menubar.setStyleSheet(styles.menubar)
    editor.timeline.setStyleSheet(styles.timeline)
    editor.properties.setStyleSheet(styles.properties)


def _apply_editor_settings(editor: "Editor", preferences: AppPreferences) -> None:
    settings = preferences.editor
    if editor._key_hint_label is not None:
        editor._key_hint_label.setVisible(settings.show_status_key_hints)
    if settings.autosave_enabled:
        editor._autosave_timer.setInterval(max(1000, settings.autosave_interval_ms))
        if not editor._autosave_timer.isActive():
            editor._autosave_timer.start()
    else:
        editor._autosave_timer.stop()
