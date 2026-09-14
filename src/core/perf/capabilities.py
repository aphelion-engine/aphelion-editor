"""Hardware detection used to derive sensible "Auto" performance settings.

Two tiers of detection exist on purpose:

**Cheap (always safe, sub-millisecond)**
    CPU counts, physical RAM, platform, Python version. These are read via
    ``os``/``ctypes`` and never shell out, so they can run during startup.

**Expensive (on demand only)**
    FFmpeg's advertised hardware encoders and the display adapter name.
    These spawn a subprocess, so they are only executed when the user hits
    *Auto Configure Performance* in Preferences, and the result is cached
    in memory.

Nothing here may raise: a machine we cannot interrogate simply reports
conservative values and the editor falls back to software paths.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
import threading
from dataclasses import dataclass, replace

__all__ = [
    "HardwareCapabilities",
    "clear_capability_cache",
    "detect_capabilities",
    "probe_ffmpeg_encoders",
]

#: Encoder names we can usefully offer when FFmpeg reports them.
KNOWN_HARDWARE_ENCODERS: tuple[str, ...] = (
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "h264_qsv",
    "hevc_qsv",
    "av1_qsv",
    "h264_amf",
    "hevc_amf",
    "h264_vaapi",
    "hevc_vaapi",
    "h264_videotoolbox",
    "hevc_videotoolbox",
)


@dataclass(frozen=True, slots=True)
class HardwareCapabilities:
    """Snapshot of the machine's relevant resources."""

    cpu_logical: int = 4
    cpu_physical: int = 4
    ram_total_mb: int = 8192
    ram_available_mb: int = 4096
    platform: str = ""
    python_version: str = ""
    gpu_name: str = ""
    hardware_encoders: tuple[str, ...] = ()
    detected_expensive: bool = False
    #: ``"native"`` when the optional C extension is built and importable,
    #: ``"python"`` when the NumPy/OpenCV fallbacks are in use.
    frame_backend: str = ""
    #: Version reported by the native extension, or 0.
    native_version: int = 0

    # ------------------------------------------------------------------
    # Derived classifications
    # ------------------------------------------------------------------

    @property
    def native_kernels(self) -> bool:
        """Whether the native frame kernels are available."""
        return self.frame_backend == "native"

    @property
    def is_low_end(self) -> bool:
        """Whether this machine should default to the Eco profile."""
        return self.cpu_logical <= 8 or self.ram_total_mb <= 16 * 1024

    @property
    def is_high_end(self) -> bool:
        """Whether this machine can use the Performance/Maximum profiles."""
        return self.cpu_logical >= 16 and self.ram_total_mb >= 32 * 1024

    @property
    def hardware_decode_supported(self) -> bool:
        """Whether any hardware decoder is likely available.

        OpenCV exposes no reliable capability query, so we infer from the
        presence of hardware *encoders* (same vendor stack) or a discrete
        GPU. Hardware decode remains strictly best-effort.
        """
        if self.hardware_encoders:
            return True
        name = self.gpu_name.lower()
        return any(
            token in name
            for token in ("nvidia", "geforce", "quadro", "radeon", "intel", "arc")
        )

    @property
    def preferred_hardware_encoder(self) -> str:
        """Best available H.264 hardware encoder, or ``""`` for software."""
        for candidate in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi", "h264_videotoolbox"):
            if candidate in self.hardware_encoders:
                return candidate
        return ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation for diagnostics."""
        return {
            "cpu_logical": self.cpu_logical,
            "cpu_physical": self.cpu_physical,
            "ram_total_mb": self.ram_total_mb,
            "ram_available_mb": self.ram_available_mb,
            "platform": self.platform,
            "python_version": self.python_version,
            "gpu_name": self.gpu_name,
            "hardware_encoders": list(self.hardware_encoders),
            "hardware_decode_supported": self.hardware_decode_supported,
            "frame_backend": self.frame_backend,
            "native_version": self.native_version,
            "is_low_end": self.is_low_end,
            "is_high_end": self.is_high_end,
        }


def _frame_backend(refresh: bool = False) -> tuple[str, int]:
    """Return ``(backend, version)`` for the frame kernel implementation.

    Never raises: a missing or broken native extension is a normal, supported
    configuration, not an error. ``refresh`` re-attempts the import so a
    user who builds the extension without restarting sees it reported.
    """
    try:
        from core.native import probe

        info = probe(refresh=refresh)
        return info.backend, int(info.version)
    except Exception:  # noqa: BLE001
        return "python", 0


# ----------------------------------------------------------------------
# Physical memory
# ----------------------------------------------------------------------


class _MemoryStatusEx(ctypes.Structure):
    """Win32 ``MEMORYSTATUSEX`` used for RAM detection."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _physical_memory_mb() -> tuple[int, int]:
    """Return ``(total_mb, available_mb)`` without requiring psutil."""
    try:  # Optional dependency: use it when present.
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        return int(memory.total // (1024 * 1024)), int(memory.available // (1024 * 1024))
    except Exception:  # noqa: BLE001 - psutil is optional
        pass

    if sys.platform == "win32":
        try:
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return (
                    int(status.ullTotalPhys // (1024 * 1024)),
                    int(status.ullAvailPhys // (1024 * 1024)),
                )
        except Exception:  # noqa: BLE001
            pass

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")  # type: ignore[attr-defined]
        total_pages = os.sysconf("SC_PHYS_PAGES")  # type: ignore[attr-defined]
        available_pages = os.sysconf("SC_AVPHYS_PAGES")  # type: ignore[attr-defined]
        return (
            int(page_size * total_pages // (1024 * 1024)),
            int(page_size * available_pages // (1024 * 1024)),
        )
    except Exception:  # noqa: BLE001
        pass

    return 8192, 4096


def _physical_core_count(logical: int) -> int:
    """Best-effort physical core count, falling back to ``logical // 2``."""
    try:
        import psutil  # type: ignore

        physical = psutil.cpu_count(logical=False)
        if physical:
            return int(physical)
    except Exception:  # noqa: BLE001
        pass
    return max(1, logical // 2)


# ----------------------------------------------------------------------
# Expensive detection
# ----------------------------------------------------------------------


def _ffmpeg_executable() -> str | None:
    """Locate an FFmpeg binary via ``imageio-ffmpeg`` (already a dependency)."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def probe_ffmpeg_encoders(timeout: float = 8.0) -> tuple[str, ...]:
    """Return the hardware encoders the local FFmpeg advertises.

    Always returns a tuple — an unavailable FFmpeg yields ``()`` rather
    than raising, so export simply stays on the software encoder.
    """
    executable = _ffmpeg_executable()
    if not executable:
        return ()
    try:
        completed = subprocess.run(
            [executable, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return ()

    found = [
        name
        for name in KNOWN_HARDWARE_ENCODERS
        if name in (completed.stdout or "")
    ]
    return tuple(found)


def _detect_gpu_name() -> str:
    """Return the primary display adapter name, or ``""`` when unknown."""
    if sys.platform == "win32":
        try:
            completed = subprocess.run(
                [
                    "wmic",
                    "path",
                    "win32_VideoController",
                    "get",
                    "name",
                ],
                capture_output=True,
                text=True,
                timeout=6.0,
                check=False,
            )
            lines = [
                line.strip()
                for line in (completed.stdout or "").splitlines()
                if line.strip() and line.strip().lower() != "name"
            ]
            if lines:
                return lines[0]
        except Exception:  # noqa: BLE001
            pass
    return ""


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_CACHE: HardwareCapabilities | None = None


def detect_capabilities(
    refresh: bool = False,
    include_expensive: bool = False,
) -> HardwareCapabilities:
    """Return cached hardware capabilities.

    Parameters:
        refresh: Re-run detection even when a cached value exists.
        include_expensive: Also probe FFmpeg encoders and the GPU name
            (spawns subprocesses; only call from an explicit user action).

    Returns:
        A :class:`HardwareCapabilities` snapshot. Never raises.
    """
    global _CACHE
    with _CACHE_LOCK:
        cached = _CACHE

    if (
        cached is not None
        and not refresh
        and (cached.detected_expensive or not include_expensive)
    ):
        return cached

    logical = max(1, os.cpu_count() or 4)
    total_mb, available_mb = _physical_memory_mb()
    backend, native_version = _frame_backend(refresh=refresh)
    base = HardwareCapabilities(
        cpu_logical=logical,
        cpu_physical=_physical_core_count(logical),
        ram_total_mb=total_mb,
        ram_available_mb=available_mb,
        platform=f"{platform.system()} {platform.release()}",
        python_version=platform.python_version(),
        gpu_name=cached.gpu_name if cached else "",
        hardware_encoders=cached.hardware_encoders if cached else (),
        detected_expensive=cached.detected_expensive if cached else False,
        frame_backend=backend,
        native_version=native_version,
    )

    if include_expensive and (refresh or not base.detected_expensive):
        base = replace(
            base,
            gpu_name=_detect_gpu_name() or base.gpu_name,
            hardware_encoders=probe_ffmpeg_encoders() or base.hardware_encoders,
            detected_expensive=True,
        )

    with _CACHE_LOCK:
        _CACHE = base
    return base


def clear_capability_cache() -> None:
    """Forget the cached capability snapshot (used by tests)."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
