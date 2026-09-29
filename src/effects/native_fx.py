"""Central dispatch for compiled CPU effects with reference fallbacks.

Frames cross the native boundary through the buffer protocol as contiguous
float32 RGB arrays. The extension writes into a caller-owned output, so the
binding does not convert frames to bytes or make intermediate copies.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

import numpy as np

from effects.frame_ops import ensure_rgb_f32

_BACKEND: ContextVar[str] = ContextVar("aphelion_effect_backend", default="native")

# These IDs are the stable AP_FxEffect values in native/aphelion_fx.h.
_EFFECT_IDS: dict[str, int] = {
    "exposure_contrast": 1,
    "invert": 2,
    "posterize": 3,
    "monochrome": 4,
    "threshold": 5,
    "levels": 6,
    "shadows_highlights": 7,
    "color_balance": 8,
    "color_grade": 9,
    "channel_mixer": 10,
    "duotone": 11,
    "chroma_key": 12,
    "suppress_spill": 13,
    "kaleidoscope": 14,
    "twirl": 15,
    "bulge": 16,
    "ripple": 17,
    "wave_warp": 18,
    "offset": 19,
    "mirror": 20,
    "shockwave": 21,
    "bend": 22,
    "rgb_split": 23,
    "chromatic_aberration": 24,
    "vignette": 25,
    "scanlines": 26,
    "tile": 27,
    "hsv_adjust": 28,
    "vibrance": 29,
    "channel_mask": 30,
    "depth_slice": 31,
    "highlights": 32,
    "input_color": 33,
    "clip_affine": 34,
}


class NativeEffectError(RuntimeError):
    """A compiled effect failed after validating its frame and parameters."""


def blend(background, foreground, *, mode, opacity, mask, reference):
    """Fuse blending and masking without full-frame arithmetic intermediates."""
    module = None if _BACKEND.get() == 'python' else _native_module()
    if module is None or not hasattr(module, 'fx_blend'):
        if _BACKEND.get() != 'python':
            raise NativeEffectError('Native compositor is unavailable; rebuild the native backend')
        return reference()
    from effects.frame_ops import resize_like
    names = ['Normal', 'Add', 'Subtract', 'Multiply', 'Screen', 'Overlay',
             'Difference', 'Darken', 'Lighten']
    bg = np.ascontiguousarray(ensure_rgb_f32(background))
    fg = np.ascontiguousarray(resize_like(ensure_rgb_f32(foreground), bg))
    matte = None if mask is None else np.ascontiguousarray(resize_like(ensure_rgb_f32(mask), bg))
    destination = np.empty_like(bg)
    module.fx_blend(bg, fg, matte, destination, bg.shape[1], bg.shape[0],
                    names.index(mode.name) if mode.name in names else 0, float(opacity))
    return destination


def _native_module():
    """Return the extension only when the generic effects ABI is available."""
    try:
        import aphelion_native  # type: ignore[import-not-found]
    except ImportError as exc:
        raise NativeEffectError('Native effects are required. Build with python native/build.py') from exc
    if getattr(aphelion_native, 'APHELION_NATIVE_VERSION', 0) < 4:
        raise NativeEffectError('Native effects backend is outdated. Rebuild it and restart the editor')
    return aphelion_native


def reference_mode() -> bool:
    """References can only be selected explicitly by tests and diagnostics."""
    return _BACKEND.get() == 'python'


def extended(operation: int, source: np.ndarray, auxiliary: np.ndarray,
             parameters: tuple[float, ...], auxiliary2: np.ndarray | None = None) -> np.ndarray:
    """Run a fused multi-input kernel; no production Python fallback."""
    src = np.ascontiguousarray(ensure_rgb_f32(source))
    aux = np.ascontiguousarray(auxiliary, dtype=np.float32)
    aux2 = None if auxiliary2 is None else np.ascontiguousarray(auxiliary2, dtype=np.float32)
    destination = np.empty_like(src)
    _native_module().fx_extended(src, aux, aux2, destination, src.shape[1], src.shape[0],
                                operation, parameters)
    return destination


@contextmanager
def use_backend(backend: str) -> Iterator[None]:
    """Temporarily force ``python`` or ``native`` dispatch (used by benchmarks)."""
    if backend not in {"python", "native", "auto"}:
        raise ValueError(f"unsupported effects backend: {backend}")
    token = _BACKEND.set(backend)
    try:
        yield
    finally:
        _BACKEND.reset(token)


def backend_name() -> str:
    """Return the backend currently selected for dispatch."""
    if _BACKEND.get() == "python":
        return "python"
    return "native" if _native_module() is not None else "python"


def _run(name: str, frame: np.ndarray, parameters: tuple[float, ...],
         reference: Callable[..., np.ndarray], *, out: np.ndarray | None = None) -> np.ndarray:
    """Run a registered pointwise RGB effect or its Python reference."""
    selected = _BACKEND.get()
    module = None if selected == "python" else _native_module()
    if module is None:
        if selected != "python":
            raise NativeEffectError(f"{name} requested native backend, but it is unavailable")
        return reference(frame)

    source = ensure_rgb_f32(frame)
    if source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("native effects require an HxWx3 RGB frame")
    if not source.flags.c_contiguous:
        source = np.ascontiguousarray(source)
    destination = np.empty_like(source) if out is None else out
    if (destination.dtype != np.float32 or destination.shape != source.shape or
            not destination.flags.c_contiguous or not destination.flags.writeable):
        raise ValueError("native effects destination must be writable contiguous float32 RGB matching source")
    height, width = source.shape[:2]
    try:
        module.fx_apply(source, destination, width, height, _EFFECT_IDS[name], parameters)
    except (TypeError, ValueError, RuntimeError, BufferError) as exc:
        raise NativeEffectError(f"{name} failed: {exc}") from exc
    return destination


def _run_geometry(name: str, frame: np.ndarray, parameters: tuple[float, ...],
                  reference: Callable[..., np.ndarray]) -> np.ndarray:
    """Run a registered coordinate-map effect in C or its existing reference."""
    selected = _BACKEND.get()
    module = None if selected == "python" else _native_module()
    if module is None:
        if selected != "python":
            raise NativeEffectError(f"{name} requested native backend, but it is unavailable")
        return reference(frame)
    source = ensure_rgb_f32(frame)
    if source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("native geometry effects require an HxWx3 RGB frame")
    if not source.flags.c_contiguous:
        source = np.ascontiguousarray(source)
    destination = np.empty_like(source)
    height, width = source.shape[:2]
    try:
        module.fx_geometry(source, destination, width, height, _EFFECT_IDS[name], parameters)
    except (TypeError, ValueError, RuntimeError, BufferError) as exc:
        raise NativeEffectError(f"{name} failed: {exc}") from exc
    return destination


def exposure_contrast(frame: np.ndarray, *, exposure: float, brightness: float,
                      contrast: float) -> np.ndarray:
    """Fused exposure/brightness/contrast kernel or NumPy reference."""
    gain = float((2.0 ** exposure) * contrast)
    offset = float(brightness * 0.01 + 0.5 * (1.0 - contrast))
    return _run("exposure_contrast", frame, (gain, offset),
                lambda image: _exposure_reference(image, gain, offset))


def _exposure_reference(frame: np.ndarray, gain: float, offset: float) -> np.ndarray:
    from effects.color_adjustments import _exposure_contrast_python
    return _exposure_contrast_python(frame, gain=gain, offset=offset)


def invert(frame: np.ndarray) -> np.ndarray:
    """Invert RGB values through a single native read/write pass."""
    return _run("invert", frame, (), _invert_reference)


def _invert_reference(frame: np.ndarray) -> np.ndarray:
    from effects.color_adjustments import _invert_python
    return _invert_python(frame)


def posterize(frame: np.ndarray, *, levels: int) -> np.ndarray:
    """Quantize each RGB channel to evenly spaced levels."""
    count = max(2, min(32, int(levels)))
    return _run("posterize", frame, (float(count),),
                lambda image: _posterize_reference(image, count))


def _posterize_reference(frame: np.ndarray, levels: int) -> np.ndarray:
    from effects.color_adjustments import _posterize_python
    return _posterize_python(frame, levels=levels)


def monochrome(frame: np.ndarray, *, red_weight: float, green_weight: float,
               blue_weight: float) -> np.ndarray:
    """Convert RGB to weighted monochrome in one native pass."""
    weights = np.asarray((red_weight, green_weight, blue_weight), dtype=np.float32)
    total = float(np.sum(weights))
    if total <= 1e-6:
        weights[:] = (0.2126, 0.7152, 0.0722)
    else:
        weights /= np.float32(total)
    normalized = tuple(float(value) for value in weights)
    return _run("monochrome", frame, normalized,
                lambda image: _monochrome_reference(image, *normalized))


def _monochrome_reference(frame: np.ndarray, red_weight: float,
                          green_weight: float, blue_weight: float) -> np.ndarray:
    from effects.color_adjustments import _monochrome_python
    return _monochrome_python(frame, red_weight=red_weight, green_weight=green_weight,
                              blue_weight=blue_weight)


def threshold(frame: np.ndarray, *, level: int, low_color: tuple[int, int, int],
              high_color: tuple[int, int, int]) -> np.ndarray:
    """Map pixels to RGB colors according to luminance."""
    low = tuple(float(value) / 255.0 for value in low_color[:3])
    high = tuple(float(value) / 255.0 for value in high_color[:3])
    threshold_value = max(0, min(255, int(level))) / 255.0
    parameters = (threshold_value, *low, *high)
    return _run("threshold", frame, parameters,
                lambda image: _threshold_reference(image, threshold_value, low, high))


def _threshold_reference(frame: np.ndarray, level: float,
                         low: tuple[float, float, float],
                         high: tuple[float, float, float]) -> np.ndarray:
    from effects.color_adjustments import _threshold_python
    low_color = tuple(int(round(value * 255)) for value in low)
    high_color = tuple(int(round(value * 255)) for value in high)
    return _threshold_python(frame, level=round(level * 255), low_color=low_color,
                             high_color=high_color)


def levels(frame: np.ndarray, *, in_black: float, in_white: float, gamma: float,
           out_black: float, out_white: float, reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Apply fused input/output levels and gamma correction."""
    source = ensure_rgb_f32(frame)
    low_in = float(np.clip(in_black, 0.0, 0.98))
    high_in = float(np.clip(in_white, low_in + 0.02, 1.0))
    low_out = float(np.clip(out_black, 0.0, 0.98))
    high_out = float(np.clip(out_white, low_out + 0.02, 1.0))
    gamma_value = max(0.05, float(gamma))
    return _run("levels", source,
                (low_in, high_in-low_in, 1.0/gamma_value, low_out, high_out-low_out),
                lambda _image: reference())


