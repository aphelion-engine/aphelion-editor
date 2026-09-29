"""Persistent FFmpeg decode+scale pipe for high-resolution playback.

Why this exists
---------------
OpenCV's FFmpeg backend ignores mid-stream resize requests on this build, so a
4K source feeding a 960-pixel Viewer always materialises a full 3840x2160 BGR
frame (~24 MB) and then software-downscales it — every frame. A dedicated
FFmpeg process fuses decode and scaling (``-vf scale``) so only the small RGB
frame is ever produced. Measured on 4K H.264/HEVC: ~2x the throughput of the
OpenCV full-decode path with ~12x less memory per frame.

The pipe is sequential. Random access restarts the process at the requested
timestamp; ``-ss`` before ``-i`` lands on the preceding keyframe, and the
caller reads forward to the exact target. stderr is sent to DEVNULL so a
noisy mid-GOP seek can never block the process on a full pipe buffer.
"""

from __future__ import annotations

import subprocess

import imageio_ffmpeg
import numpy as np


def _even(value: int) -> int:
    value = int(value)
    return value if value <= 2 else value - (value % 2)


class FfmpegPipe:
    """A single decoder process emitting RGB24 frames at a fixed scaled size."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._width: int = 0
        self._height: int = 0
        self._frame_bytes: int = 0

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def start(
        self,
        path: str,
        *,
        target_width: int,
        native_width: int,
        native_height: int,
        start_time_sec: float = 0.0,
    ) -> None:
        """(Re)start the process, decoding ``path`` at ``target_width``.

        ``target_width`` equal to or above the native width means full
        resolution, in which case no scale filter is added.
        """
        self.stop()

        width = _even(max(2, min(int(target_width), int(native_width))))
        if width >= native_width:
            width = native_width
        height = _even(int(round(native_height * (width / float(native_width)))))
        if width <= 0 or height <= 0:
            return

        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        if start_time_sec > 0.0:
            command.extend(("-ss", f"{start_time_sec:.6f}"))
        command.extend(("-i", path, "-an"))
        if width < native_width:
            command.extend(("-vf", f"scale={width}:{height}"))
        command.extend(("-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"))

        try:
            self._proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._proc = None
            return

        self._width = width
        self._height = height
        self._frame_bytes = width * height * 3

    def read(self) -> np.ndarray | None:
        """Return the next RGB24 frame as an ``(H, W, 3)`` uint8 array, or None at EOF."""
        proc = self._proc
        if proc is None or proc.stdout is None or self._frame_bytes <= 0:
            return None
        try:
            # Read directly into the final writable storage, avoiding a bytes
            # allocation followed by a second full-frame memcpy. Pipes may
            # return short reads; only complete frames can enter the graph.
            frame = np.empty((self._height, self._width, 3), dtype=np.uint8)
            view = memoryview(frame).cast('B')
            offset = 0
            while offset < len(view):
                count = proc.stdout.readinto(view[offset:])
                if not count:
                    return None
                offset += count
        except (OSError, ValueError):
            return None
        return frame

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass
        if proc.stdout is not None:
            proc.stdout.close()
