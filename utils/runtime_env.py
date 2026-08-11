"""Process-level environment hardening before heavy native libs load."""

from __future__ import annotations

import os


def prepare_process_environment() -> None:
    """Quiet noisy native media loggers (OpenCV / FFmpeg).

    Must run before modules that create video captures are imported.

    Side effects:
        Sets process environment defaults when unset.
    """
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
