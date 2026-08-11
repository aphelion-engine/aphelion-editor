"""LRU frame cache with a configurable memory budget."""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from typing import Any

import numpy as np


def _estimate_bytes(value: Any) -> int:
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    return sys.getsizeof(value)


class FrameCache:
    """Thread-safe LRU cache keyed by (node_id, frame_num, output_slot)."""

    def __init__(self, max_mb: int = 512) -> None:
        self._max_bytes = max_mb * 1024 * 1024
        self._current_bytes = 0
        self._entries: OrderedDict[tuple[str, int, str], Any] = OrderedDict()
        self._sizes: dict[tuple[str, int, str], int] = {}
        self._lock = threading.RLock()

    def get(self, key: tuple[str, int, str]) -> Any | None:
        with self._lock:
            if key not in self._entries:
                return None
            self._entries.move_to_end(key)
            return self._entries[key]

    def set(self, key: tuple[str, int, str], value: Any) -> None:
        size = _estimate_bytes(value)
        with self._lock:
            if key in self._entries:
                self._current_bytes -= self._sizes[key]
                del self._entries[key]
                del self._sizes[key]

            while self._current_bytes + size > self._max_bytes and self._entries:
                oldest_key, _ = self._entries.popitem(last=False)
                self._current_bytes -= self._sizes.pop(oldest_key)

            self._entries[key] = value
            self._sizes[key] = size
            self._current_bytes += size

    def invalidate_node(self, node_id: str) -> None:
        with self._lock:
            keys_to_remove = [k for k in self._entries if k[0] == node_id]
            for key in keys_to_remove:
                self._current_bytes -= self._sizes.pop(key)
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sizes.clear()
            self._current_bytes = 0

    @property
    def size_mb(self) -> float:
        return self._current_bytes / (1024 * 1024)
