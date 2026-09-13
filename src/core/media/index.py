"""Cached keyframe index for compressed media.

Long-GOP codecs make random access expensive in a way that is invisible
from the outside: seeking to frame 300 of a file with 250-frame GOPs means
finding the keyframe at 250 and decoding fifty frames to reach it. The
decoder previously discovered this the hard way — by seeking, reading back
the *actual* landing position, and walking forward — on every seek.

An index removes the guessing. Once keyframe positions are known, a seek
can:

* jump straight to the correct keyframe (no probing loop);
* know in advance how many frames must be decoded after the seek, which is
  exactly the information the deadline scheduler needs to decide whether a
  frame is even worth starting (see ``core.playback.deadline``);
* answer "how expensive is this neighbourhood" for cache decisions.

The index is keyed by source identity (path + size + mtime) and persisted,
so it is built once per file rather than once per session.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from core.perf.scheduler import JobPriority, get_scheduler
from utils.logging_setup import get_logger

_LOG = get_logger("core.media.index")

__all__ = ["KeyframeIndex", "KeyframeIndexCache", "get_keyframe_index_cache"]


@dataclass(frozen=True, slots=True)
class KeyframeIndex:
    """Keyframe positions for one media file."""

    path: str
    size: int
    mtime_ns: int
    fps: float
    frame_count: int
    #: Sorted source frame indices that begin a GOP.
    keyframes: tuple[int, ...]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def complete(self) -> bool:
        """Whether the index has enough information to be useful."""
        return len(self.keyframes) > 0

    def nearest_before(self, frame: int) -> int:
        """Return the last keyframe at or before ``frame``."""
        if not self.keyframes:
            return 0
        target = int(frame)
        low, high = 0, len(self.keyframes) - 1
        best = self.keyframes[0]
        while low <= high:
            middle = (low + high) // 2
            candidate = self.keyframes[middle]
            if candidate <= target:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        return best

    def nearest_after(self, frame: int) -> int:
        """Return the first keyframe at or after ``frame``."""
        if not self.keyframes:
            return 0
        target = int(frame)
        low, high = 0, len(self.keyframes) - 1
        best = self.keyframes[-1]
        while low <= high:
            middle = (low + high) // 2
            candidate = self.keyframes[middle]
            if candidate >= target:
                best = candidate
                high = middle - 1
            else:
                low = middle + 1
        return best

    def decode_distance(self, frame: int) -> int:
        """Frames that must be decoded after the keyframe to reach ``frame``.

        This is the number that predicts seek cost, and therefore the number
        the deadline scheduler uses to decide whether a scrub request can be
        answered before it stops being relevant.
        """
        return max(0, int(frame) - self.nearest_before(frame))

    def gop_length(self, frame: int) -> int:
        """Return the length of the GOP containing ``frame``."""
        start = self.nearest_before(frame)
        following = self.nearest_after(start + 1)
        if following <= start:
            return max(1, self.frame_count - start)
        return max(1, following - start)

    @property
    def average_gop(self) -> float:
        """Mean GOP length across the file."""
        if len(self.keyframes) < 2:
            return float(max(1, self.frame_count))
        span = self.keyframes[-1] - self.keyframes[0]
        return span / max(1, len(self.keyframes) - 1)

    @property
    def worst_gop(self) -> int:
        """Longest GOP in the file."""
        if len(self.keyframes) < 2:
            return self.frame_count
        gaps = [
            self.keyframes[index + 1] - self.keyframes[index]
            for index in range(len(self.keyframes) - 1)
        ]
        gaps.append(max(1, self.frame_count - self.keyframes[-1]))
        return max(gaps)

    @property
    def is_all_intra(self) -> bool:
        """Whether every frame is a keyframe (a proxy, typically)."""
        return len(self.keyframes) >= max(2, self.frame_count - 1)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""
        return {
            "path": self.path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "keyframes": list(self.keyframes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "KeyframeIndex | None":
        """Rebuild an index from persisted JSON, or ``None`` when invalid."""
        try:
            return cls(
                path=str(data["path"]),
                size=int(data["size"]),  # type: ignore[arg-type]
                mtime_ns=int(data["mtime_ns"]),  # type: ignore[arg-type]
                fps=float(data["fps"]),  # type: ignore[arg-type]
                frame_count=int(data["frame_count"]),  # type: ignore[arg-type]
                keyframes=tuple(int(value) for value in data["keyframes"]),  # type: ignore[arg-type]
            )
        except Exception:  # noqa: BLE001 - a corrupt cache entry is just a miss
            return None

    def summary(self) -> str:
        """Return a one-line description for diagnostics."""
        if not self.complete:
            return "no keyframes"
        if self.is_all_intra:
            return f"{len(self.keyframes)} keyframes (all-intra)"
        return (
            f"{len(self.keyframes)} keyframes, avg GOP {self.average_gop:.0f}, "
            f"worst {self.worst_gop}"
        )


class KeyframeIndexCache:
    """Builds, persists, and serves :class:`KeyframeIndex` objects.

    Parameters:
        cache_root: Directory for persisted index JSON. Defaults to
            ``userdata/cache/index``.
    """

    #: Refuse to hold more than this many indexes in memory.
    MEMORY_LIMIT: int = 64

    def __init__(self, cache_root: Path | str | None = None) -> None:
        self._cache_root = Path(cache_root) if cache_root else _default_cache_root()
        self._memory: "OrderedDict[tuple[str, int, int, float], KeyframeIndex]" = (
            OrderedDict()
        )
        self._lock = threading.RLock()
        self._in_flight: set[tuple[str, int, int, float]] = set()

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @staticmethod
    def _key(path: Path, fps: float) -> tuple[str, int, int, float] | None:
        """Return the cache key for ``path``, or ``None`` when unreadable."""
        try:
            stat = path.stat()
        except OSError:
            return None
        return (
            os.path.normcase(str(path.resolve())),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            round(float(fps), 6),
        )

    def _disk_path(self, key: tuple[str, int, int, float]) -> Path:
        """Return the persisted index path for a cache key."""
        import hashlib

        digest = hashlib.sha1(
            "|".join((key[0], str(key[1]), str(key[2]), str(key[3]))).encode("utf-8")
        ).hexdigest()[:20]
        return self._cache_root / f"{digest}.json"

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def cached(self, source: str | Path, fps: float) -> KeyframeIndex | None:
        """Return an already-known index without any I/O beyond a lookup.

        This is the hot-path entry point and never builds anything.
        """
        key = self._key(Path(source), fps)
        if key is None:
            return None

        with self._lock:
            hit = self._memory.get(key)
            if hit is not None:
                self._memory.move_to_end(key)
                return hit

        disk = self._disk_path(key)
        if not disk.is_file():
            return None

        try:
            payload = json.loads(disk.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

        index = KeyframeIndex.from_dict(payload)
        if index is None:
            return None

        with self._lock:
            self._store_locked(key, index)
        return index

    def _store_locked(
        self, key: tuple[str, int, int, float], index: KeyframeIndex
    ) -> None:
        self._memory[key] = index
        self._memory.move_to_end(key)
        while len(self._memory) > self.MEMORY_LIMIT:
            self._memory.popitem(last=False)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def ensure(
        self,
        source: str | Path,
        fps: float,
        frame_count: int,
        *,
        priority: JobPriority = JobPriority.BACKGROUND,
    ):
        """Queue an index build in the background.

        Returns immediately with a ``Future``, or ``None`` when an index is
        already available or the tools are missing. Repeated calls are
        de-duplicated.
        """
        path = Path(source)
        key = self._key(path, fps)
        if key is None or self.cached(path, fps) is not None:
            return None

        with self._lock:
            if key in self._in_flight:
                return None
            self._in_flight.add(key)

        return get_scheduler().submit(
            self._build_and_store,
            path,
            float(fps),
            int(frame_count),
            key,
            priority=priority,
            name=f"index:{path.name}",
        )

    def _build_and_store(
        self,
        path: Path,
        fps: float,
        frame_count: int,
        key: tuple[str, int, int, float],
    ) -> KeyframeIndex | None:
        """Build an index, persist it, and release the in-flight marker."""
        try:
            index = self.build(path, fps, frame_count)
            if index is None:
                return None
            disk = self._disk_path(key)
            disk.parent.mkdir(parents=True, exist_ok=True)
            disk.write_text(
                json.dumps(index.to_dict()),
                encoding="utf-8",
            )
            with self._lock:
                self._store_locked(key, index)
            _LOG.debug("Indexed %s: %s", path.name, index.summary())
            return index
        except Exception as exc:  # noqa: BLE001 - indexing is best-effort
            _LOG.debug("Keyframe index failed for %s: %s", path, exc)
            return None
        finally:
            with self._lock:
                self._in_flight.discard(key)

    def build(
        self,
        source: str | Path,
        fps: float,
        frame_count: int,
    ) -> KeyframeIndex | None:
        """Synchronously scan keyframe positions; ``None`` when unavailable.

        Uses ``ffprobe -skip_frame nokey``, which lists only keyframes and
        therefore does not decode the file. PTS values are converted to
        frame indices through the supplied frame rate; variable-frame-rate
        sources are approximated, and the resulting index is validated for
        monotonicity before being trusted.
        """
        path = Path(source)
        tools = _ffprobe_executable()
        if tools is None or not path.is_file():
            return None

        command = [
            tools,
            "-v", "error",
            "-select_streams", "v:0",
            "-skip_frame", "nokey",
            "-show_entries", "frame=best_effort_timestamp_time,pts_time",
            "-of", "json",
            str(path),
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:  # noqa: BLE001
            return None

        if completed.returncode != 0:
            return None

        try:
            payload = json.loads(completed.stdout or "{}")
        except Exception:  # noqa: BLE001
            return None

        rate = max(0.001, float(fps))
        frames: list[int] = []

        for entry in payload.get("frames", []):
            raw = entry.get("best_effort_timestamp_time")
            if raw in (None, "N/A"):
                raw = entry.get("pts_time")
            if raw in (None, "N/A"):
                continue
            try:
                seconds = float(raw)
            except (TypeError, ValueError):
                continue
            frame_index = int(round(seconds * rate))
            if frame_index < 0:
                continue
            if frames and frame_index <= frames[-1]:
                # Non-monotonic (VFR or a duplicated PTS): refuse the whole
                # index rather than hand the scheduler a misleading one.
                continue
            frames.append(frame_index)

        if not frames:
            return None

        # A single keyframe at 0 usually means the scan failed rather than
        # that the file is one long GOP; treat it as "no index".
        limit = max(1, int(frame_count))
        if len(frames) == 1 and limit > 2:
            return None

        key = self._key(path, fps)
        if key is None:
            return None

        return KeyframeIndex(
            path=str(path),
            size=key[1],
            mtime_ns=key[2],
            fps=float(fps),
            frame_count=limit,
            keyframes=tuple(frames),
        )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self, *, delete_files: bool = True) -> int:
        """Drop in-memory indexes and optionally delete persisted ones."""
        removed = 0
        if delete_files and self._cache_root.is_dir():
            for entry in self._cache_root.glob("*.json"):
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    continue
        with self._lock:
            self._memory.clear()
            self._in_flight.clear()
        return removed

    def stats(self) -> dict[str, int]:
        """Return counters for diagnostics."""
        with self._lock:
            return {
                "memory_entries": len(self._memory),
                "in_flight": len(self._in_flight),
            }


_MANAGER: KeyframeIndexCache | None = None
_MANAGER_LOCK = threading.Lock()


def get_keyframe_index_cache() -> KeyframeIndexCache:
    """Return the process-wide keyframe index cache."""
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = KeyframeIndexCache()
    return _MANAGER


def _ffprobe_executable() -> str | None:
    """Locate an FFprobe binary beside the bundled FFmpeg."""
    try:
        import imageio_ffmpeg
    except Exception:  # noqa: BLE001
        return None

    try:
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return None

    for name in ("ffprobe.exe", "ffprobe"):
        candidate = ffmpeg.with_name(name)
        if candidate.is_file():
            return str(candidate)
    return None


def _default_cache_root() -> Path:
    """Return ``userdata/cache/index`` under the application root."""
    try:
        from utils.paths import app_data_path

        return app_data_path("cache", "index")
    except Exception:  # noqa: BLE001
        return Path.cwd() / "userdata" / "cache" / "index"
