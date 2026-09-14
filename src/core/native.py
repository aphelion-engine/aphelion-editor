"""Optional native acceleration for the media engine.

``aphelion_native`` is a C extension (see ``native/aphelion_native.c``) that
implements the frame operations where native code measurably beats calling
into NumPy/OpenCV:

* **in-place BGR→RGB swap** — replaces a ``cv2.cvtColor`` that allocates a
  whole new frame, mutating the decoder's own buffer instead;
* **fused BGR→RGB + box downscale** — replaces a ``cvtColor`` + ``resize``
  pair (two passes, one intermediate allocation) with one pass into a
  caller-supplied buffer;
* **RGB→luma** — writes into a caller buffer instead of allocating.

Plus a byte-budgeted buffer **pool**, which removes the per-frame
allocate/discard churn that shows up as allocator time and GC pressure.

Why this module exists rather than importing the extension directly
------------------------------------------------------------------
Three reasons, all about not making the application fragile:

1. **The extension is optional.** Nothing here fails if it was never built.
   :data:`BACKEND` reports which implementation is live, and every operation
   has an equivalent NumPy/OpenCV fallback that is exercised by the test
   suite so the fallback path cannot rot.
2. **Failure is contained.** A missing module, a stale ABI, a partially
   built artefact — all degrade to the fallback rather than raising at
   import time.
3. **One place to look.** Callers ask for :func:`kernels` and use the
   returned object; they never branch on native availability themselves.

Probing is lazy and cached, and the import attempt happens on first use
rather than at application start, so a cold launch never waits for it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "BACKEND",
    "BufferPool",
    "FrameKernels",
    "KernelProbe",
    "kernels",
    "native_available",
    "probe",
]


@dataclass(frozen=True, slots=True)
class KernelProbe:
    """Result of looking for the native extension."""

    available: bool
    version: int = 0
    module_path: str = ""
    error: str = ""

    @property
    def backend(self) -> str:
        """Return ``"native"`` or ``"python"``."""
        return "native" if self.available else "python"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for diagnostics."""
        return {
            "available": self.available,
            "backend": self.backend,
            "version": self.version,
            "module_path": self.module_path,
            "error": self.error,
        }


_PROBE_LOCK = threading.Lock()
_PROBE: KernelProbe | None = None
_MODULE: Any = None


