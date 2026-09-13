"""Application preference models (Qt-free)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.constants import (AUTO_WORKER_THREADS, AUTOSAVE_INTERVAL_MS,
                              DEFAULT_DECODE_CACHE_FRAMES,
                              DEFAULT_MAX_PREFETCH_FRAMES,
                              DEFAULT_MAX_PREVIEW_SCALE,
                              DEFAULT_MIN_PREVIEW_SCALE,
                              DEFAULT_PLAYBACK_PROXY_WIDTH,
                              DEFAULT_PREFETCH_MAX_MB,
                              DEFAULT_RENDER_QUEUE_DEPTH,
                              DEFAULT_SCRUB_QUALITY_PERCENT,
                              DEFAULT_THUMBNAIL_CACHE_MB,
                              FRAME_CACHE_MAX_ALLOWED_MB, FRAME_CACHE_MAX_MB,
                              FRAME_CACHE_MIN_MB, MAX_DECODE_CACHE_FRAMES,
                              MAX_MAX_PREFETCH_FRAMES, MAX_PREFETCH_MAX_MB,
                              MAX_RENDER_QUEUE_DEPTH)
from config.theme_tokens import ThemeTokens, aphelion_dark, builtin_theme
from core.perf.scheduler import MAX_WORKER_THREADS
from ui.node_graph import operations as node_ops

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

#: Current on-disk preferences schema version.
#:
#: ``1`` — original document: a flat ``[performance]`` section whose only
#: frame-dropping control was the boolean ``drop_frames_during_playback``.
#: ``2`` — performance overhaul: explicit ``drop_frames_mode`` ladder, preview
#: scaling, scrub quality, worker/CPU budget, GPU codec and render controls.
#:
#: Reading is always backwards compatible (missing keys fall back to the
#: dataclass defaults). This constant only records semantic changes so a
#: migrated document can be recognized on the next load.
PREFERENCES_VERSION: int = 2


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

    graph_layout_mode: node_ops.GraphLayoutMode = node_ops.GraphLayoutMode.HIERARCHICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "editor_font_family": self.editor_font_family,
            "editor_font_size": self.editor_font_size,
            "show_graph_grid": self.show_graph_grid,
            "autosave_enabled": self.autosave_enabled,
            "autosave_interval_ms": self.autosave_interval_ms,
            "show_status_key_hints": self.show_status_key_hints,
            "show_pin_bar": self.show_pin_bar,
            "graph_layout_mode": self.graph_layout_mode.value,
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

    Every "Auto" value is ``0`` (or an empty string) meaning *derive from
    detected hardware*; see :mod:`core.perf.capabilities` and
    :mod:`core.perf.presets`. Unknown values read from disk are clamped
    rather than rejected so older/newer preference files always load.
    """

    # --- Profile -----------------------------------------------------
    performance_profile: str = "balanced"

    # --- Memory / cache ---------------------------------------------
    frame_cache_mb: int = FRAME_CACHE_MAX_MB
    decode_cache_frames: int = DEFAULT_DECODE_CACHE_FRAMES

    # --- Prefetch ----------------------------------------------------
    prefetch_enabled: bool = True
    adaptive_prefetch: bool = True
    max_prefetch_frames: int = DEFAULT_MAX_PREFETCH_FRAMES

    # --- Preview quality --------------------------------------------
    adaptive_preview_enabled: bool = True
    auto_proxy_enabled: bool = True
    min_preview_scale_percent: int = DEFAULT_MIN_PREVIEW_SCALE
    max_preview_scale_percent: int = DEFAULT_MAX_PREVIEW_SCALE
    playback_proxy_override_enabled: bool = False
    playback_proxy_width: int = DEFAULT_PLAYBACK_PROXY_WIDTH
    high_quality_when_paused: bool = True

    # --- Frame dropping ---------------------------------------------
    drop_frames_during_playback: bool = True
    drop_frames_mode: str = "ADAPTIVE"
    target_preview_fps: int = 0  # 0 = follow the project frame rate

    # --- Scrubbing ---------------------------------------------------
    scrub_quality_percent: int = DEFAULT_SCRUB_QUALITY_PERCENT
    auto_scrub_quality: bool = True
    high_quality_after_scrub: bool = True
    # Reserved: no node currently declares itself "heavy", so there is
    # nothing to bypass yet. Persisted so the schema and presets are
    # already stable when cost classification lands.
    bypass_heavy_effects_during_scrub: bool = True
    bypass_heavy_effects_during_playback: bool = False

    # --- CPU / workers ----------------------------------------------
    worker_threads: int = AUTO_WORKER_THREADS
    # Reserved: OpenCV/FFmpeg thread coordination is not implemented.
    cpu_thread_budget: int = 0
    pause_background_during_playback: bool = True

    # --- GPU / hardware codecs --------------------------------------
    hardware_decode_enabled: bool = False
    # Reserved: the exporter always uses the software encoder today.
    hardware_encode_enabled: bool = False
    preferred_hardware_encoder: str = ""

    # --- Render / export (reserved) ---------------------------------
    # Export already overlaps graph and encode work; these knobs are
    # persisted for the configurable render pipeline but are not read yet.
    render_workers: int = 0
    render_queue_depth: int = DEFAULT_RENDER_QUEUE_DEPTH
    ffmpeg_threads: int = 0
    parallel_frame_evaluation: bool = False

    # --- Tracking (reserved) ----------------------------------------
    # Tracking still uses its own strategy; nothing reads these yet.
    tracking_quality: str = "balanced"
    tracking_workers: int = 0
    optical_flow_fast_path: bool = True
    pyramid_tracking: bool = True

    # --- Diagnostics -------------------------------------------------
    show_performance_overlay: bool = False
    performance_diagnostics: bool = False
    # Reserved: no scratch-buffer pool exists yet.
    frame_buffer_pool: bool = True
    # Reserved: there is no thumbnail subsystem to budget for.
    thumbnail_cache_mb: int = DEFAULT_THUMBNAIL_CACHE_MB
    automatic_cache_distribution: bool = True
    prefetch_max_mb: int = DEFAULT_PREFETCH_MAX_MB

    #: Unrecognized keys from a newer/older build, round-tripped untouched.
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def effective_drop_mode(self) -> str:
        """Frame-drop mode, honouring the legacy on/off checkbox."""
        if not self.drop_frames_during_playback:
            return "OFF"
        return str(self.drop_frames_mode or "ADAPTIVE").upper()

    @property
    def profile(self) -> "PerformanceProfile":
        """Parsed :class:`~core.perf.presets.PerformanceProfile`."""
        from core.perf.presets import PerformanceProfile

        return PerformanceProfile.from_value(self.performance_profile)

    def with_profile(self, profile: "PerformanceProfile") -> "PerformanceSettings":
        """Return a copy with ``profile`` applied (hardware-aware)."""
        from core.perf.presets import apply_profile

        return apply_profile(self, profile)

    @classmethod
    def auto_configured(cls) -> "PerformanceSettings":
        """Return settings auto-configured for this machine."""
        from core.perf.capabilities import detect_capabilities
        from core.perf.presets import apply_profile, recommend_profile

        caps = detect_capabilities(include_expensive=True)
        return apply_profile(cls(), recommend_profile(caps), caps)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "performance_profile": self.performance_profile,
            "frame_cache_mb": self.frame_cache_mb,
            "thumbnail_cache_mb": self.thumbnail_cache_mb,
            "automatic_cache_distribution": self.automatic_cache_distribution,
            "decode_cache_frames": self.decode_cache_frames,
            "prefetch_enabled": self.prefetch_enabled,
            "adaptive_prefetch": self.adaptive_prefetch,
            "max_prefetch_frames": self.max_prefetch_frames,
            "prefetch_max_mb": self.prefetch_max_mb,
            "adaptive_preview_enabled": self.adaptive_preview_enabled,
            "auto_proxy_enabled": self.auto_proxy_enabled,
            "min_preview_scale_percent": self.min_preview_scale_percent,
            "max_preview_scale_percent": self.max_preview_scale_percent,
            "playback_proxy_override_enabled": self.playback_proxy_override_enabled,
            "playback_proxy_width": self.playback_proxy_width,
            "high_quality_when_paused": self.high_quality_when_paused,
            "drop_frames_during_playback": self.drop_frames_during_playback,
            "drop_frames_mode": self.drop_frames_mode,
            "target_preview_fps": self.target_preview_fps,
            "scrub_quality_percent": self.scrub_quality_percent,
            "auto_scrub_quality": self.auto_scrub_quality,
            "high_quality_after_scrub": self.high_quality_after_scrub,
            "bypass_heavy_effects_during_scrub": self.bypass_heavy_effects_during_scrub,
            "bypass_heavy_effects_during_playback": self.bypass_heavy_effects_during_playback,
            "worker_threads": self.worker_threads,
            "cpu_thread_budget": self.cpu_thread_budget,
            "pause_background_during_playback": self.pause_background_during_playback,
            "hardware_decode_enabled": self.hardware_decode_enabled,
            "hardware_encode_enabled": self.hardware_encode_enabled,
            "preferred_hardware_encoder": self.preferred_hardware_encoder,
            "render_workers": self.render_workers,
            "render_queue_depth": self.render_queue_depth,
            "ffmpeg_threads": self.ffmpeg_threads,
            "parallel_frame_evaluation": self.parallel_frame_evaluation,
            "tracking_quality": self.tracking_quality,
            "tracking_workers": self.tracking_workers,
            "optical_flow_fast_path": self.optical_flow_fast_path,
            "pyramid_tracking": self.pyramid_tracking,
            "show_performance_overlay": self.show_performance_overlay,
            "performance_diagnostics": self.performance_diagnostics,
            "frame_buffer_pool": self.frame_buffer_pool,
        }
        # Keys written by a newer build (or an experimental knob) survive a
        # load/save cycle instead of being silently dropped.
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceSettings:
        """Deserialize with per-field clamping and legacy-key migration.

        Legacy keys:
            * ``frame_cache_mb`` before validation existed could be any
              integer — it is now clamped to the supported range.
            * ``drop_frames_during_playback=False`` with no explicit mode
              maps to ``OFF`` rather than the default ``ADAPTIVE``.
        """
        raw_mode = data.get("drop_frames_mode")
        drop_enabled = bool(data.get("drop_frames_during_playback", True))
        if raw_mode is None:
            mode = "OFF" if not drop_enabled else "ADAPTIVE"
        else:
            mode = str(raw_mode).strip().upper()
            if mode not in _VALID_DROP_MODES:
                mode = "ADAPTIVE" if drop_enabled else "OFF"

        profile = str(data.get("performance_profile",
                      "balanced")).strip().lower()
        if profile not in _VALID_PROFILES:
            profile = "balanced"

        min_scale = _clamp(
            int(data.get("min_preview_scale_percent", DEFAULT_MIN_PREVIEW_SCALE)),
            5,
            100,
        )
        max_scale = _clamp(
            int(data.get("max_preview_scale_percent", DEFAULT_MAX_PREVIEW_SCALE)),
            min_scale,
            100,
        )

        tracking_quality = str(
            data.get("tracking_quality", "balanced")).strip().lower()
        if tracking_quality not in _VALID_TRACKING_QUALITY:
            tracking_quality = "balanced"

        worker_threads = _clamp(
            int(data.get("worker_threads", AUTO_WORKER_THREADS)),
            0,
            MAX_WORKER_THREADS,
        )

        return cls(
            performance_profile=profile,
            frame_cache_mb=_clamp(
                int(data.get("frame_cache_mb", FRAME_CACHE_MAX_MB)),
                FRAME_CACHE_MIN_MB,
                FRAME_CACHE_MAX_ALLOWED_MB,
            ),
            thumbnail_cache_mb=_clamp(
                int(data.get("thumbnail_cache_mb", DEFAULT_THUMBNAIL_CACHE_MB)),
                0,
                FRAME_CACHE_MAX_ALLOWED_MB,
            ),
            automatic_cache_distribution=bool(
                data.get("automatic_cache_distribution", True)
            ),
            decode_cache_frames=_clamp(
                int(data.get("decode_cache_frames", DEFAULT_DECODE_CACHE_FRAMES)),
                1,
                MAX_DECODE_CACHE_FRAMES,
            ),
            prefetch_enabled=bool(data.get("prefetch_enabled", True)),
            adaptive_prefetch=bool(data.get("adaptive_prefetch", True)),
            max_prefetch_frames=_clamp(
                int(data.get("max_prefetch_frames", DEFAULT_MAX_PREFETCH_FRAMES)),
                0,
                MAX_MAX_PREFETCH_FRAMES,
            ),
            prefetch_max_mb=_clamp(
                int(data.get("prefetch_max_mb", DEFAULT_PREFETCH_MAX_MB)),
                32,
                MAX_PREFETCH_MAX_MB,
            ),
            adaptive_preview_enabled=bool(data.get("adaptive_preview_enabled", True)),
            auto_proxy_enabled=bool(data.get("auto_proxy_enabled", True)),
            min_preview_scale_percent=min_scale,
            max_preview_scale_percent=max_scale,
            playback_proxy_override_enabled=bool(
                data.get("playback_proxy_override_enabled", False)
            ),
            playback_proxy_width=_clamp(
                int(data.get("playback_proxy_width", DEFAULT_PLAYBACK_PROXY_WIDTH)),
                160,
                3840,
            ),
            high_quality_when_paused=bool(
                data.get("high_quality_when_paused", True)),
            drop_frames_during_playback=drop_enabled,
            drop_frames_mode=mode,
            target_preview_fps=_clamp(
                int(data.get("target_preview_fps", 0)), 0, 240
            ),
            scrub_quality_percent=_clamp(
                int(data.get("scrub_quality_percent",
                    DEFAULT_SCRUB_QUALITY_PERCENT)),
                5,
                100,
            ),
            auto_scrub_quality=bool(data.get("auto_scrub_quality", True)),
            high_quality_after_scrub=bool(
                data.get("high_quality_after_scrub", True)),
            bypass_heavy_effects_during_scrub=bool(
                data.get("bypass_heavy_effects_during_scrub", True)
            ),
            bypass_heavy_effects_during_playback=bool(
                data.get("bypass_heavy_effects_during_playback", False)
            ),
            worker_threads=worker_threads,
            cpu_thread_budget=_clamp(
                int(data.get("cpu_thread_budget", 0)), 0, MAX_WORKER_THREADS * 4
            ),
            pause_background_during_playback=bool(
                data.get("pause_background_during_playback", True)
            ),
            hardware_decode_enabled=bool(
                data.get("hardware_decode_enabled", False)),
            hardware_encode_enabled=bool(
                data.get("hardware_encode_enabled", False)),
            preferred_hardware_encoder=str(
                data.get("preferred_hardware_encoder", "")
            ),
            render_workers=_clamp(
                int(data.get("render_workers", 0)), 0, MAX_WORKER_THREADS),
            render_queue_depth=_clamp(
                int(data.get("render_queue_depth", DEFAULT_RENDER_QUEUE_DEPTH)),
                1,
                MAX_RENDER_QUEUE_DEPTH,
            ),
            ffmpeg_threads=_clamp(int(data.get("ffmpeg_threads", 0)), 0, 64),
            parallel_frame_evaluation=bool(
                data.get("parallel_frame_evaluation", False)
            ),
            tracking_quality=tracking_quality,
            tracking_workers=_clamp(
                int(data.get("tracking_workers", 0)), 0, MAX_WORKER_THREADS
            ),
            optical_flow_fast_path=bool(
                data.get("optical_flow_fast_path", True)),
            pyramid_tracking=bool(data.get("pyramid_tracking", True)),
            show_performance_overlay=bool(
                data.get("show_performance_overlay", False)
            ),
            performance_diagnostics=bool(
                data.get("performance_diagnostics", False)
            ),
            frame_buffer_pool=bool(data.get("frame_buffer_pool", True)),
            extra=_unknown_keys(data, _PERFORMANCE_KEYS),
        )