def shadows_highlights(frame: np.ndarray, *, shadows: float, highlights: float,
                       balance: float, reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Apply shadow lift and highlight compression in a fused pass."""
    pivot = float(np.clip(0.5 + balance * 0.35, 0.15, 0.85))
    return _run("shadows_highlights", frame, (float(shadows), float(highlights), pivot),
                lambda _image: reference())


def color_balance(frame: np.ndarray, *, cyan_red: float, magenta_green: float,
                  yellow_blue: float, preserve_luma: bool,
                  reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Shift the RGB axes in a fused pass, optionally preserving luminance."""
    factor = 64.0 / 255.0
    params = (cyan_red*factor, magenta_green*factor, yellow_blue*factor,
              1.0 if preserve_luma else 0.0)
    return _run("color_balance", frame, params, lambda _image: reference())


def channel_mixer(frame: np.ndarray, matrix: np.ndarray,
                  reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Apply a 3x3 RGB matrix in one native pass."""
    params = tuple(float(value) for value in np.asarray(matrix, dtype=np.float32).reshape(9))
    return _run("channel_mixer", frame, params, lambda _image: reference())


def color_grade(frame: np.ndarray, *, parameters: tuple[float, ...],
                reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Fuse exposure, temperature, lift/gamma/gain, saturation, and mix."""
    return _run("color_grade", frame, parameters, lambda _image: reference())


def duotone(frame: np.ndarray, *, dark: tuple[int, int, int],
            light: tuple[int, int, int], reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Map luminance between two colors in one native pass."""
    params = tuple(float(value)/255.0 for value in (*dark[:3], *light[:3]))
    return _run("duotone", frame, params, lambda _image: reference())


def chroma_key(frame: np.ndarray, *, key_color: tuple[int, int, int],
               tolerance: float, softness: float,
               reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Generate a soft RGB chroma matte in one native pass."""
    key = tuple(float(value)/255.0 for value in key_color[:3])
    params = (*key, max(0.0, float(tolerance)), max(1e-4, float(softness)))
    return _run("chroma_key", frame, params, lambda _image: reference())


def suppress_spill(frame: np.ndarray, *, key_color: tuple[int, int, int],
                   amount: float, reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Reduce the dominant key-color channel in one native pass."""
    key = np.asarray(key_color[:3])
    dominant = int(np.argmax(key))
    params = (float(dominant), float(np.clip(amount, 0.0, 1.0)))
    return _run("suppress_spill", frame, params, lambda _image: reference())


def geometry_effect(name: str, frame: np.ndarray, parameters: tuple[float, ...],
                    reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Shared entry point for migrated artistic spatial effects."""
    return _run_geometry(name, frame, parameters, lambda _image: reference())


def pointwise_effect(name: str, frame: np.ndarray, parameters: tuple[float, ...],
                     reference: Callable[[], np.ndarray]) -> np.ndarray:
    """Dispatch other registered pointwise effects."""
    return _run(name, frame, parameters, lambda _image: reference())
