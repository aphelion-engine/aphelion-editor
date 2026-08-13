"""Process-level environment hardening before heavy native libs load."""

from __future__ import annotations

import subprocess 
import os

def run_process(command: str) -> int:
    return subprocess.check_call(command, shell=True)

def prepare_process_environment() -> None:
    """Quiet noisy native media loggers (OpenCV / FFmpeg).

    Must run before modules that create video captures are imported.

    Side effects:
        Sets process environment defaults when unset.
    """
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