#: Every key :class:`PerformanceSettings` understands. Built lazily so it can
#: never drift out of sync with the dataclass definition.
_PERFORMANCE_KEYS: frozenset[str] = frozenset(
    name
    for name in PerformanceSettings.__dataclass_fields__
    if name != "extra"
)


def _unknown_keys(data: dict[str, Any], known: frozenset[str]) -> dict[str, Any]:
    """Return entries of ``data`` this build does not understand.

    Preserving them means a document written by a newer build (or by a build
    that had an experimental knob) is not silently stripped on save, so a
    user can move between builds without losing configuration.
    """
    return {str(key): value for key, value in data.items() if key not in known}


#: Accepted ``drop_frames_mode`` preference values.
_VALID_DROP_MODES: frozenset[str] = frozenset(
    {"OFF", "CONSERVATIVE", "BALANCED", "AGGRESSIVE", "ADAPTIVE"}
)

_VALID_PROFILES: frozenset[str] = frozenset(
    {"eco", "balanced", "performance", "maximum", "custom"}
)

_VALID_TRACKING_QUALITY: frozenset[str] = frozenset(
    {"fast", "balanced", "accurate"})



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
class AudioSettings:
    """Audio playback, export, and device preferences."""

    audio_enabled: bool = True
    master_volume: float = 1.0
    host_api_name: str = ""
    default_device_index: int = -1  # -1 means system default
    latency_preset: str = "balanced"
    buffer_size: int = 8  # Number of queued audio chunks
    stream_blocksize: int = 512
    output_sample_rate: int = 48000
    output_channels: int = 2
    export_audio_enabled: bool = True
    export_sample_rate: int = 48000
    export_channels: int = 2

    def to_dict(self) -> dict[str, Any]:
        """Serialize audio preferences to JSON-compatible data."""
        return {
            "audio_enabled": self.audio_enabled,
            "master_volume": self.master_volume,
            "host_api_name": self.host_api_name,
            "default_device_index": self.default_device_index,
            "latency_preset": self.latency_preset,
            "buffer_size": self.buffer_size,
            "stream_blocksize": self.stream_blocksize,
            "output_sample_rate": self.output_sample_rate,
            "output_channels": self.output_channels,
            "export_audio_enabled": self.export_audio_enabled,
            "export_sample_rate": self.export_sample_rate,
            "export_channels": self.export_channels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioSettings:
        """Deserialize audio preferences from JSON-compatible data."""
        blocksize = int(data.get("stream_blocksize", 512))
        if blocksize not in {0, 128, 256, 512, 1024, 2048}:
            blocksize = 512
        output_sample_rate = int(data.get("output_sample_rate", 48000))
        if output_sample_rate not in {44100, 48000, 96000}:
            output_sample_rate = 48000
        output_channels = int(data.get("output_channels", 2))
        if output_channels not in {1, 2}:
            output_channels = 2
        export_sample_rate = int(data.get("export_sample_rate", 48000))
        if export_sample_rate not in {44100, 48000, 96000}:
            export_sample_rate = 48000
        export_channels = int(data.get("export_channels", 2))
        if export_channels not in {1, 2}:
            export_channels = 2
        latency_preset = str(data.get("latency_preset", "balanced")).lower()
        if latency_preset not in {"low", "balanced", "safe"}:
            latency_preset = "balanced"
        return cls(
            audio_enabled=bool(data.get("audio_enabled", True)),
            master_volume=max(0.0, min(2.0, float(data.get("master_volume", 1.0)))),
            host_api_name=str(data.get("host_api_name", "")),
            default_device_index=int(data.get("default_device_index", -1)),
            latency_preset=latency_preset,
            buffer_size=max(2, min(20, int(data.get("buffer_size", 8)))),
            stream_blocksize=blocksize,
            output_sample_rate=output_sample_rate,
            output_channels=output_channels,
            export_audio_enabled=bool(data.get("export_audio_enabled", True)),
            export_sample_rate=export_sample_rate,
            export_channels=export_channels,
        )


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
    """Root persisted preference document.

    Versioning
    ----------
    :data:`PREFERENCES_VERSION` is bumped whenever the *meaning* of an
    existing key changes. Adding a brand-new key with a sensible default
    does **not** require a bump: :meth:`from_dict` fills missing keys from
    the dataclass defaults, so a v1 file keeps working unchanged.

    Unknown keys are preserved verbatim in :attr:`extra` (and in each
    section's own ``extra``), so a document written by a newer build — or
    by a build that had a experimental knob — is never silently stripped
    when it is saved again.
    """

    version: int = PREFERENCES_VERSION
    editor: EditorSettings = field(default_factory=EditorSettings)
    theme: ThemeSettings = field(default_factory=ThemeSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    plugins: PluginSettings = field(default_factory=PluginSettings)
    node_colors: dict[str, list[int]] = field(default_factory=dict)
    keybinds: dict[str, str] = field(default_factory=dict)
    node_create_slots: list[dict[str, Any]] = field(default_factory=list)
    pinned_actions: list[str] = field(
        default_factory=lambda: list(DEFAULT_PINNED_ACTIONS)
    )
    #: Unrecognized top-level keys, round-tripped untouched.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible data.

        The on-disk version is always the current schema version: once a
        document has been loaded and migrated in memory, saving it must
        record that fact, otherwise the migration would run on every start.
        """
        payload: dict[str, Any] = {
            "version": PREFERENCES_VERSION,
            "editor": self.editor.to_dict(),
            "theme": self.theme.to_dict(),
            "performance": self.performance.to_dict(),
            "audio": self.audio.to_dict(),
            "plugins": self.plugins.to_dict(),
            "node_colors": self.node_colors,
            "keybinds": self.keybinds,
            "node_create_slots": self.node_create_slots,
            "pinned_actions": self.pinned_actions,
        }
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppPreferences:
        """Deserialize a preference document, migrating older versions.

        This never raises for malformed *content*: unreadable sections fall
        back to defaults so a hand-edited or truncated file cannot prevent
        the editor from starting.
        """
        raw_version = data.get("version", 1)
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            version = 1

        performance_raw = dict(_as_dict(data.get("performance")))
        if version < 2:
            _migrate_performance_v1(performance_raw)

        known_top_level = {
            "version", "editor", "theme", "performance", "audio", "plugins",
            "node_colors", "keybinds", "node_create_slots", "pinned_actions",
        }
        extra = {
            str(key): value
            for key, value in data.items()
            if key not in known_top_level
        }

        return cls(
            version=PREFERENCES_VERSION,
            editor=EditorSettings.from_dict(_as_dict(data.get("editor"))),
            theme=ThemeSettings.from_dict(_as_dict(data.get("theme"))),
            performance=PerformanceSettings.from_dict(performance_raw),
            audio=AudioSettings.from_dict(_as_dict(data.get("audio"))),
            plugins=PluginSettings.from_dict(_as_dict(data.get("plugins"))),
            node_colors=_node_colors_from_raw(data.get("node_colors")),
            keybinds=_str_str_map(data.get("keybinds")),
            node_create_slots=_dict_list(data.get("node_create_slots")),
            pinned_actions=_as_str_list(
                data.get("pinned_actions"), list(DEFAULT_PINNED_ACTIONS)
            ),
            extra=extra,
        )

    @classmethod
    def defaults(cls) -> AppPreferences:
        """Return factory-default preferences."""
        return cls()

    @property
    def schema_version(self) -> int:
        """The schema version this document currently confirms to."""
        return PREFERENCES_VERSION


def _migrate_performance_v1(performance: dict[str, Any]) -> None:
    """Rewrite a v1 ``[performance]`` section in place.

    v1 had a single boolean, ``drop_frames_during_playback``. v2 introduced
    an explicit ``drop_frames_mode`` ladder. The upgrade preserves the
    user's intent exactly:

    * ``False`` (never drop) becomes ``OFF`` rather than silently turning
      frame dropping back on.
    * ``True`` becomes ``ADAPTIVE``, the new balanced default.
    * A missing key keeps whatever the current default is.

    The legacy boolean is retained so a user who downgrades to a build that
    only understands v1 still sees their setting honoured.
    """
    if "drop_frames_mode" in performance:
        return
    legacy = performance.get("drop_frames_during_playback")
    if legacy is None:
        return
    performance["drop_frames_mode"] = "ADAPTIVE" if bool(legacy) else "OFF"
