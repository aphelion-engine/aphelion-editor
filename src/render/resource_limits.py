"""Export admission budgets reserve memory for the desktop and shared-memory GPU."""
import os
import threading
from contextlib import contextmanager

MIB = 1024 * 1024
_CV_LOCK = threading.Lock()
_CV_USERS = 0
_CV_PREVIOUS = 0
_OS_MEMORY_LIMIT_ACTIVE = False


def set_os_memory_limit_active(active: bool) -> None:
    """Called only by the child after its parent installs the Windows job."""
    global _OS_MEMORY_LIMIT_ACTIVE
    _OS_MEMORY_LIMIT_ACTIVE = bool(active)


@contextmanager
def export_thread_budget():
    """Coordinate OpenCV's process-wide pool across overlapping export jobs."""
    import cv2
    global _CV_USERS, _CV_PREVIOUS
    with _CV_LOCK:
        if not _CV_USERS:
            _CV_PREVIOUS = cv2.getNumThreads()
            cv2.setNumThreads(min(max(1,_CV_PREVIOUS),codec_threads()))
        _CV_USERS += 1
    try:
        yield
    finally:
        with _CV_LOCK:
            _CV_USERS -= 1
            if not _CV_USERS:
                cv2.setNumThreads(_CV_PREVIOUS)


def available_export_bytes(requested: int) -> int:
    from core.perf.capabilities import _physical_memory_mb
    total, available = _physical_memory_mb()
    reserve = max(512, min(2048, total // 8))
    usable = max(0, available - reserve) * MIB
    return min(max(0, int(requested)), usable // 2)


def codec_threads() -> int:
    """Leave CPU capacity for UI, decode and the display driver."""
    return max(1, min(4, (os.cpu_count() or 2) // 4))


def queue_capacity(frame_bytes: int, requested_frames: int, budget: int) -> int:
    permitted = available_export_bytes(budget)
    if permitted < frame_bytes:
        raise MemoryError('Not enough free memory for export while reserving memory for Windows and the GPU')
    return max(1, min(int(requested_frames), 4, permitted // frame_bytes))


def require_working_memory(estimated_bytes: int) -> None:
    """Check before a heavy node, not after its allocations have paged Windows."""
    if _OS_MEMORY_LIMIT_ACTIVE:
        # The OS already rejects allocations beyond the entire process-tree
        # ceiling. Reserving eight hypothetical intermediates here rejected
        # small native effects despite sufficient room inside that ceiling.
        # Retain a host-pressure escape hatch for other applications growing.
        from core.perf.capabilities import _physical_memory_mb
        _, available = _physical_memory_mb()
        if available < 256:
            raise MemoryError('Export stopped because system memory became critically low')
        return
    if available_export_bytes(estimated_bytes) < estimated_bytes:
        raise MemoryError('Export stopped before exhausting system memory; insufficient headroom for the next effect')