def probe(refresh: bool = False) -> KernelProbe:
    """Return the cached native-extension probe.

    Parameters:
        refresh: Re-attempt the import (used by tests and by a rebuild).
    """
    global _PROBE, _MODULE

    if _PROBE is not None and not refresh:
        return _PROBE

    with _PROBE_LOCK:
        if _PROBE is not None and not refresh:
            return _PROBE

        try:
            import aphelion_native  # type: ignore[import-not-found]

            required = ("swap_bgr_rgb_inplace", "resize_bgr_to_rgb", "rgb_to_luma")
            missing = [name for name in required if not hasattr(aphelion_native, name)]
            if missing:
                _MODULE = None
                _PROBE = KernelProbe(
                    available=False,
                    module_path=getattr(aphelion_native, "__file__", ""),
                    error=f"missing entry points: {', '.join(missing)}",
                )
            else:
                _MODULE = aphelion_native
                _PROBE = KernelProbe(
                    available=True,
                    version=int(
                        getattr(aphelion_native, "APHELION_NATIVE_VERSION", 0)
                    ),
                    module_path=str(getattr(aphelion_native, "__file__", "")),
                )
        except ImportError as exc:
            _MODULE = None
            _PROBE = KernelProbe(available=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a broken extension must not crash
            _MODULE = None
            _PROBE = KernelProbe(available=False, error=f"{type(exc).__name__}: {exc}")

        return _PROBE


def native_available() -> bool:
    """Return whether the native kernels are usable."""
    return probe().available


def _native_module() -> Any:
    """Return the imported native module, or ``None``."""
    probe()
    return _MODULE


# ----------------------------------------------------------------------
# Buffer pool
# ----------------------------------------------------------------------


class BufferPool:
    """Byte-budgeted pool of reusable frame buffers.

    Hands out writable buffers that can be wrapped zero-copy as NumPy
    arrays, so a frame can be built into pooled memory instead of a fresh
    allocation on every presentation.

    The native implementation is used when available; otherwise a small
    pure-Python equivalent provides the same API and accounting. The
    fallback matters: it is what the test suite exercises, so behaviour
    cannot silently diverge between the two backends.

    Parameters:
        budget_bytes: Maximum bytes retained while idle. Buffers released
            beyond the budget are dropped rather than pooled.
    """

    __slots__ = ("_native", "_fallback", "_budget", "_lock")

    def __init__(self, budget_bytes: int = 256 * 1024 * 1024) -> None:
        self._budget = max(0, int(budget_bytes))
        self._lock = threading.Lock()
        module = _native_module()
        self._native = None
        self._fallback: dict[int, list[bytearray]] | None = None
        self._fallback_stats = {"hits": 0, "misses": 0, "releases": 0, "discards": 0}
        self._fallback_bytes = 0

        if module is not None and hasattr(module, "Pool"):
            try:
                self._native = module.Pool(self._budget)
            except Exception:  # noqa: BLE001 - fall back rather than fail
                self._native = None

        if self._native is None:
            self._fallback = {}

    @property
    def backend(self) -> str:
        """Return the implementation actually in use."""
        return "native" if self._native is not None else "python"

    def acquire(self, size: int) -> bytearray:
        """Return a writable buffer of exactly ``size`` bytes."""
        if size <= 0:
            raise ValueError("BufferPool.acquire: size must be positive")

        if self._native is not None:
            return self._native.acquire(int(size))

        assert self._fallback is not None
        with self._lock:
            bucket = self._fallback.get(size)
            if bucket:
                self._fallback_stats["hits"] += 1
                self._fallback_bytes -= size
                return bucket.pop()
            self._fallback_stats["misses"] += 1
        return bytearray(size)

    def release(self, buffer: bytearray) -> bool:
        """Return ``buffer`` to the pool; ``True`` when it was retained."""
        if self._native is not None:
            return bool(self._native.release(buffer))

        size = len(buffer)
        if size <= 0:
            return False

        assert self._fallback is not None
        with self._lock:
            self._fallback_stats["releases"] += 1
            if self._fallback_bytes + size > self._budget:
                self._fallback_stats["discards"] += 1
                return False
            self._fallback.setdefault(size, []).append(buffer)
            self._fallback_bytes += size
        return True

    def clear(self) -> None:
        """Drop every pooled buffer."""
        if self._native is not None:
            self._native.clear()
            return
        with self._lock:
            if self._fallback is not None:
                self._fallback.clear()
            self._fallback_bytes = 0

    def stats(self) -> dict[str, float | int | str]:
        """Return byte accounting and reuse counters."""
        if self._native is not None:
            payload = dict(self._native.stats())
            payload["backend"] = "native"
            return payload

        hits = self._fallback_stats["hits"]
        misses = self._fallback_stats["misses"]
        requests = hits + misses
        with self._lock:
            idle = self._fallback_bytes
            buckets = len(self._fallback) if self._fallback else 0
        return {
            "backend": "python",
            "idle_bytes": idle,
            "budget_bytes": self._budget,
            "hits": hits,
            "misses": misses,
            "releases": self._fallback_stats["releases"],
            "discards": self._fallback_stats["discards"],
            "live_buffers": buckets,
            "hit_rate": (hits / requests) if requests else 0.0,
        }


# ----------------------------------------------------------------------
# Kernels
# ----------------------------------------------------------------------


class FrameKernels:
    """Backend-agnostic frame operations.

    Every method has an identical contract regardless of backend, which is
    what lets callers stay ignorant of whether the extension is present.
    Inputs must be C-contiguous; callers use :func:`as_array` to get a
    contiguous view cheaply.
    """

    __slots__ = ("_module",)

    def __init__(self, module: Any = None) -> None:
        self._module = module

    @property
    def backend(self) -> str:
        """Return ``"native"`` or ``"python"``."""
        return "native" if self._module is not None else "python"

    # ------------------------------------------------------------------
    # Channel swap
    # ------------------------------------------------------------------

    def swap_bgr_rgb_inplace(self, frame: np.ndarray) -> None:
        """Swap red and blue channels of a ``HxWx3`` uint8 frame in place.

        This is the decode path's replacement for
        ``cv2.cvtColor(frame, COLOR_BGR2RGB)``. The OpenCV call allocates a
        new frame; this mutates the buffer the decoder already produced, so
        it costs O(1) memory and performs no allocation.

        Safe to call on a buffer the caller owns exclusively. Do **not**
        call it on a frame that is already referenced by a cache or another
        consumer.
        """
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(
                "swap_bgr_rgb_inplace expects a HxWx3 uint8 frame, "
                f"got {frame.dtype} {frame.shape}"
            )

        height, width = frame.shape[:2]

        if self._module is not None:
            self._module.swap_bgr_rgb_inplace(frame, width, height)
            return

        _swap_bgr_rgb_python(frame)

    # ------------------------------------------------------------------
    # Fused convert + downscale
    # ------------------------------------------------------------------

    def resize_bgr_to_rgb(
        self,
        source: np.ndarray,
        destination: np.ndarray,
        out_width: int,
        out_height: int,
    ) -> None:
        """Box-downsample BGR ``source`` into RGB ``destination``.

        Replaces ``cvtColor`` + ``resize`` with one pass that writes
        straight into ``destination``. ``destination`` is normally a pooled
        buffer wrapped with :func:`as_array`, so the whole operation costs
        no allocation.
        """
        src_height, src_width = source.shape[:2]
        view = destination.reshape(out_height, out_width, 3)

        if self._module is not None:
            self._module.resize_bgr_to_rgb(
                source, view, src_width, src_height, int(out_width), int(out_height)
            )
            return

        _resize_bgr_to_rgb_python(
            source, view, int(out_width), int(out_height)
        )

    # ------------------------------------------------------------------
    # Luma
    # ------------------------------------------------------------------

    def luma(self, frame: np.ndarray, out: np.ndarray | None = None) -> np.ndarray:
        """Convert an RGB ``HxWx3`` uint8 frame to a ``HxW`` uint8 luma plane.

        Coefficients match ``cv2.COLOR_RGB2GRAY`` exactly, so tracking and
        histogram results are unchanged by the backend switch.
        """
        height, width = frame.shape[:2]

        if frame.dtype != np.uint8:
            raise ValueError(
                f"luma expects a uint8 frame, got {frame.dtype}"
            )

        if out is None:
            out = np.empty((height, width), dtype=np.uint8)
        elif out.shape[:2] != (height, width):
            raise ValueError(
                f"luma: out shape {out.shape[:2]} does not match frame {(height, width)}"
            )

        if self._module is not None:
            self._module.rgb_to_luma(frame, out, width, height)
            return out

        _luma_python(frame, out)
        return out


# ----------------------------------------------------------------------
# Pure-Python reference implementations
#
# These are the *contract*. The native kernels must agree with them, and
# the test suite checks that they do, so shipping a native build can never
# silently change a pixel.
# ----------------------------------------------------------------------


def _swap_bgr_rgb_python(frame: np.ndarray) -> None:
    """In-place channel swap using one single-channel temporary.

    Costs ``width*height`` bytes of scratch instead of the ``width*height*3``
    a full-frame copy would need, and never allocates a second frame.
    """
    blue = frame[:, :, 0].copy()
    frame[:, :, 0] = frame[:, :, 2]
    frame[:, :, 2] = blue


def _resize_bgr_to_rgb_python(
    source: np.ndarray,
    destination: np.ndarray,
    out_width: int,
    out_height: int,
) -> None:
    """Reference fused convert + box downscale.

    Uses OpenCV for the heavy lifting but writes into the caller's buffer,
    so the fallback still avoids the intermediate-frame allocation the
    previous code paid.
    """
    import cv2

    rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
    src_height, src_width = rgb.shape[:2]

    if (src_width, src_height) == (out_width, out_height):
        resized = rgb
    else:
        resized = cv2.resize(
            rgb, (out_width, out_height), interpolation=cv2.INTER_AREA
        )

    destination[...] = resized


def _luma_python(frame: np.ndarray, out: np.ndarray) -> None:
    """Reference RGB -> luma using OpenCV's exact coefficients."""
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    out[...] = gray


# ----------------------------------------------------------------------
# Zero-copy helpers
# ----------------------------------------------------------------------


def as_array(buffer: bytearray, shape: tuple[int, ...]) -> np.ndarray:
    """Wrap a pooled buffer as a NumPy array without copying.

    The returned array shares memory with ``buffer``; it stays valid for as
    long as the caller keeps a reference, which is why the buffer must not
    be released back to the pool while the array is in use.
    """
    expected = 1
    for dimension in shape:
        expected *= int(dimension)

    if len(buffer) < expected:
        raise ValueError(
            f"buffer holds {len(buffer)} bytes, need {expected} for {shape}"
        )

    return np.frombuffer(buffer, dtype=np.uint8, count=expected).reshape(shape)


def frame_bytes(width: int, height: int, channels: int = 3) -> int:
    """Return the byte size of an uncompressed frame with this geometry."""
    return int(width) * int(height) * int(channels)


_KERNELS_LOCK = threading.Lock()
_KERNELS: FrameKernels | None = None


def kernels() -> FrameKernels:
    """Return the process-wide kernel set, selecting the best backend once."""
    global _KERNELS

    if _KERNELS is not None:
        return _KERNELS

    with _KERNELS_LOCK:
        if _KERNELS is None:
            _KERNELS = FrameKernels(_native_module())
        return _KERNELS


def reset_for_tests() -> None:
    """Clear the cached probe and kernels (used by the test suite)."""
    global _PROBE, _MODULE, _KERNELS
    with _PROBE_LOCK:
        _PROBE = None
        _MODULE = None
    with _KERNELS_LOCK:
        _KERNELS = None


def __getattr__(name: str) -> Any:
    """Resolve ``BACKEND`` lazily (PEP 562).

    ``BACKEND`` is the one thing about this module that is expensive to
    determine (it imports the extension) and trivial to describe. Resolving
    it through the module ``__getattr__`` means ``import core.native`` stays
    cheap, ``from core.native import BACKEND`` yields a plain string rather
    than a wrapper object, and the probe is still performed only once
    because :func:`probe` caches its result.
    """
    if name == "BACKEND":
        return probe().backend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
