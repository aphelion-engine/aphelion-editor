"""Shared, allocation-conscious operations for frame effects.

Frame representations
---------------------
The engine moves frames between two representations rather than one:

``SOURCE_DTYPE`` (uint8)
    Exactly what the decoder, the image importer, and the caching layer
    prefer. Four times denser than float32, so a byte-budgeted cache holds
    four times as many frames, and a frame with no effects in its path
    never has to be touched at all.

``FRAME_DTYPE`` (float32)
    The canonical *processing* contract: ``HxWx3`` with a nominal
    ``[0.0, 1.0]`` range representing display-referred SDR. Values may
    briefly exceed this range mid-graph (e.g. after an exposure boost);
    only the display/export boundary (`to_display_u8`) clamps back to
    ``[0, 1]`` before quantizing to 8-bit.

Why this matters
----------------
Historically the source node promoted every decoded frame to float32
eagerly, and the viewport quantized it straight back to uint8 — two full
frame passes plus two allocations per frame to reproduce the pixels the
decoder had already produced. Bare ``Video Input → Viewer`` playback paid
that for nothing.

Now the promotion is **lazy and demand-driven**: ``ensure_rgb_f32`` is
called by the node that actually needs float precision, and the compiled
render plan (``core.render_plan``) only allows a source to emit its raw
8-bit form when every node on the path to the Viewer has declared that it
tolerates it. See ``Node.accepts_u8_frame``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    # Imported for typing only. Keeping this out of the runtime import graph
    # breaks the effects <-> core.nodes cycle (core.nodes.frame_base imports
    # mix_frames from this module) and keeps this hot path cheap to import.
    from core.nodes.base import ColorRgb

#: Canonical processing representation.
FRAME_DTYPE: np.dtype = np.dtype(np.float32)

#: Raw/decoder representation; what the cache and the display path prefer.
SOURCE_DTYPE: np.dtype = np.dtype(np.uint8)

#: Precomputed reciprocals so the promotion path never builds a Python float.
_INV_U8: np.float32 = np.float32(1.0 / 255.0)
_INV_U16: np.float32 = np.float32(1.0 / 65535.0)


def _ensure_three_channels(frame: np.ndarray) -> np.ndarray:
    """Normalize channel layout without changing dtype or value range.

    Deliberately mirrors the historical slicing semantics for one-channel
    and >4-channel inputs so mask-style payloads keep behaving exactly as
    they did before this module gained multi-dtype support.
    """
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
    if frame.shape[2] == 3:
        return frame if frame.flags.c_contiguous else np.ascontiguousarray(frame)
    return np.ascontiguousarray(frame[:, :, :3])


def is_source_frame(frame: np.ndarray) -> bool:
    """Return whether ``frame`` is already in the raw 8-bit representation."""
    return isinstance(frame, np.ndarray) and frame.dtype == SOURCE_DTYPE


def ensure_rgb_f32(frame: np.ndarray) -> np.ndarray:
    """Return a contiguous 3-channel RGB float32 frame normalized to ``[0, 1]``.

    Accepts every representation the engine may hand a node:

    * ``float32`` / ``float64`` assumed already in ``[0, 1]`` — passed through
    * ``uint8`` (0…255) — promoted and scaled
    * ``uint16`` (0…65535) — promoted and scaled

    Normalizing here is what makes ``Node.accepts_u8_frame`` possible: a node
    that starts with this call transparently accepts a raw decoded frame and
    pays the promotion exactly once, at the point where float precision is
    genuinely required.

    The single-pass ``np.multiply(..., dtype=float32)`` form is used instead
    of ``astype`` followed by a multiply, which allocated an extra full-frame
    temporary on every promoted frame.
    """
    dtype = frame.dtype

    if dtype == np.float32:
        return _ensure_three_channels(frame)

    if dtype == np.uint8:
        return np.multiply(_ensure_three_channels(frame), _INV_U8, dtype=np.float32)

    if dtype == np.uint16:
        return np.multiply(_ensure_three_channels(frame), _INV_U16, dtype=np.float32)

    # float64 and anything else: normalize channels first where the conversion
    # is cheap, then fall back to a plain cast.
    rgb = _ensure_three_channels(frame)
    return rgb if rgb.dtype == np.float32 else rgb.astype(np.float32, copy=False)


def from_source_u8(frame_u8: np.ndarray) -> np.ndarray:
    """Promote a raw 8-bit RGB frame (decoder/import) into the float pipeline."""
    return np.multiply(frame_u8, _INV_U8, dtype=np.float32)


def ensure_rgb_u8(frame: np.ndarray) -> np.ndarray:
    """Return a contiguous 3-channel RGB uint8 frame.

    The inverse of :func:`ensure_rgb_f32`, used by the display/present path
    and by anything that wants the dense representation (caches, thumbnails,
    encoder hand-off).
    """
    if frame.dtype == np.uint8:
        return _ensure_three_channels(frame)

    rgb = _ensure_three_channels(frame)

    if rgb.dtype == np.uint16:
        return cv2.convertScaleAbs(rgb, alpha=255.0 / 65535.0)

    return to_display_u8(rgb)


def to_display_u8(
    frame: np.ndarray,
    dst: np.ndarray | None = None,
) -> np.ndarray:
    """Quantize a pipeline frame for Qt display or 8-bit export.

    Accepts either representation:

    * already-``uint8`` input is returned unchanged — the display boundary is
      a *no-op* for a frame that never entered the float pipeline, which is
      the entire point of the lazy promotion in :func:`ensure_rgb_f32`.
    * ``uint16`` input is scaled directly.
    * float input is clamped to ``[0, 1]`` then saturated and rounded by a
      single SIMD-accelerated ``cv2.convertScaleAbs`` pass (instead of a
      separate multiply + rint + astype chain, which allocated three
      temporaries per frame).

    Parameters:
        frame: Pipeline frame in any supported representation.
        dst: Optional pre-allocated ``uint8`` output buffer of the right
            shape, typically from the CPU frame pool. When supplied the
            quantization writes into it instead of allocating.
    """
    if frame.dtype == np.uint8:
        return _ensure_three_channels(frame)

    if frame.dtype == np.uint16:
        return cv2.convertScaleAbs(
            _ensure_three_channels(frame),
            dst=dst,
            alpha=255.0 / 65535.0,
        )

    rgb = _ensure_three_channels(frame)
    if rgb.dtype != np.float32:
        rgb = rgb.astype(np.float32, copy=False)

    clamped: np.ndarray = np.clip(rgb, 0.0, 1.0)
    return cv2.convertScaleAbs(clamped, dst=dst, alpha=255.0)


def color01(rgb: ColorRgb) -> np.ndarray:
    """Convert a 0-255 UI color tuple to a float32 ``(3,)`` array in ``[0, 1]``."""
    return np.asarray(rgb, dtype=np.float32) * np.float32(1.0 / 255.0)


def resize_like(frame: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Resize ``frame`` to ``reference`` dimensions only when required."""
    target_height: int = int(reference.shape[0])
    target_width: int = int(reference.shape[1])
    if frame.shape[:2] == (target_height, target_width):
        return frame
    interpolation: int = (
        cv2.INTER_AREA
        if frame.shape[0] > target_height or frame.shape[1] > target_width
        else cv2.INTER_LINEAR
    )
    return cv2.resize(frame, (target_width, target_height), interpolation=interpolation)


def mix_frames(
    source: np.ndarray,
    effected: np.ndarray,
    amount: float,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Mix ``effected`` over ``source`` using amount and optional luma mask."""
    mix: float = float(np.clip(amount, 0.0, 1.0))
    if mix <= 0.0:
        return source
    foreground: np.ndarray = resize_like(effected, source)
    if mask is None:
        if mix >= 1.0:
            return foreground
        return source * np.float32(1.0 - mix) + foreground * np.float32(mix)
    return _masked_mix(source, foreground, mix, mask)


def luma_mask(mask: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Return a resized float32 mask shaped ``HxWx1`` in 0-1."""
    normalized: np.ndarray = resize_like(ensure_rgb_f32(mask), reference)
    gray: np.ndarray = cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY)
    return gray[..., None]


def _masked_mix(
    source: np.ndarray,
    foreground: np.ndarray,
    amount: float,
    mask: np.ndarray,
) -> np.ndarray:
    """Blend two aligned RGB frames through a float32 luma mask."""
    alpha: np.ndarray = luma_mask(mask, source)
    if amount < 1.0:
        alpha = alpha * np.float32(amount)
    return source * (1.0 - alpha) + foreground * alpha
