"""Background export of evaluated viewer frames to video or image sequences.

Optimization strategy:

- The producer runs the project in **export evaluation mode**, which
  replaces the interactive cross-frame frame cache with a per-frame
  scratch cache. A linear export never re-reads an earlier frame, so the
  interactive LRU only contributed bookkeeping plus hundreds of
  megabytes of live float32 intermediates. See ``Project.set_export_mode``.
- Encoding is pipelined on a bounded pool so the CPU encodes frame *N*
  while frame *N+1* is evaluating. Image sequences colour-convert on the
  producer thread, halving the number of full frame buffers kept alive by
  the in-flight queue.
- The MP4 writer has its own dedicated encoder thread and is fed in a
  single pass, so no frame is ever evaluated twice.
"""

from __future__ import annotations

import os
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from core.audio import AudioData, FrameWithAudio
from effects.frame_ops import to_display_u8
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from render.video_writer import ExportQuality, Mp4VideoWriter

if TYPE_CHECKING:
    from core.project import Project


class ExportFormat(Enum):
    """Supported export container formats."""

    MP4 = auto()
    PNG_SEQUENCE = auto()


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """Parameters for a single export job."""

    viewer_id: str
    start_frame: int
    end_frame: int
    output_path: Path
    format: ExportFormat
    fps: int
    full_resolution: bool = False
    export_audio_enabled: bool = True
    export_sample_rate: int = 48000
    export_channels: int = 2
    export_quality: ExportQuality = ExportQuality.FAST
    #: Parallel encoders for image-sequence export. ``0`` selects a
    #: sensible value from the host CPU count.
    encode_workers: int = 0
    #: PNG zlib compression level (0-9). Lower is dramatically faster and
    #: only costs disk space, which is why it defaults below OpenCV's own.
    png_compression: int = 1


_PROGRESS_UPDATE_INTERVAL: int = 8

# Upper bound on encoder threads. PNG compression scales well across
# cores, but past this point memory bandwidth and the single evaluation
# producer become the limit.
_MAX_ENCODE_WORKERS: int = 16


def _default_encode_workers() -> int:
    """Return a sensible default encoder thread count."""
    cpu_count: int = os.cpu_count() or 2
    return max(2, min(_MAX_ENCODE_WORKERS, cpu_count))


def _encode_png_bgr(
    frame_bgr: np.ndarray,
    filename: Path,
    compression: int,
) -> bool:
    """Encode one BGR frame to a PNG on disk.

    ``frame_bgr`` is already colour-converted by the producer so that each
    queued task retains exactly one frame buffer.

    Returns:
        ``True`` when the file was written, ``False`` otherwise.
    """
    return bool(
        cv2.imwrite(
            str(filename),
            frame_bgr,
            [cv2.IMWRITE_PNG_COMPRESSION, compression],
        )
    )


