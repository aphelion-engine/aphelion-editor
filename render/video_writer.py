"""Reliable H.264 MP4 writer used by the export pipeline.

``cv2.VideoWriter`` with the ``mp4v`` fourcc is the previous approach and is
a common source of "corrupted" exports: OpenCV's headless build lacks a
proper H.264 encoder, so it silently falls back to tagging a non-standard
MPEG-4 Part 2 bitstream as an ``.mp4`` container. Many players, browsers,
and NLEs refuse to open the result or report it as damaged.

This module instead pipes raw RGB frames straight through FFmpeg (via the
bundled ``imageio-ffmpeg`` binary, so no system FFmpeg install is required)
encoded as H.264 with 4:2:0 chroma subsampling and a ``+faststart`` moov
atom, which is the de-facto standard for universally playable MP4 output.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

import cv2
import imageio
import numpy as np

_H264_CRF: int = 18
"""Constant rate factor for libx264 (lower is higher quality; 18 is near-lossless)."""

_H264_PRESET: str = "medium"
"""libx264 speed/efficiency preset; a reasonable default for export jobs."""


class Mp4VideoWriter:
    """Streams uint8 HxWx3 RGB frames to disk as an H.264 MP4 via FFmpeg."""

    def __init__(self, output_path: Path, *, fps: float, width: int, height: int) -> None:
        """Open the FFmpeg-backed writer.

        Parameters:
            output_path: Destination ``.mp4`` file path.
            fps: Output frame rate (clamped to at least 1 by the caller).
            width: Source frame width in pixels.
            height: Source frame height in pixels.

        Side effects:
            Spawns an FFmpeg subprocess (via ``imageio-ffmpeg``) that remains
            open until ``close`` is called.

        Raises:
            OSError: If the FFmpeg binary cannot be located or started.
            RuntimeError: If the writer fails to initialize.
        """
        # libx264 requires even dimensions for 4:2:0 chroma subsampling;
        # pad by one replicated pixel row/column rather than resizing so the
        # visible image is never distorted.
        self._pad_right: int = width % 2
        self._pad_bottom: int = height % 2
        self._writer: Any = imageio.get_writer(
            str(output_path),
            format="FFMPEG",
            mode="I",
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=1,
            output_params=[
                "-crf",
                str(_H264_CRF),
                "-preset",
                _H264_PRESET,
                "-movflags",
                "+faststart",
            ],
        )

    def write(self, frame_rgb: np.ndarray) -> None:
        """Append one uint8 HxWx3 RGB frame, padding to even dimensions."""
        if self._pad_right or self._pad_bottom:
            frame_rgb = cv2.copyMakeBorder(
                frame_rgb,
                0,
                self._pad_bottom,
                0,
                self._pad_right,
                cv2.BORDER_REPLICATE,
            )
        self._writer.append_data(frame_rgb)

    def close(self) -> None:
        """Flush buffered frames and finalize the MP4 container."""
        self._writer.close()

    def __enter__(self) -> Mp4VideoWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
