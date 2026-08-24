"""Build pip artifacts for the sibling ``aphelion-sdk`` package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

from freeze_config import PLUGIN_SDK_ROOT

SDK_RELEASES_DIR: Final[Path] = PLUGIN_SDK_ROOT / "releases"
EDITOR_RELEASES_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "releases"
_INSTALL_SDK_CMD: Final[Path] = Path(__file__).resolve().parent.parent / "installer" / "install_sdk.cmd"


class SdkReleaseError(RuntimeError):
    """Raised when the SDK pip artifacts cannot be built."""


def ensure_sdk_release() -> Path:
    """Build wheel and sdist into ``aphelion-sdk/releases`` and return the wheel.

    Returns:
        Path to ``aphelion_sdk-*-py3-none-any.whl``.

    Raises:
        SdkReleaseError: If the build produces no wheel.

    Side effects:
        Creates ``releases/`` and writes distribution files.
    """
    SDK_RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    _run_build(SDK_RELEASES_DIR)
    wheel: Path | None = _latest_wheel(SDK_RELEASES_DIR)
    if wheel is None:
        raise SdkReleaseError(f"SDK build produced no wheel in {SDK_RELEASES_DIR}")
    return wheel


def installer_include_files(wheel: Path) -> list[tuple[str, str]]:
    """Return extra freeze include pairs for the SDK wheel and pip helper."""
    files: list[tuple[str, str]] = [(str(wheel.resolve()), f"sdk/{wheel.name}")]
    if _INSTALL_SDK_CMD.is_file():
        files.append((str(_INSTALL_SDK_CMD.resolve()), "install_sdk.cmd"))
    return files


def _latest_wheel(directory: Path) -> Path | None:
    """Return the newest ``aphelion_sdk-*.whl`` in ``directory``."""
    wheels: list[Path] = sorted(directory.glob("aphelion_sdk-*.whl"))
    if not wheels:
        return None
    return wheels[-1]


def _run_build(output_dir: Path) -> None:
    """Run ``python -m build`` and fall back to ``pip wheel``."""
    build_cmd: list[str] = [
        sys.executable,
        "-m",
        "build",
        "--outdir",
        str(output_dir),
        str(PLUGIN_SDK_ROOT),
    ]
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        build_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0:
        return
    _run_pip_wheel(output_dir, completed.stderr)


def _run_pip_wheel(output_dir: Path, build_stderr: str) -> None:
    """Build a wheel with pip when the ``build`` frontend is missing."""
    command: list[str] = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(output_dir),
        str(PLUGIN_SDK_ROOT),
    ]
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail: str = completed.stderr.strip() or build_stderr.strip()
        raise SdkReleaseError(f"Failed to build aphelion-sdk:\n{detail}")
