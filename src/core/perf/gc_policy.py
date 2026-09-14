"""Garbage-collection coordination for playback stability.

CPython's generational collector can trigger a full collection at an
arbitrary bytecode boundary. During playback that surfaces as an occasional
multi-millisecond spike that has *nothing* to do with media work — which is
exactly the kind of stutter that frame timings alone cannot explain.

The standard mitigation is :func:`gc.freeze`: objects that already exist are
moved into a permanent generation that is never scanned again, so the
collector has far less to walk. Because freezing is process-wide and stays
in effect until :func:`gc.unfreeze`, it is applied only for the duration of
a playback session and always reversed afterwards, followed by a full
collection so anything that became garbage during playback is actually
released rather than pinned in the permanent generation.

This deliberately does **not** disable the collector globally. Everything
allocated during playback is still collected normally; only the pre-existing
long-lived object graph is taken out of the scan set.
"""

from __future__ import annotations

import gc
import threading

__all__ = ["GCPolicy", "get_gc_policy"]


class GCPolicy:
    """Applies and reverses playback-scoped GC tuning.

    Every method is safe to call redundantly and on platforms where the
    underlying ``gc`` entry points are unavailable: the policy degrades to
    doing nothing rather than raising.
    """

    __slots__ = ("_lock", "_engaged", "_was_enabled", "_gen0", "_collections")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engaged = False
        self._was_enabled = True
        self._gen0 = 0
        self._collections = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def engaged(self) -> bool:
        """Whether playback-scoped tuning is currently applied."""
        return self._engaged

    def begin_playback(self) -> bool:
        """Reduce collection pressure for the duration of playback.

        Returns:
            ``True`` when tuning was applied, ``False`` when it was already
            applied or is unavailable on this interpreter.
        """
        with self._lock:
            if self._engaged:
                return False
            if not gc.isenabled():
                # Someone else disabled the collector; do not fight them or
                # claim responsibility for re-enabling it.
                return False

            try:
                self._was_enabled = True
                thresholds = gc.get_threshold()
                self._gen0 = int(thresholds[0])
                self._collections = int(gc.get_count()[0])
                gc.freeze()
            except Exception:  # noqa: BLE001 - advisory only, never fatal
                return False

            self._engaged = True
            return True

    def end_playback(self) -> None:
        """Reverse playback-scoped tuning and release what became garbage."""
        with self._lock:
            if not self._engaged:
                return
            self._engaged = False
            try:
                gc.unfreeze()
            except Exception:  # noqa: BLE001
                pass

        # Collect outside the lock: this can take a few milliseconds and
        # must not block a concurrent begin_playback().
        try:
            gc.collect()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int | bool]:
        """Return counters for the overlay and traces."""
        try:
            counts = gc.get_count()
            gen0_count = int(counts[0])
        except Exception:  # noqa: BLE001
            gen0_count = 0
        return {
            "engaged": self._engaged,
            "enabled": bool(gc.isenabled()),
            "gen0_threshold": self._gen0,
            "gen0_count": gen0_count,
            "count_at_start": self._collections,
        }


_POLICY: GCPolicy | None = None
_POLICY_LOCK = threading.Lock()


def get_gc_policy() -> GCPolicy:
    """Return the process-wide GC policy."""
    global _POLICY
    if _POLICY is None:
        with _POLICY_LOCK:
            if _POLICY is None:
                _POLICY = GCPolicy()
    return _POLICY
