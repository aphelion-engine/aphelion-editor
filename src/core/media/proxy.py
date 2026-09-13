"""Real editing proxies: persistent, all-intra, background-generated.

Why the old approach was not enough
-----------------------------------
Playback proxying previously meant *scaling the frame after decoding it*.
That reduces graph cost, but it does nothing about the part that actually
makes scrubbing painful: seeking and decoding a long-GOP H.264/H.265 source.
A seek into a 250-frame GOP means finding the keyframe, then decoding up to
249 frames to reach the one requested. No amount of post-decode downscaling
can fix that.

What a real proxy is
--------------------
A separate, *regenerable* media file transcoded to a codec designed for
editing:

* **every frame is a keyframe** (``-g 1``), so any frame is reachable in one
  decode step regardless of position — seek cost becomes roughly constant
  instead of growing with GOP length;
* **low resolution** (720p/540p/360p), so each decoded frame is 4-16x
  cheaper to move;
* **stored in a cache directory** keyed by source identity, so it survives
  restarts and is regenerated only when the source or the proxy recipe
  changes.

The original file is never modified or replaced: the timeline still refers
to it, export always reads it, and a proxy is only ever an *interactive*
substitute.

Frame mapping
-------------
The proxy is encoded at the source's declared frame rate with every frame
retained, so frame *N* of the proxy is frame *N* of the source. That is
verified after encoding (frame count must match within a small tolerance)
and a proxy that fails verification is deleted rather than trusted.

Scheduling
----------
Generation runs on the shared background scheduler, so it:
* never blocks the UI or project load;
* yields to playback (the scheduler's background bands pause while playing);
* is de-duplicated per source, so ten callers asking for the same proxy
  produce one job.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from core.perf.scheduler import JobPriority, get_scheduler
from utils.logging_setup import get_logger

_LOG = get_logger("core.media.proxy")

__all__ = [
    "ProxyManager",
    "ProxySpec",
    "ProxyStatus",
    "ProxyState",
    "get_proxy_manager",
]


#: Bumped whenever the encoding recipe changes, so stale proxies are
#: transparently regenerated instead of being reused.
PROXY_RECIPE_VERSION: int = 1


class ProxyState(str, Enum):
    """Lifecycle of one source's proxy."""

    NONE = "none"
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProxySpec:
    """How a proxy should be produced."""

    #: Target height in pixels. Width follows the source aspect ratio.
    height: int = 540
    #: Constant-rate factor; 18 keeps preview proxies visually clean.
    crf: int = 20
    #: Encoder preset. ``ultrafast`` trades size for generation speed, which
    #: is the right trade for a disposable cache artefact.
    preset: str = "ultrafast"

    @property
    def height_label(self) -> str:
        """Return ``720p`` / ``540p`` / ``360p`` for the status UI."""
        return f"{self.height}p"

    def signature(self) -> str:
        """Return a stable short digest of the recipe."""
        payload = f"{PROXY_RECIPE_VERSION}:{self.height}:{self.crf}:{self.preset}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


@dataclass(slots=True)
class ProxyStatus:
    """Observable state of one proxy, for the cache-status UI."""

    source: str
    state: ProxyState = ProxyState.NONE
    path: str = ""
    progress: float = 0.0
    detail: str = ""
    updated_at: float = 0.0

    @property
    def ready(self) -> bool:
        """Whether a usable proxy exists."""
        return self.state is ProxyState.READY and bool(self.path)

    @property
    def building(self) -> bool:
        """Whether generation is in flight."""
        return self.state in (ProxyState.QUEUED, ProxyState.BUILDING)

    def label(self) -> str:
        """Return the short status string shown next to the media."""
        if self.state is ProxyState.READY:
            return "Proxy ready"
        if self.state is ProxyState.BUILDING:
            return f"Proxy building {self.progress * 100:.0f}%"
        if self.state is ProxyState.QUEUED:
            return "Proxy queued"
        if self.state is ProxyState.FAILED:
            return "Proxy failed"
        if self.state is ProxyState.UNAVAILABLE:
            return "Original"
        return "Original"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""
        return {
            "source": self.source,
            "state": self.state.value,
            "label": self.label(),
            "path": self.path,
            "progress": round(self.progress, 3),
            "detail": self.detail,
        }


# ----------------------------------------------------------------------
# FFmpeg discovery
# ----------------------------------------------------------------------


