"""Bounded ordered map for independent frames; no Qt dependency.

Only a fixed window of futures exists, including completed out-of-order
results. A slow first frame therefore cannot grow the reorder buffer.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Iterator, TypeVar

T = TypeVar('T')
R = TypeVar('R')


def ordered_frames(render: Callable[[T], R], frames: Iterable[T], *,
                   workers: int, capacity: int,
                   cancelled: Callable[[], bool]) -> Iterator[R]:
    iterator = iter(frames)
    pending = deque()
    pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix='AphelionRender')
    try:
        for _ in range(max(1, capacity)):
            if cancelled():
                return
            try:
                frame = next(iterator)
            except StopIteration:
                break
            pending.append(pool.submit(render, frame))
        while pending and not cancelled():
            yield pending.popleft().result()
            if cancelled():
                return
            try:
                frame = next(iterator)
            except StopIteration:
                continue
            pending.append(pool.submit(render, frame))
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
