"""Repeatable tracking metrics independent of the UI and media decoder."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import time

import numpy as np

from core.tracking.planar_tracker import PlanarTrackingResult


@dataclass(frozen=True)
class TrackingBenchmarkMetrics:
    frames: int
    valid_frames: int
    predicted_frames: int
    recovered_frames: int
    survival_rate: float
    recovery_rate: float
    mean_corner_error: float | None
    max_corner_error: float | None
    drift_after_100: float | None
    frames_per_second: float

    def to_dict(self) -> dict:
        return asdict(self)


def benchmark_planar(results: dict[int, PlanarTrackingResult], ground_truth: dict[int, np.ndarray] | None = None,
                     elapsed_seconds: float | None = None,
                     image_size: tuple[int, int] | None = None) -> TrackingBenchmarkMetrics:
    frames = sorted(results)
    valid = [result for result in results.values() if result.valid]
    errors: list[float] = []
    if ground_truth:
        for frame, result in results.items():
            if result.polygon is None or frame not in ground_truth:
                continue
            predicted = np.asarray(result.polygon, np.float64)
            truth = np.asarray(ground_truth[frame], np.float64)
            if image_size is not None:
                truth = truth / np.asarray(image_size, dtype=np.float64)
            errors.append(float(np.mean(np.linalg.norm(predicted - truth, axis=1))))
    return TrackingBenchmarkMetrics(
        frames=len(frames), valid_frames=len(valid),
        predicted_frames=sum(result.predicted for result in results.values()),
        recovered_frames=sum(result.recovered for result in results.values()),
        survival_rate=len(valid) / max(1, len(frames)),
        recovery_rate=sum(result.recovered for result in results.values()) / max(1, len(frames)),
        mean_corner_error=float(np.mean(errors)) if errors else None,
        max_corner_error=float(np.max(errors)) if errors else None,
        drift_after_100=errors[min(99, len(errors) - 1)] if errors else None,
        frames_per_second=len(frames) / elapsed_seconds if elapsed_seconds and elapsed_seconds > 0 else 0.0,
    )