class ExportWorker(QThread):
    """Evaluate and write frames off the UI thread."""

    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        project: Project,
        request: ExportRequest,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._request = request
        self._cancelled = False
        self._skipped_frames: int = 0
        self._last_error: str | None = None

    def cancel(self) -> None:
        """Request a graceful stop after the current frame."""
        self._cancelled = True
        self.requestInterruption()

    def stop(self) -> None:
        """Block until the export thread exits."""
        self.cancel()
        if not self.wait(30000):
            self.terminate()
            self.wait(1000)

    def run(self) -> None:
        # Full-resolution export must not be quietly downgraded by whatever
        # proxy width the interactive Viewer happens to be set to.
        self._project.set_full_resolution_override(self._request.full_resolution)
        # Sequential rendering never revisits a frame, so disable the
        # interactive cross-frame cache for the duration of the export.
        self._project.set_export_mode(True)
        # Fresh slate so any exception surfaced afterward is from this run,
        # not a stale failure left over from earlier interactive preview.
        for node in self._project.nodes.values():
            node.exception_log.clear()
        try:
            self._export()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            self._project.set_export_mode(False)
            self._project.set_full_resolution_override(False)

    def _export(self) -> None:
        request = self._request
        start = max(0, request.start_frame)
        end = max(start, request.end_frame)
        total = end - start + 1
        if total <= 0:
            self.failed.emit("Export range is empty.")
            return

        if request.format == ExportFormat.PNG_SEQUENCE:
            self._export_png_sequence(start, end, total)
            return
        self._export_mp4(start, end, total)

    def _evaluate_frame_rgb(self, frame_num: int) -> tuple[np.ndarray | None, AudioData | None]:
        """Evaluate a frame and return it as a contiguous uint8 RGB array with audio.

        Returns:
            Tuple of (frame_rgb, audio_data). Frame may be None if evaluation fails.
            Audio may be None if no audio is available.
        """
        result = self._project.evaluate_node(self._request.viewer_id, frame_num)

        # Handle FrameWithAudio (frame with audio data)
        if isinstance(result, FrameWithAudio):
            frame_result = result.frame
            audio_result = result.audio
        # Handle multi-output nodes (like Tracker's x/y)
        elif isinstance(result, dict):
            frame_result = result.get("frame")
            audio_result = None
        else:
            frame_result = result
            audio_result = None

        if not isinstance(frame_result, np.ndarray):
            self._skipped_frames += 1
            return None, None

        # Only bridge dtypes when the pipeline handed back something other
        # than display-ready 8-bit RGB. The common case is already uint8,
        # and ``to_display_u8`` always allocates, so re-normalizing here
        # would cost an extra full-frame copy on every exported frame.
        frame = frame_result if frame_result.dtype == np.uint8 else to_display_u8(frame_result)
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        elif frame.shape[2] == 4:
            frame = np.ascontiguousarray(frame[:, :, :3])
        elif frame.shape[2] != 3:
            self._skipped_frames += 1
            return None, None

        if not frame.flags.c_contiguous:
            frame = np.ascontiguousarray(frame)

        return frame, audio_result

    def _find_last_exception_message(self) -> str | None:
        """Scan every node for the most recent exception logged this run."""
        for node in self._project.nodes.values():
            if node.exception_log:
                return f"{node.name}: {node.exception_log[-1]}"
        return None

    def _no_frames_message(self, verb: str) -> str:
        """Build a diagnostic message when an export produced zero frames."""
        self._last_error = self._find_last_exception_message()
        detail = f" Last error — {self._last_error}" if self._last_error else ""
        return f"No frames could be {verb} ({self._skipped_frames} skipped).{detail}"

    def _encode_workers(self) -> int:
        """Resolve the encoder thread count for this job."""
        requested = int(self._request.encode_workers)
        return requested if requested > 0 else _default_encode_workers()

    def _export_png_sequence(self, start: int, end: int, total: int) -> None:
        out_dir = self._request.output_path
        out_dir.mkdir(parents=True, exist_ok=True)

        compression: int = max(0, min(9, int(self._request.png_compression)))
        workers: int = self._encode_workers()
        # Enough queued work to keep every worker busy while staying within
        # roughly two frames of buffering per worker.
        backlog: int = max(8, workers * 2)

        written = 0
        in_flight: deque[Future[bool]] = deque()
        evaluate = self._evaluate_frame_rgb

        def drain(count: int) -> int:
            """Collect ``count`` completed encodes, returning successes."""
            completed = 0
            while in_flight and count > 0:
                if in_flight[0].result():
                    completed += 1
                in_flight.popleft()
                count -= 1
            return completed

        pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="AphelionPng",
        )
        try:
            for index, frame_num in enumerate(range(start, end + 1)):
                if self._cancelled or self.isInterruptionRequested():
                    pool.shutdown(wait=False, cancel_futures=True)
                    self.failed.emit("Export cancelled.")
                    return

                frame, _ = evaluate(frame_num)
                if frame is not None:
                    # Colour-convert on the producer thread so each queued
                    # task holds one frame buffer instead of two.
                    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    filename = out_dir / f"frame_{frame_num:06d}.png"
                    in_flight.append(
                        pool.submit(
                            _encode_png_bgr,
                            bgr,
                            filename,
                            compression,
                        )
                    )

                # Once the backlog is reached we block on the oldest encodes.
                # This keeps memory bounded while still giving every worker
                # something to chew on.
                if len(in_flight) >= backlog:
                    written += drain(len(in_flight) - workers + 1)

                if ((index + 1) % _PROGRESS_UPDATE_INTERVAL == 0) or (index + 1 == total):
                    self.progress.emit(index + 1, total)

            written += drain(len(in_flight))
        finally:
            pool.shutdown(wait=True)

        if written == 0:
            self.failed.emit(self._no_frames_message("evaluated for export"))
            return
        self.finished_ok.emit(str(out_dir))

    def _export_mp4(self, start: int, end: int, total: int) -> None:
        audio_sample_rate = max(1, int(self._request.export_sample_rate))
        audio_channels = 1 if int(self._request.export_channels) == 1 else 2
        include_audio: bool = self._request.export_audio_enabled
        output = self._request.output_path

        # Single pass: the first valid frame both probes the dimensions and
        # opens the writer. The old flow probed a frame and then re-evaluated
        # it in the main loop; with the export scratch cache that re-probe
        # would be a full duplicate graph evaluation.
        writer: Mp4VideoWriter | None = None
        writer_write = None
        width = 0
        height = 0
        written = 0
        evaluate = self._evaluate_frame_rgb
        fps = float(max(1, self._request.fps))

        try:
            for index, frame_num in enumerate(range(start, end + 1)):
                if self._cancelled or self.isInterruptionRequested():
                    self.failed.emit("Export cancelled.")
                    return

                frame, audio = evaluate(frame_num)
                if frame is None:
                    continue

                if writer is None:
                    height, width = frame.shape[:2]
                    output.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        writer = Mp4VideoWriter(
                            output,
                            fps=fps,
                            width=width,
                            height=height,
                            audio_sample_rate=audio_sample_rate,
                            audio_channels=audio_channels,
                            include_audio=include_audio,
                            quality=self._request.export_quality,
                        )
                    except (OSError, RuntimeError) as exc:
                        self.failed.emit(f"Could not open the video writer: {exc}")
                        return
                    writer_write = writer.write
                elif frame.shape[0] != height or frame.shape[1] != width:
                    interpolation = (
                        cv2.INTER_AREA
                        if frame.shape[0] > height or frame.shape[1] > width
                        else cv2.INTER_LINEAR
                    )
                    frame = cv2.resize(frame, (width, height), interpolation=interpolation)

                writer_write(frame, audio=audio if include_audio else None)
                written += 1

                if ((index + 1) % _PROGRESS_UPDATE_INTERVAL == 0) or (index + 1 == total):
                    self.progress.emit(index + 1, total)
        finally:
            if writer is not None:
                writer.close()

        if written == 0:
            self.failed.emit(self._no_frames_message("written"))
            return
        self.finished_ok.emit(str(output))
