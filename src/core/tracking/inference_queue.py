"""Cancellable background inference queue used by optional ML backends."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any, Callable


@dataclass
class InferenceJob:
    job_id: str
    future: Future[Any]
    cancel_event: Event = field(default_factory=Event)

    def cancel(self) -> bool:
        self.cancel_event.set()
        return self.future.cancel()


class InferenceQueue:
    """Bounded-by-call asynchronous execution without UI-thread inference."""

    def __init__(self, workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="aphelion-track")
        self._lock = Lock()
        self._jobs: dict[str, InferenceJob] = {}

    def submit(self, job_id: str, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> InferenceJob:
        cancel_event = Event()

        def run() -> Any:
            if cancel_event.is_set():
                return None
            return operation(*args, cancel_event=cancel_event, **kwargs)

        future = self._executor.submit(run)
        job = InferenceJob(job_id, future, cancel_event)
        with self._lock:
            old = self._jobs.get(job_id)
            if old is not None:
                old.cancel()
            self._jobs[job_id] = job
        return job

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            job.cancel()

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
