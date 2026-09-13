"""Named performance profiles and machine-aware auto configuration.

A profile is a bundle of :class:`~core.preferences.models.PerformanceSettings`
values chosen to be internally consistent. ``Custom`` keeps whatever the
user has configured and is never applied automatically.

Presets are computed from :class:`HardwareCapabilities` rather than being
hardcoded, so a 6-core/16 GB laptop and a 32-core/128 GB workstation get
different cache budgets and worker counts from the same profile name.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.perf.capabilities import HardwareCapabilities, detect_capabilities
from core.perf.scheduler import recommended_worker_count

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.preferences.models import PerformanceSettings

__all__ = [
    "PROFILE_LABELS",
    "PerformanceProfile",
    "apply_profile",
    "profile_overrides",
    "recommend_profile",
]


class PerformanceProfile(str, Enum):
    """User-selectable performance posture."""

    ECO = "eco"
    BALANCED = "balanced"
    PERFORMANCE = "performance"
    MAXIMUM = "maximum"
    CUSTOM = "custom"

    @classmethod
    def from_value(cls, value: object) -> "PerformanceProfile":
        """Parse a stored preference value, defaulting to ``BALANCED``."""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.BALANCED

    @property
    def label(self) -> str:
        """Display name for the preferences combo box."""
        return PROFILE_LABELS.get(self, self.value.title())


PROFILE_LABELS: dict[PerformanceProfile, str] = {
    PerformanceProfile.ECO: "Eco",
    PerformanceProfile.BALANCED: "Balanced",
    PerformanceProfile.PERFORMANCE: "Performance",
    PerformanceProfile.MAXIMUM: "Maximum Performance",
    PerformanceProfile.CUSTOM: "Custom",
}


def _cache_budget_mb(caps: HardwareCapabilities, share: float, cap_mb: int) -> int:
    """Derive a frame-cache budget from total RAM, clamped to sane bounds."""
    usable = max(1024, caps.ram_total_mb)
    budget = int(usable * share)
    return max(256, min(cap_mb, budget))


def _prefetch_mb(caps: HardwareCapabilities, share: float, cap_mb: int) -> int:
    """Derive a prefetch memory ceiling from total RAM."""
    usable = max(1024, caps.ram_total_mb)
    return max(64, min(cap_mb, int(usable * share)))


def profile_overrides(
    profile: PerformanceProfile,
    caps: HardwareCapabilities | None = None,
) -> dict[str, Any]:
    """Return the setting overrides implied by ``profile``.

    Parameters:
        profile: Requested profile. ``CUSTOM`` yields an empty mapping.
        caps: Capability snapshot; detected on demand when omitted.

    Returns:
        A mapping of :class:`PerformanceSettings` field names to values.
        An empty mapping means "leave the user's values alone".
    """
    if profile is PerformanceProfile.CUSTOM:
        return {}

    capabilities = caps or detect_capabilities()
    base_workers = recommended_worker_count(capabilities.cpu_logical)

    if profile is PerformanceProfile.ECO:
        return {
            "performance_profile": PerformanceProfile.ECO.value,
            "frame_cache_mb": _cache_budget_mb(capabilities, 0.06, 512),
            "decode_cache_frames": 8,
            "max_prefetch_frames": 1,
            "prefetch_enabled": True,
            "adaptive_prefetch": False,
            "prefetch_max_mb": _prefetch_mb(capabilities, 0.01, 192),
            "adaptive_preview_enabled": True,
            "auto_proxy_enabled": True,
            "playback_proxy_override_enabled": True,
            "playback_proxy_width": 640,
            "max_preview_scale_percent": 50,
            "min_preview_scale_percent": 25,
            "high_quality_when_paused": True,
            "drop_frames_mode": "AGGRESSIVE",
            "scrub_quality_percent": 25,
            "auto_scrub_quality": True,
            "high_quality_after_scrub": True,
            "bypass_heavy_effects_during_playback": True,
            "bypass_heavy_effects_during_scrub": True,
            "worker_threads": max(1, base_workers - 1),
            "cpu_thread_budget": max(2, capabilities.cpu_logical // 2),
            "pause_background_during_playback": True,
            "hardware_decode_enabled": False,
            "hardware_encode_enabled": False,
            "parallel_frame_evaluation": False,
            "render_workers": 1,
            "render_queue_depth": 2,
            "ffmpeg_threads": 0,
            "thumbnail_cache_mb": 64,
            "automatic_cache_distribution": True,
            "tracking_quality": "fast",
            "tracking_workers": max(1, base_workers - 1),
            "optical_flow_fast_path": True,
            "pyramid_tracking": True,
            "frame_buffer_pool": True,
            "performance_diagnostics": False,
        }

    if profile is PerformanceProfile.BALANCED:
        return {
            "performance_profile": PerformanceProfile.BALANCED.value,
            "frame_cache_mb": _cache_budget_mb(capabilities, 0.12, 2048),
            "decode_cache_frames": 16,
            "max_prefetch_frames": 6,
            "prefetch_enabled": True,
            "adaptive_prefetch": True,
            "prefetch_max_mb": _prefetch_mb(capabilities, 0.02, 512),
            "adaptive_preview_enabled": True,
            "auto_proxy_enabled": True,
            "playback_proxy_override_enabled": False,
            "playback_proxy_width": 640,
            "max_preview_scale_percent": 100,
            "min_preview_scale_percent": 33,
            "high_quality_when_paused": True,
            "drop_frames_mode": "ADAPTIVE",
            "scrub_quality_percent": 50,
            "auto_scrub_quality": True,
            "high_quality_after_scrub": True,
            "bypass_heavy_effects_during_playback": False,
            "bypass_heavy_effects_during_scrub": True,
            "worker_threads": base_workers,
            "cpu_thread_budget": 0,
            "pause_background_during_playback": True,
            "hardware_decode_enabled": False,
            "hardware_encode_enabled": False,
            "parallel_frame_evaluation": False,
            "render_workers": 0,
            "render_queue_depth": 4,
            "ffmpeg_threads": 0,
            "thumbnail_cache_mb": 128,
            "automatic_cache_distribution": True,
            "tracking_quality": "balanced",
            "tracking_workers": base_workers,
            "optical_flow_fast_path": True,
            "pyramid_tracking": True,
            "frame_buffer_pool": True,
            "performance_diagnostics": False,
        }

    if profile is PerformanceProfile.PERFORMANCE:
        return {
            "performance_profile": PerformanceProfile.PERFORMANCE.value,
            "frame_cache_mb": _cache_budget_mb(capabilities, 0.25, 6144),
            "decode_cache_frames": 32,
            "max_prefetch_frames": 12,
            "prefetch_enabled": True,
            "adaptive_prefetch": True,
            "prefetch_max_mb": _prefetch_mb(capabilities, 0.04, 1024),
            "adaptive_preview_enabled": True,
            "auto_proxy_enabled": True,
            "playback_proxy_override_enabled": False,
            "playback_proxy_width": 960,
            "max_preview_scale_percent": 100,
            "min_preview_scale_percent": 50,
            "high_quality_when_paused": True,
            "drop_frames_mode": "BALANCED",
            "scrub_quality_percent": 75,
            "auto_scrub_quality": True,
            "high_quality_after_scrub": True,
            "bypass_heavy_effects_during_playback": False,
            "bypass_heavy_effects_during_scrub": False,
            "worker_threads": min(12, base_workers + 1),
            "cpu_thread_budget": 0,
            "pause_background_during_playback": False,
            "hardware_decode_enabled": capabilities.hardware_decode_supported,
            "hardware_encode_enabled": bool(capabilities.preferred_hardware_encoder),
            "parallel_frame_evaluation": True,
            "render_workers": max(2, base_workers),
            "render_queue_depth": 8,
            "ffmpeg_threads": 0,
            "thumbnail_cache_mb": 256,
            "automatic_cache_distribution": True,
            "tracking_quality": "balanced",
            "tracking_workers": base_workers,
            "optical_flow_fast_path": True,
            "pyramid_tracking": True,
            "frame_buffer_pool": True,
            "performance_diagnostics": False,
        }

    # PerformanceProfile.MAXIMUM
    return {
        "performance_profile": PerformanceProfile.MAXIMUM.value,
        "frame_cache_mb": _cache_budget_mb(capabilities, 0.40, 12288),
        "decode_cache_frames": 64,
        "max_prefetch_frames": 24,
        "prefetch_enabled": True,
        "adaptive_prefetch": True,
        "prefetch_max_mb": _prefetch_mb(capabilities, 0.06, 2048),
        "adaptive_preview_enabled": True,
        "auto_proxy_enabled": True,
        "playback_proxy_override_enabled": False,
        "playback_proxy_width": 1280,
        "max_preview_scale_percent": 100,
        "min_preview_scale_percent": 50,
        "high_quality_when_paused": True,
        "drop_frames_mode": "ADAPTIVE",
        "scrub_quality_percent": 100,
        "auto_scrub_quality": True,
        "high_quality_after_scrub": True,
        "bypass_heavy_effects_during_playback": False,
        "bypass_heavy_effects_during_scrub": False,
        "worker_threads": min(16, base_workers + 2),
        "cpu_thread_budget": 0,
        "pause_background_during_playback": False,
        "hardware_decode_enabled": capabilities.hardware_decode_supported,
        "hardware_encode_enabled": bool(capabilities.preferred_hardware_encoder),
        "parallel_frame_evaluation": True,
        "render_workers": max(2, base_workers + 1),
        "render_queue_depth": 16,
        "ffmpeg_threads": 0,
        "thumbnail_cache_mb": 512,
        "automatic_cache_distribution": True,
        "tracking_quality": "accurate",
        "tracking_workers": min(16, base_workers + 1),
        "optical_flow_fast_path": False,
        "pyramid_tracking": True,
        "frame_buffer_pool": True,
        "performance_diagnostics": False,
    }


def recommend_profile(caps: HardwareCapabilities | None = None) -> PerformanceProfile:
    """Return the profile best suited to the detected hardware.

    ``available`` RAM (not total) is used when present, so a machine with
    32 GB installed but only 6 GB free does not get a 12 GB cache budget.
    """
    capabilities = caps or detect_capabilities()
    effective_ram = capabilities.ram_available_mb or capabilities.ram_total_mb

    if capabilities.cpu_logical <= 4 or effective_ram <= 8 * 1024:
        return PerformanceProfile.ECO
    if capabilities.cpu_logical >= 16 and effective_ram >= 32 * 1024:
        return PerformanceProfile.MAXIMUM
    if capabilities.cpu_logical >= 10 and effective_ram >= 16 * 1024:
        return PerformanceProfile.PERFORMANCE
    return PerformanceProfile.BALANCED


def apply_profile(
    settings: "PerformanceSettings",
    profile: PerformanceProfile,
    caps: HardwareCapabilities | None = None,
) -> "PerformanceSettings":
    """Return a copy of ``settings`` with ``profile`` applied.

    Unknown/unsupported field names in the preset table are ignored, so a
    preset can add a knob before the settings model gains the field.
    """
    overrides = profile_overrides(profile, caps)
    if not overrides:
        return settings

    allowed = set(getattr(type(settings), "__dataclass_fields__", {}))
    payload = {key: value for key, value in overrides.items() if key in allowed}
    return replace(settings, **payload)
