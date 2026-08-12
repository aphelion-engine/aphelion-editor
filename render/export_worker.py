"""Background export of evaluated viewer frames to video or image sequences."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from effects.frame_ops import to_display_u8
from render.video_writer import Mp4VideoWriter

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
        # Fresh slate so any exception surfaced afterward is from this run,
        # not a stale failure left over from earlier interactive preview.
        for node in self._project.nodes.values():
            node.exception_log.clear()
        try:
            self._export()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
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

    def _evaluate_frame_rgb(self, frame_num: int) -> np.ndarray | None:
        """Evaluate a frame and return it as a contiguous uint8 RGB array."""
        result = self._project.evaluate_node(self._request.viewer_id, frame_num)
        if not isinstance(result, np.ndarray):
            self._skipped_frames += 1
            return None
        frame = np.ascontiguousarray(result)
        if frame.dtype != np.uint8:
            frame = to_display_u8(frame)
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
        elif frame.shape[2] != 3:
            self._skipped_frames += 1
            return None
        return np.ascontiguousarray(frame)

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

    def _export_png_sequence(self, start: int, end: int, total: int) -> None:
        out_dir = self._request.output_path
        out_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for index, frame_num in enumerate(range(start, end + 1)):
            if self._cancelled or self.isInterruptionRequested():
                self.failed.emit("Export cancelled.")
                return
            frame = self._evaluate_frame_rgb(frame_num)
            if frame is None:
                continue
            filename = out_dir / f"frame_{frame_num:06d}.png"
            cv2.imwrite(str(filename), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            written += 1
            self.progress.emit(index + 1, total)
        if written == 0:
            self.failed.emit(self._no_frames_message("evaluated for export"))
            return
        self.finished_ok.emit(str(out_dir))

    def _export_mp4(self, start: int, end: int, total: int) -> None:
        first: np.ndarray | None = None
        for frame_num in range(start, end + 1):
            first = self._evaluate_frame_rgb(frame_num)
            if first is not None:
                break
        if first is None:
            self.failed.emit(self._no_frames_message("evaluated for export"))
            return

        height, width = first.shape[:2]
        output = self._request.output_path
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            writer = Mp4VideoWriter(
                output,
                fps=float(max(1, self._request.fps)),
                width=width,
                height=height,
            )
        except (OSError, RuntimeError) as exc:
            self.failed.emit(f"Could not open the video writer: {exc}")
            return

        written = 0
        try:
            for index, frame_num in enumerate(range(start, end + 1)):
                if self._cancelled or self.isInterruptionRequested():
                    self.failed.emit("Export cancelled.")
                    return
                # Cache-backed, so re-evaluating the probed frame above is free.
                frame = self._evaluate_frame_rgb(frame_num)
                if frame is None:
                    continue
                if frame.shape[0] != height or frame.shape[1] != width:
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)
                written += 1
                self.progress.emit(index + 1, total)
        finally:
            writer.close()

        if written == 0:
            self.failed.emit(self._no_frames_message("written"))
            return
        self.finished_ok.emit(str(output))