def _ffmpeg_executable() -> str | None:
    """Return an FFmpeg binary path, preferring the bundled build."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - optional at import time
        return None


def _probe_tools() -> tuple[str, str] | None:
    """Return ``(ffmpeg, ffprobe)`` when both are usable."""
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return None
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not ffprobe.is_file():
        sibling = Path(ffmpeg).parent / ("ffprobe" if os.name != "nt" else "ffprobe.exe")
        if sibling.is_file():
            ffprobe = sibling
        else:
            return None
    return str(ffmpeg), str(ffprobe)


#: Matches ``out_time_ms=`` (microseconds) in FFmpeg's ``-progress`` stream.
_PROGRESS_RE = re.compile(r"out_time_(?:ms|us)=(\d+)")


# ----------------------------------------------------------------------
# Manager
# ----------------------------------------------------------------------


class ProxyManager:
    """Generates, caches, and reports editing proxies.

    Parameters:
        cache_root: Directory for generated proxies. Defaults to
            ``userdata/cache/proxies`` under the application root.
        spec: Encoding recipe. Changing it invalidates every cached proxy.
    """

    def __init__(
        self,
        cache_root: Path | str | None = None,
        spec: ProxySpec | None = None,
    ) -> None:
        self._spec = spec or ProxySpec()
        self._cache_root = Path(cache_root) if cache_root else _default_cache_root()
        self._status: "OrderedDict[str, ProxyStatus]" = OrderedDict()
        self._durations: dict[str, float] = {}
        self._lock = threading.RLock()
        self._in_flight: set[str] = set()
        self._enabled = True
        self._max_status_entries = 512

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def spec(self) -> ProxySpec:
        """Active encoding recipe."""
        return self._spec

    def set_spec(self, spec: ProxySpec) -> None:
        """Change the recipe; every previously generated proxy is ignored."""
        with self._lock:
            self._spec = spec
            self._status.clear()

    @property
    def enabled(self) -> bool:
        """Whether proxy generation is allowed at all."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable proxy generation."""
        self._enabled = bool(enabled)

    @property
    def cache_root(self) -> Path:
        """Directory holding generated proxies."""
        return self._cache_root

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def _identity(self, source: Path) -> tuple[str, int, int] | None:
        """Return the cache identity for ``source``, or None if unreadable."""
        try:
            stat = source.stat()
        except OSError:
            return None
        return (
            os.path.normcase(str(source.resolve())),
            int(stat.st_size),
            int(stat.st_mtime_ns),
        )

    def proxy_path(self, source: str | Path) -> Path:
        """Return the deterministic proxy path for ``source``.

        The name is derived from the source identity *and* the recipe, so a
        changed source or a changed recipe maps to a different file and can
        never be served stale output.
        """
        path = Path(source)
        identity = self._identity(path)
        if identity is None:
            digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
        else:
            payload = "|".join(
                (identity[0], str(identity[1]), str(identity[2]), self._spec.signature())
            )
            digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

        return self._cache_root / f"{path.stem}_{digest}.mp4"

    def manifest_path(self, proxy_path: Path) -> Path:
        """Return the sidecar manifest path for ``proxy_path``."""
        return proxy_path.with_suffix(proxy_path.suffix + ".json")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, source: str | Path) -> Path | None:
        """Return an already-generated usable proxy, or ``None``.

        This is a pure filesystem/registration check: it never starts work,
        so it is safe to call from the evaluation hot path.
        """
        path = Path(source)
        if not path.is_file():
            return None

        proxy = self.proxy_path(path)
        manifest = self.manifest_path(proxy)
        if not (proxy.is_file() and manifest.is_file()):
            return None

        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt manifest means "no proxy"
            return None

        if data.get("recipe") != self._spec.signature():
            return None
        if data.get("verified") is not True:
            return None

        return proxy

    def status(self, source: str | Path) -> ProxyStatus:
        """Return the current proxy status for ``source``."""
        key = os.path.normcase(os.path.abspath(str(source)))
        with self._lock:
            existing = self._status.get(key)
            if existing is not None:
                return existing

        if self.lookup(source) is not None:
            result = ProxyStatus(
                source=str(source),
                state=ProxyState.READY,
                path=str(self.proxy_path(source)),
                progress=1.0,
            )
        else:
            result = ProxyStatus(source=str(source), state=ProxyState.NONE)

        self._remember(key, result)
        return result

    def all_status(self) -> list[ProxyStatus]:
        """Return every tracked status, for the cache-status panel."""
        with self._lock:
            return list(self._status.values())

    def _remember(self, key: str, status: ProxyStatus) -> None:
        status.updated_at = time.monotonic()
        with self._lock:
            self._status[key] = status
            self._status.move_to_end(key)
            while len(self._status) > self._max_status_entries:
                self._status.popitem(last=False)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def ensure(self, source: str | Path, *, priority: JobPriority = JobPriority.BACKGROUND):
        """Request proxy generation in the background.

        Returns immediately. Repeated calls for the same source are
        de-duplicated, so queueing a proxy is idempotent and cheap.

        Parameters:
            source: Media file to proxy.
            priority: Scheduler band. Defaults to BACKGROUND so proxy work
                yields to interactive decoding and stops entirely while
                playback is running.

        Returns:
            A ``concurrent.futures.Future`` for the proxy path, or ``None``
            when generation is disabled or impossible.
        """
        path = Path(source)
        if not self._enabled or not path.is_file():
            return None
        if self.lookup(path) is not None:
            return None

        tools = _probe_tools()
        if tools is None:
            self._remember(
                os.path.normcase(os.path.abspath(str(path))),
                ProxyStatus(
                    source=str(path),
                    state=ProxyState.UNAVAILABLE,
                    detail="FFmpeg/FFprobe not available",
                ),
            )
            return None

        key = os.path.normcase(os.path.abspath(str(path)))
        with self._lock:
            if key in self._in_flight:
                return None
            self._in_flight.add(key)

        self._remember(
            key,
            ProxyStatus(source=str(path), state=ProxyState.QUEUED, detail="queued"),
        )

        return get_scheduler().submit(
            self._generate,
            path,
            tools,
            priority=priority,
            name=f"proxy:{path.name}",
        )

    def _generate(self, source: Path, tools: tuple[str, str]) -> Path | None:
        """Encode the proxy, verify it, and publish its manifest."""
        key = os.path.normcase(os.path.abspath(str(source)))
        ffmpeg, ffprobe = tools
        proxy = self.proxy_path(source)
        proxy.parent.mkdir(parents=True, exist_ok=True)
        temporary = proxy.with_suffix(".part.mp4")

        self._remember(
            key,
            ProxyStatus(source=str(source), state=ProxyState.BUILDING, detail="encoding"),
        )

        try:
            ok = self._run_ffmpeg(ffmpeg, source, temporary, key)
            if not ok:
                raise RuntimeError("ffmpeg failed")

            verified, frame_count, fps = self._verify(ffprobe, source, temporary)
            if not verified:
                raise RuntimeError("proxy verification failed")

            temporary.replace(proxy)
            self.manifest_path(proxy).write_text(
                json.dumps(
                    {
                        "recipe": self._spec.signature(),
                        "source": str(source),
                        "verified": True,
                        "frame_count": frame_count,
                        "fps": fps,
                        "spec": {
                            "height": self._spec.height,
                            "crf": self._spec.crf,
                            "preset": self._spec.preset,
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - proxy failure is never fatal
            _LOG.debug("Proxy generation failed for %s: %s", source, exc)
            for leftover in (temporary, proxy):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass
            self._remember(
                key,
                ProxyStatus(
                    source=str(source),
                    state=ProxyState.FAILED,
                    detail=str(exc)[:200],
                ),
            )
            return None
        finally:
            with self._lock:
                self._in_flight.discard(key)

        self._remember(
            key,
            ProxyStatus(
                source=str(source),
                state=ProxyState.READY,
                path=str(proxy),
                progress=1.0,
                detail=f"{self._spec.height_label}, all-intra",
            ),
        )
        _LOG.info("Generated %s proxy for %s", self._spec.height_label, source.name)
        return proxy

    def _run_ffmpeg(self, ffmpeg: str, source: Path, destination: Path, key: str) -> bool:
        """Encode an all-intra proxy, reporting progress to the status map."""
        height = max(120, int(self._spec.height))

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-y",
            "-i", str(source),
            # Scale to the target height, keeping the aspect ratio and an
            # even width (yuv420p requires it).
            "-vf", f"scale=-2:{height}",
            "-c:v", "libx264",
            "-preset", self._spec.preset,
            "-crf", str(int(self._spec.crf)),
            # The point of the whole exercise: every frame is a keyframe, so
            # a seek costs one decode step no matter where it lands.
            "-g", "1",
            "-keyint_min", "1",
            "-sc_threshold", "0",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
            # Frames map 1:1 to the source; audio keeps its original path.
            "-an",
            "-progress", "pipe:1",
            destination.as_posix(),
        ]

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=_no_window_flag(),
            )
        except OSError as exc:
            _LOG.debug("Could not start ffmpeg: %s", exc)
            return False

        assert process.stdout is not None
        for line in process.stdout:
            match = _PROGRESS_RE.search(line)
            if match is None:
                continue
            self._report_progress(key, source, float(match.group(1)) / 1_000_000.0)

        return process.wait() == 0

    def _report_progress(self, key: str, source: Path, seconds: float) -> None:
        """Update the status entry with a coarse progress estimate."""
        with self._lock:
            current = self._status.get(key)
            if current is None:
                return
            total = self._durations.get(key, 0.0)
            progress = 0.0 if total <= 0.0 else max(0.0, min(0.99, seconds / total))
            self._status[key] = replace(
                current,
                state=ProxyState.BUILDING,
                progress=progress,
            )

    def _verify(
        self,
        ffprobe: str,
        source: Path,
        candidate: Path,
    ) -> tuple[bool, int, float]:
        """Check that the proxy maps 1:1 onto the source.

        A proxy that has lost or gained frames would silently shift the
        whole timeline, which is far worse than having no proxy at all — so
        a mismatch deletes the candidate instead of using it.
        """
        source_info = self._ffprobe_stream(ffprobe, source)
        proxy_info = self._ffprobe_stream(ffprobe, candidate)
        if source_info is None or proxy_info is None:
            return False, 0, 0.0

        src_frames, src_fps = source_info
        out_frames, out_fps = proxy_info

        if src_frames <= 0 or out_frames <= 0:
            return False, out_frames, out_fps

        # Allow a single frame of rounding slack; reject anything larger.
        if abs(out_frames - src_frames) > 1:
            _LOG.debug(
                "Proxy frame count mismatch for %s: %s vs %s",
                source.name,
                out_frames,
                src_frames,
            )
            return False, out_frames, out_fps

        if src_fps > 0.0 and out_fps > 0.0 and abs(out_fps - src_fps) > 0.01:
            _LOG.debug("Proxy fps mismatch for %s: %s vs %s", source.name, out_fps, src_fps)
            return False, out_frames, out_fps

        if src_fps > 0.0:
            with self._lock:
                self._durations[os.path.normcase(os.path.abspath(str(source)))] = (
                    src_frames / src_fps
                )
        return True, out_frames, out_fps

    @staticmethod
    def _ffprobe_stream(ffprobe: str, path: Path) -> tuple[int, float] | None:
        """Return ``(frame_count, fps)`` for the first video stream."""
        command = [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames,avg_frame_rate,width,height",
            "-of", "json",
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                creationflags=_no_window_flag(),
            )
        except Exception:  # noqa: BLE001
            return None

        if completed.returncode != 0:
            return None

        try:
            payload = json.loads(completed.stdout or "{}")
            stream = (payload.get("streams") or [{}])[0]
        except Exception:  # noqa: BLE001
            return None

        frames = int(stream.get("nb_frames") or 0)
        rate = str(stream.get("avg_frame_rate") or "0/0")
        fps = 0.0
        if "/" in rate:
            numerator, _, denominator = rate.partition("/")
            try:
                denominator_value = float(denominator)
                if denominator_value > 0:
                    fps = float(numerator) / denominator_value
            except ValueError:
                fps = 0.0
        else:
            try:
                fps = float(rate)
            except ValueError:
                fps = 0.0

        return frames, fps

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self, *, delete_files: bool = True) -> int:
        """Remove cached proxies; returns how many files were deleted."""
        removed = 0
        if delete_files and self._cache_root.is_dir():
            for entry in self._cache_root.glob("*.mp4*"):
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    continue
        with self._lock:
            self._status.clear()
            self._in_flight.clear()
        return removed

    def regenerate(self, source: str | Path):
        """Delete any existing proxy for ``source`` and queue a fresh one."""
        path = Path(source)
        proxy = self.proxy_path(path)
        for target in (proxy, self.manifest_path(proxy)):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        self._remember(
            os.path.normcase(os.path.abspath(str(path))),
            ProxyStatus(source=str(path), state=ProxyState.NONE),
        )
        return self.ensure(path)

    def cache_size_bytes(self) -> int:
        """Return the total size of generated proxies on disk."""
        if not self._cache_root.is_dir():
            return 0
        total = 0
        for entry in self._cache_root.glob("*.mp4*"):
            try:
                total += entry.stat().st_size
            except OSError:
                continue
        return total

    def stats(self) -> dict[str, int]:
        """Return counters for the preferences/diagnostics panel."""
        counts: dict[str, int] = {}
        with self._lock:
            for status in self._status.values():
                counts[status.state.value] = counts.get(status.state.value, 0) + 1
        counts["cache_bytes"] = self.cache_size_bytes()
        counts["in_flight"] = len(self._in_flight)
        return counts


# ----------------------------------------------------------------------
# Process-wide manager
# ----------------------------------------------------------------------

_MANAGER: ProxyManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_proxy_manager() -> ProxyManager:
    """Return the process-wide proxy manager, creating it on first use."""
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = ProxyManager()
    return _MANAGER


def _default_cache_root() -> Path:
    """Return ``userdata/cache/proxies`` under the application root."""
    try:
        from utils.paths import app_data_path

        return app_data_path("cache", "proxies")
    except Exception:  # noqa: BLE001 - never fail on a path helper
        return Path.cwd() / "userdata" / "cache" / "proxies"


def _no_window_flag() -> int:
    """Return the subprocess flag that suppresses a console window on Windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
