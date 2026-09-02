"""LRU frame cache with a configurable memory budget."""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from typing import Any

import numpy as np


def _estimate_bytes(value: Any) -> int:
    """Estimate the memory consumed by a cached value."""
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    return sys.getsizeof(value)


class FrameCache:
    """LRU cache keyed by ``(node_id, frame_num, output_slot)``.

    The cache remains thread-safe for normal project/UI access.

    ``get_fast`` and ``set_fast`` are intentionally available for the
    Project evaluator, which already owns the project's global evaluation
    lock. Avoid using the fast methods from arbitrary threads.
    """

    __slots__ = (
        "_max_bytes",
        "_current_bytes",
        "_entries",
        "_sizes",
        "_lock",
    )

    def __init__(self, max_mb: int = 512) -> None:
        self._max_bytes = max(1, int(max_mb)) * 1024 * 1024
        self._current_bytes = 0

        self._entries: OrderedDict[tuple[str, int, str], Any] = OrderedDict()
        self._sizes: dict[tuple[str, int, str], int] = {}

        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Normal thread-safe API
    # ------------------------------------------------------------------

    def get(self, key: tuple[str, int, str]) -> Any | None:
        with self._lock:
            return self._get_unlocked(key)

    def set(self, key: tuple[str, int, str], value: Any) -> None:
        with self._lock:
            self._set_unlocked(key, value)

    # ------------------------------------------------------------------
    # Fast API
    #
    # These deliberately do not acquire the cache lock.
    #
    # Project.evaluate_node() already holds Project._eval_lock for the
    # complete recursive evaluation tree, so acquiring another RLock for
    # every node/cache access is unnecessary overhead.
    # ------------------------------------------------------------------

    def get_fast(self, key: tuple[str, int, str]) -> Any | None:
        return self._get_unlocked(key)

    def set_fast(self, key: tuple[str, int, str], value: Any) -> None:
        self._set_unlocked(key, value)

    # ------------------------------------------------------------------
    # Internal unlocked implementation
    # ------------------------------------------------------------------

    def _get_unlocked(self, key: tuple[str, int, str]) -> Any | None:
        entries = self._entries

        try:
            value = entries[key]
        except KeyError:
            return None

        entries.move_to_end(key)
        return value

    def _set_unlocked(self, key: tuple[str, int, str], value: Any) -> None:
        size = _estimate_bytes(value)

        entries = self._entries
        sizes = self._sizes

        old_size = sizes.pop(key, None)

        if old_size is not None:
            self._current_bytes -= old_size
            del entries[key]

        # A single frame larger than the entire cache should not cause
        # unrelated cached frames to survive indefinitely.
        if size > self._max_bytes:
            entries.clear()
            sizes.clear()
            self._current_bytes = 0
            return

        current_bytes = self._current_bytes
        max_bytes = self._max_bytes

        while current_bytes + size > max_bytes and entries:
            oldest_key, _ = entries.popitem(last=False)
            current_bytes -= sizes.pop(oldest_key)

        entries[key] = value
        sizes[key] = size

        self._current_bytes = current_bytes + size

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def invalidate_node(self, node_id: str) -> None:
        """Remove all cache entries for a given node id.

        Fixed to avoid mutating the OrderedDict while iterating.
        """
        with self._lock:
            entries = self._entries
            sizes = self._sizes

            if not entries:
                return

            # Iterate over a snapshot of keys to avoid mutation-during-iteration.
            remove = [
                key
                for key in list(entries.keys())
                if key[0] == node_id
            ]

            for key in remove:
                size = sizes.pop(key, 0)
                if key in entries:
                    del entries[key]
                self._current_bytes -= size
                if self._current_bytes < 0:
                    self._current_bytes = 0

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sizes.clear()
            self._current_bytes = 0

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------

    def set_max_mb(self, max_mb: int) -> None:
        """Resize the memory budget."""
        with self._lock:
            self._max_bytes = max(1, int(max_mb)) * 1024 * 1024

            entries = self._entries
            sizes = self._sizes

            while self._current_bytes > self._max_bytes and entries:
                oldest_key, _ = entries.popitem(last=False)
                self._current_bytes -= sizes.pop(oldest_key, 0)
                if self._current_bytes < 0:
                    self._current_bytes = 0

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @property
    def size_mb(self) -> float:
        return self._current_bytes / (1024 * 1024)

    @property
    def max_mb(self) -> float:
        return self._max_bytes / (1024 * 1024)

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)
