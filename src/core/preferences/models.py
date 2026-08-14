"""Application preference models (Qt-free)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.constants import (
    AUTOSAVE_INTERVAL_MS,
    DEFAULT_DECODE_CACHE_FRAMES,
    DEFAULT_MAX_PREFETCH_FRAMES,
    DEFAULT_PLAYBACK_PROXY_WIDTH,
    FRAME_CACHE_MAX_ALLOWED_MB,
    FRAME_CACHE_MAX_MB,
    FRAME_CACHE_MIN_MB,
    MAX_DECODE_CACHE_FRAMES,
    MAX_MAX_PREFETCH_FRAMES,
)
from config.theme_tokens import ThemeTokens, aphelion_dark, builtin_theme

DEFAULT_PINNED_ACTIONS: tuple[str, ...] = (
    "save_project",
    "undo",
    "redo",
    "play_pause",
    "export_sequence",
)
"""Factory-default pin-bar contents, expressed as ``KeyAction`` values.

Kept as plain strings (rather than importing ``KeyAction``) to preserve the
Qt-free nature of this module; ``core.preferences.applier`` resolves them
back to enum members when wiring the live editor.
"""


@dataclass
class EditorSettings:
    """User-facing editor behavior preferences."""

    editor_font_family: str = "JetBrains Mono"
    editor_font_size: int = 13
    show_graph_grid: bool = True
    autosave_enabled: bool = True
    autosave_interval_ms: int = AUTOSAVE_INTERVAL_MS
    show_status_key_hints: bool = True
    show_pin_bar: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "editor_font_family": self.editor_font_family,
            "editor_font_size": self.editor_font_size,
            "show_graph_grid": self.show_graph_grid,
            "autosave_enabled": self.autosave_enabled,
            "autosave_interval_ms": self.autosave_interval_ms,
            "show_status_key_hints": self.show_status_key_hints,
            "show_pin_bar": self.show_pin_bar,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditorSettings:
        return cls(
            editor_font_family=str(data.get("editor_font_family", "JetBrains Mono")),
            editor_font_size=int(data.get("editor_font_size", 13)),
            show_graph_grid=bool(data.get("show_graph_grid", True)),
            autosave_enabled=bool(data.get("autosave_enabled", True)),
            autosave_interval_ms=int(
                data.get("autosave_interval_ms", AUTOSAVE_INTERVAL_MS)
            ),
            show_status_key_hints=bool(data.get("show_status_key_hints", True)),
            show_pin_bar=bool(data.get("show_pin_bar", False)),
        )


@dataclass
class ThemeSettings:
    """Active theme selection and optional custom override."""

    active_theme_id: str = "aphelion_dark"
    custom_tokens: ThemeTokens | None = None

    def resolved_tokens(self) -> ThemeTokens:
        """Return the effective theme tokens for the current selection."""
        if self.custom_tokens is not None:
            return self.custom_tokens
        preset = builtin_theme(self.active_theme_id)
        return preset if preset is not None else aphelion_dark()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"active_theme_id": self.active_theme_id}
        if self.custom_tokens is not None:
            payload["custom_tokens"] = self.custom_tokens.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThemeSettings:
        custom_raw = data.get("custom_tokens")
        custom = (
            ThemeTokens.from_dict(custom_raw)
            if isinstance(custom_raw, dict)
            else None
        )
        return cls(
            active_theme_id=str(data.get("active_theme_id", "aphelion_dark")),
            custom_tokens=custom,
        )


@dataclass
class PerformanceSettings:
    """Global playback-performance knobs applied on top of per-Viewer settings.

    These are process-wide defaults/caps (cache budget, decode strategy,
    threading behavior); per-composition preview quality still lives on the
    Viewer node itself and is persisted with the project document.
    """

    frame_cache_mb: int = FRAME_CACHE_MAX_MB
    decode_cache_frames: int = DEFAULT_DECODE_CACHE_FRAMES
    max_prefetch_frames: int = DEFAULT_MAX_PREFETCH_FRAMES
    hardware_decode_enabled: bool = False
    playback_proxy_override_enabled: bool = False
    playback_proxy_width: int = DEFAULT_PLAYBACK_PROXY_WIDTH
    drop_frames_during_playback: bool = True
    show_performance_overlay: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_cache_mb": self.frame_cache_mb,
            "decode_cache_frames": self.decode_cache_frames,
            "max_prefetch_frames": self.max_prefetch_frames,
            "hardware_decode_enabled": self.hardware_decode_enabled,
            "playback_proxy_override_enabled": self.playback_proxy_override_enabled,
            "playback_proxy_width": self.playback_proxy_width,
            "drop_frames_during_playback": self.drop_frames_during_playback,
            "show_performance_overlay": self.show_performance_overlay,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceSettings:
        return cls(
            frame_cache_mb=_clamp(
                int(data.get("frame_cache_mb", FRAME_CACHE_MAX_MB)),
                FRAME_CACHE_MIN_MB,
                FRAME_CACHE_MAX_ALLOWED_MB,
            ),
            decode_cache_frames=_clamp(
                int(data.get("decode_cache_frames", DEFAULT_DECODE_CACHE_FRAMES)),
                1,
                MAX_DECODE_CACHE_FRAMES,
            ),
            max_prefetch_frames=_clamp(
                int(data.get("max_prefetch_frames", DEFAULT_MAX_PREFETCH_FRAMES)),
                0,
                MAX_MAX_PREFETCH_FRAMES,
            ),
            hardware_decode_enabled=bool(data.get("hardware_decode_enabled", False)),
            playback_proxy_override_enabled=bool(
                data.get("playback_proxy_override_enabled", False)
            ),
            playback_proxy_width=max(
                160, int(data.get("playback_proxy_width", DEFAULT_PLAYBACK_PROXY_WIDTH))
            ),
            drop_frames_during_playback=bool(
                data.get("drop_frames_during_playback", True)
            ),
            show_performance_overlay=bool(
                data.get("show_performance_overlay", False)
            ),
        )


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _as_dict(raw: object) -> dict[str, Any]:
    """Return ``raw`` when it is a dict, otherwise an empty dict."""
    return raw if isinstance(raw, dict) else {}


def _as_str_list(raw: object, default: list[str]) -> list[str]:
    """Return ``raw`` as a string list, or a copy of ``default``."""
    if not isinstance(raw, list):
        return list(default)
    return [str(item) for item in raw]


def _str_str_map(raw: object) -> dict[str, str]:
    """Return a string-to-string mapping copied from ``raw``."""
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _dict_list(raw: object) -> list[dict[str, Any]]:
    """Return dict items from a JSON list, skipping other values."""
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _node_colors_from_raw(raw: object) -> dict[str, list[int]]:
    """Parse persisted node-color overrides ``{key: [r, g, b]}``."""
    colors: dict[str, list[int]] = {}
    if not isinstance(raw, dict):
        return colors
    for key, value in raw.items():
        if isinstance(value, list):
            colors[str(key)] = [int(channel) for channel in value[:3]]
    return colors


@dataclass
class PluginSettings:
    """How third-party plugins are discovered, enabled, and reloaded."""

    load_bundled: bool = True
    load_user: bool = True
    load_entry_points: bool = True
    disabled_plugin_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize plugin preferences to JSON-compatible data."""
        return {
            "load_bundled": self.load_bundled,
            "load_user": self.load_user,
            "load_entry_points": self.load_entry_points,
            "disabled_plugin_keys": list(self.disabled_plugin_keys),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginSettings:
        """Deserialize plugin preferences from JSON-compatible data."""
        return cls(
            load_bundled=bool(data.get("load_bundled", True)),
            load_user=bool(data.get("load_user", True)),
            load_entry_points=bool(data.get("load_entry_points", True)),
            disabled_plugin_keys=_as_str_list(data.get("disabled_plugin_keys"), []),
        )


@dataclass
class AppPreferences:
    """Root persisted preference document."""

    version: int = 1
    editor: EditorSettings = field(default_factory=EditorSettings)
    theme: ThemeSettings = field(default_factory=ThemeSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    plugins: PluginSettings = field(default_factory=PluginSettings)
    node_colors: dict[str, list[int]] = field(default_factory=dict)
    keybinds: dict[str, str] = field(default_factory=dict)
    node_create_slots: list[dict[str, Any]] = field(default_factory=list)
    pinned_actions: list[str] = field(
        default_factory=lambda: list(DEFAULT_PINNED_ACTIONS)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "editor": self.editor.to_dict(),
            "theme": self.theme.to_dict(),
            "performance": self.performance.to_dict(),
            "plugins": self.plugins.to_dict(),
            "node_colors": self.node_colors,
            "keybinds": self.keybinds,
            "node_create_slots": self.node_create_slots,
            "pinned_actions": self.pinned_actions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppPreferences:
        """Deserialize a preference document from JSON-compatible data."""
        return cls(
            version=int(data.get("version", 1)),
            editor=EditorSettings.from_dict(_as_dict(data.get("editor"))),
            theme=ThemeSettings.from_dict(_as_dict(data.get("theme"))),
            performance=PerformanceSettings.from_dict(
                _as_dict(data.get("performance"))
            ),
            plugins=PluginSettings.from_dict(_as_dict(data.get("plugins"))),
            node_colors=_node_colors_from_raw(data.get("node_colors")),
            keybinds=_str_str_map(data.get("keybinds")),
            node_create_slots=_dict_list(data.get("node_create_slots")),
            pinned_actions=_as_str_list(
                data.get("pinned_actions"), list(DEFAULT_PINNED_ACTIONS)
            ),
        )

    @classmethod
    def defaults(cls) -> AppPreferences:
        """Return factory-default preferences."""
        return cls()
