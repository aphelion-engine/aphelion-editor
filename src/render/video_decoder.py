"""Fast OpenCV-backed video decode for interactive preview.

Design goals:
- Sequential reads during playback (avoid brittle random seeks)
- Decode *at* the size the Viewer needs, not at source size (this is the
  single largest playback win for high-resolution or high-bitrate media)
- Optional proxy substitution for sources that are too heavy to decode live
- RGB uint8 output ready for ``QImage.Format_RGB888``
- Quiet FFmpeg/OpenCV stderr noise from mid-GOP seeks
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from config.constants import DEFAULT_DECODE_CACHE_FRAMES
from core.audio import AudioData
from core.perf.profiler import profiler
from core.perf.scheduler import JobPriority, get_scheduler

# Must be set before the first OpenCV/FFmpeg capture is created.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")  # AV_LOG_FATAL
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")

import cv2
from render.audio_decoder import AudioDecoder, AudioInfo

# Prefer sequential decode over hard seeks within this many frames.
_MAX_FORWARD_GRABS: int = 48
_SEEK_READ_RETRIES: int = 3

_CAPTURE_LOCK = threading.RLock()
_LOGGING_CONFIGURED = False

# Global performance knobs, pushed from Preferences via the setters below.
# Kept module-level (rather than per-instance constructor args) so every
# VideoInput node's decoder picks up a preference change immediately,
# without the node graph needing to know about the preference system.
_DECODE_CACHE_FRAMES: int = DEFAULT_DECODE_CACHE_FRAMES
_HARDWARE_DECODE_ENABLED: bool = False

#: Whether verified editing proxies may be substituted for originals.
_PROXY_ENABLED: bool = True

#: Decoder thread count. ``0`` leaves the choice to FFmpeg's own default,
#: which is derived from the machine's core count and is usually right.
_DECODE_THREADS: int = 0

#: Ceiling on the width a decoder is allowed to emit, regardless of source.
#: ``0`` means unbounded. This is the safety valve for extremely large
#: sources (8K, screen recordings) where even "full quality" is not a
#: realistic ask.
_MAX_DECODE_WIDTH: int = 0

#: Smallest width worth asking the decoder for. Below this the box filter
#: discards so much detail that the result is not a preview of the source,
#: so the request is refused and full resolution is decoded instead.
_MIN_DECODE_WIDTH: int = 64


def set_decode_threads(thread_count: int) -> None:
    """Set the decoder thread count for newly opened media.

    Side effects:
        Takes effect the next time a ``VideoDecoder`` opens a file.
    """
    global _DECODE_THREADS
    _DECODE_THREADS = max(0, int(thread_count))


def set_max_decode_width(width: int) -> None:
    """Set the global ceiling on decoded frame width (``0`` = unbounded)."""
    global _MAX_DECODE_WIDTH
    _MAX_DECODE_WIDTH = max(0, int(width))


def _even(value: int) -> int:
    """Round ``value`` down to an even number, with a floor of 2.

    Codec and scaler paths are frequently written for even dimensions
    (chroma is subsampled 2:1), so an odd request can be silently rounded
    by the backend anyway. Doing it here keeps the value the decoder
    reports back equal to the value we asked for.
    """
    value = int(value)
    if value <= 2:
        return 2
    return value - (value % 2)


def set_proxy_enabled(enabled: bool) -> None:
    """Enable or disable editing-proxy substitution for newly opened media.

    Already-open captures keep whatever they opened with; the change takes
    effect the next time a ``VideoDecoder`` opens a file.
    """
    global _PROXY_ENABLED
    _PROXY_ENABLED = bool(enabled)


def _kernels():
    """Return the frame kernel set, preferring the native implementation.

    Imported lazily so a missing/broken extension can never stop this module
    from importing, and so the probe happens on first decode rather than at
    application start.
    """
    from core.native import kernels

    return kernels()

# ----------------------------------------------------------------
# Media metadata cache (Section 58: never re-probe an unchanged file)
# ----------------------------------------------------------------

_PROBE_CACHE_LIMIT: int = 256
_PROBE_TIMEOUT_SECONDS: float = 20.0
_PROBE_CACHE: "OrderedDict[tuple[str, int, int], MediaInfo]" = OrderedDict()
_PROBE_FAILURES: set[tuple[str, int, int]] = set()
_PROBE_CACHE_LOCK = threading.Lock()


def _probe_cache_key(path: str) -> tuple[str, int, int] | None:
    """Return ``(canonical_path, size, mtime_ns)`` or ``None`` if unknown."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.normcase(os.path.abspath(path)), int(stat.st_size), int(stat.st_mtime_ns))


def set_decode_cache_frames(frame_count: int) -> None:
    """Set how many full-resolution decoded frames each decoder retains.

    A larger LRU avoids re-seeking/re-decoding when a user scrubs back over
    recently visited source frames, or when a downstream (non-source) node
    property changes and invalidates only the node-output cache. Cost is
    O(frame_count) full-resolution frames of RAM per open Video Input node.
    """
    global _DECODE_CACHE_FRAMES
    _DECODE_CACHE_FRAMES = max(1, int(frame_count))


def set_hardware_decode_enabled(enabled: bool) -> None:
    """Toggle best-effort hardware-accelerated decode for newly opened media.

    Side effects:
        Takes effect the next time a ``VideoDecoder`` opens a file; already
        open captures are unaffected until re-opened.
    """
    global _HARDWARE_DECODE_ENABLED
    _HARDWARE_DECODE_ENABLED = bool(enabled)


def _configure_decoder_logging() -> None:
    """Mute noisy libav/OpenCV decode warnings (mid-GOP seeks, etc.)."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True

    try:
        cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass


_configure_decoder_logging()


def _apply_decode_threads(capture: cv2.VideoCapture, threads: int) -> None:
    """Set the decoder thread count on a fresh capture.

    ``CAP_PROP_N_THREADS`` is the only thread knob OpenCV exposes for the
    FFmpeg backend, and it must be set before the first frame is read. Some
    builds do not expose it at all and returning ``False`` is normal, so the
    result is deliberately not checked — this is a throughput hint, never a
    correctness requirement, and FFmpeg's own default (derived from the
    core count) is already reasonable.
    """
    count = int(threads) if int(threads) > 0 else _DECODE_THREADS
    if count <= 0:
        return
    try:
        capture.set(cv2.CAP_PROP_N_THREADS, float(count))
    except Exception:  # noqa: BLE001 - unsupported property on some builds
        pass


def _try_enable_hardware_acceleration(capture: cv2.VideoCapture) -> None:
    """Best-effort request for hardware-accelerated decode.

    Not every OpenCV build exposes ``CAP_PROP_HW_ACCELERATION`` and not every
    platform has a working backend, so failures are silently ignored and
    decode falls back to software — this is strictly an opt-in speed hint,
    never a correctness requirement.
    """
    accel_flag = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)
    accel_any = getattr(cv2, "VIDEO_ACCELERATION_ANY", None)
    if accel_flag is None or accel_any is None:
        return
    try:
        capture.set(accel_flag, accel_any)
    except Exception:  # noqa: BLE001
        pass


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Lightweight media metadata used to sync the project timeline."""

    fps: float
    duration_sec: float
    width: int
    height: int
    frame_count: int
    has_audio: bool = False
    audio_sample_rate: int = 48000
    audio_channels: int = 2


class VideoDecoder:
    """Stateful decoder optimized for scrub + forward playback."""

    def __init__(self) -> None:
        self._capture: cv2.VideoCapture | None = None
        self._path: str | None = None
        #: Original media path; differs from ``_path`` when a proxy is used.
        self._source_path: str | None = None
        #: Proxy actually being decoded, when one is in use.
        self._proxy_path: str | None = None
        #: Cached keyframe index for the source, when one has been built.
        self._keyframes = None
        self._fps: float = 30.0
        self._frame_count: int = 0
        self._width: int = 0
        self._height: int = 0
        self._next_index: int = 0

        # ---- Decode-time scaling ------------------------------------
        # The dimensions the *codec* actually holds. ``_width``/``_height``
        # describe the media and are what the timeline and project see;
        # these describe the pixels coming out of ``capture.read()``, which
        # can be smaller when the decoder is asked to scale.
        self._native_width: int = 0
        self._native_height: int = 0
        #: Size the capture is currently configured to emit.
        self._capture_width: int = 0
        self._capture_height: int = 0
        #: Cleared once the backend proves it will not honour a resize.
        self._decode_scale_supported: bool = True
        #: Requested decode quality, pushed in by the owning node.
        #: ``None`` means "choose from the requested output width".
        self._quality_scale: float | None = None
        #: Explicit cap on decoded width (``0`` = none).
        self._decode_width_cap: int = 0
        self._decode_threads: int = 0
        #: Set when the decoder's own notion of its position is stale —
        #: after a size change, the stream is reshaped and the next read
        #: must re-seek instead of trusting ``_next_index``.
        self._force_seek: bool = False

        # Bounded LRU of decoded frames, keyed by ``(frame, output_width)``.
        # Entries are stored *already at that width*, so a cache hit costs
        # nothing but a dict lookup.
        self._frame_cache: OrderedDict[int, np.ndarray] = OrderedDict()
        # Audio decoder for extracting audio from video files
        self._audio_decoder: AudioDecoder = AudioDecoder()
        self._audio_info: AudioInfo | None = None

    @property
    def path(self) -> str | None:
        """Path currently being decoded (the proxy, when one is in use)."""
        return self._path

    @property
    def source_path(self) -> str | None:
        """Path of the original media, regardless of proxy substitution."""
        return self._source_path

    @property
    def is_proxy(self) -> bool:
        """Whether pixels are coming from a generated editing proxy."""
        return self._proxy_path is not None

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def decode_distance(self, frame_num: int) -> int:
        """Frames needing decode after a keyframe to reach ``frame_num``.

        ``0`` means the frame is a keyframe and is reachable instantly. The
        deadline scheduler uses this to estimate seek cost before starting
        work, instead of discovering it after the fact.
        """
        index = self._keyframes
        if index is None or not index.complete:
            return -1
        return index.decode_distance(frame_num)

    def _adopt_proxy(
        self, path: str, use_proxy: bool | None = None
    ) -> tuple[str, dict[str, object]] | None:
        """Return ``(decode_path, source_meta)`` when a proxy is usable.

        Source metadata is taken from the proxy manifest so the original
        container never has to be re-opened (which would both cost a probe
        and risk a lock-order problem with the capture lock).

        Parameters:
            use_proxy: Per-source override. ``None`` defers to the global
                preference pushed in through :func:`set_proxy_enabled`.
        """
        if use_proxy is not None and not use_proxy:
            return None
        if not _PROXY_ENABLED:
            return None
        try:
            from core.media.proxy import get_proxy_manager

            entry = get_proxy_manager().lookup_with_info(path)
        except Exception:  # noqa: BLE001 - proxies are strictly optional
            return None

        if entry is None:
            return None

        proxy_path, manifest = entry
        return str(proxy_path), manifest

    def set_decode_preferences(
        self,
        *,
        quality_scale: float | None = None,
        width_cap: int = 0,
        threads: int = 0,
    ) -> None:
        """Set how much of the source this decoder is allowed to materialise.

        The single most effective playback control for high-quality media.
        Historically a 4K source feeding a 960-pixel Viewer decoded a full
        3840×2160 BGR frame (~24 MB) and then threw away 94% of it in a
        software resize — every frame, with or without effects. Asking the
        decoder to emit the smaller frame instead moves the scaling inside
        the codec pipeline, where it is far cheaper than a separate pass.

        Parameters:
            quality_scale: Fraction of native resolution to decode, or
                ``None`` to derive the size from the requested output
                width (which is what playback wants).
            width_cap: Hard ceiling on decoded width; ``0`` uses the
                module-level default.
            threads: Decoder threads; ``0`` leaves FFmpeg's default.

        Side effects:
            A change to ``threads`` only takes effect on the next
            :meth:`open`, because it is fixed when the codec context is
            created. Quality changes take effect on the next read, and
            drop the decoded-frame cache, since every entry in it was
            produced under the previous setting.
        """
        quality = None if quality_scale is None else float(quality_scale)
        cap = max(0, int(width_cap))

        if quality != self._quality_scale or cap != self._decode_width_cap:
            # Entries cached at the old quality are still *correct*, but
            # keeping them would make the setting appear not to have taken
            # effect until the cache happened to roll over.
            self._frame_cache.clear()

        self._quality_scale = quality
        self._decode_width_cap = cap
        self._decode_threads = max(0, int(threads))

    def _effective_decode_width(self, max_width: int) -> int:
        """Width the decoder should emit for a request of ``max_width``.

        Returns the native width when no scaling is worth doing, so the
        common "already small enough" case costs nothing.
        """
        native = self._native_width
        if native <= 0:
            return 0

        if self._quality_scale is not None:
            # An explicit quality choice overrides the Viewer width: the
            # user asked for a specific fraction of the source.
            target = int(round(native * self._quality_scale))
        else:
            target = int(max_width) if max_width > 0 else native

        cap = self._decode_width_cap or _MAX_DECODE_WIDTH
        if cap > 0:
            target = min(target, cap)

        # Never ask for more pixels than the source holds.
        target = min(target, native)
        if target >= native:
            return native

        target = _even(target)
        if target < _MIN_DECODE_WIDTH and native >= _MIN_DECODE_WIDTH:
            return native
        return target

    def _ensure_decode_scale(self, target_width: int) -> None:
        """Ask the capture to emit frames at ``target_width``.

        ``target_width`` of ``0`` or of the native width means "full
        resolution", which is also how a previous downscale is undone — a
        decoder left at quarter size after the user moved to Full would
        silently keep serving soft frames.

        Failure is expected on some builds: not every OpenCV/FFmpeg
        combination honours a mid-stream resize. When that happens the
        decoder is marked as unable to scale *once*, and every later call
        is a no-op — software scaling downstream still produces a correct
        frame, just at full decode cost.
        """
        capture = self._capture
        native = self._native_width
        if capture is None or native <= 0 or self._native_height <= 0:
            return
        if not self._decode_scale_supported:
            return

        target_width = max(0, int(target_width))
        desired = target_width if 0 < target_width < native else native
        if desired == self._capture_width:
            return

        if desired == native:
            width, height = native, self._native_height
        else:
            width = _even(desired)
            height = _even(
                int(round(self._native_height * (width / float(native))))
            )

        with profiler.scope("decode_scale"):
            # Both properties are set together: the scaler derives the
            # output geometry from the pair, and setting one alone can
            # leave the capture reporting a size it will not produce.
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

        # The return value is deliberately ignored, and so is
        # ``get(CAP_PROP_FRAME_WIDTH)``: OpenCV's FFmpeg backend answers that
        # getter with the *codec's* width, never the scaler's target, so it
        # reports "no change" even when the resize worked perfectly. The
        # only trustworthy evidence is the geometry of the next frame that
        # comes out, which ``_observe_decoded_size`` checks.
        self._capture_width = width
        self._capture_height = height
        # Reshaping the output restarts the scaler's frame handling, so the
        # decoder's idea of where it is in the stream is no longer valid.
        self._force_seek = True
        self._next_index = -1

    def _observe_decoded_size(self, frame: np.ndarray) -> None:
        """Check that a requested decode scale was actually applied.

        Called on the first frame decoded after a resize request. Because
        OpenCV cannot be asked whether it honoured the request, the answer
        is taken from the frame itself — and if the answer is no, the
        decoder stops asking and lets the software path scale instead.
        Persisting with a request that is being silently dropped would cost
        a ``set()`` call per read and a wrong cache key, without ever
        producing smaller frames.
        """
        if not self._decode_scale_supported:
            return

        wanted = self._capture_width
        if wanted <= 0 or wanted >= self._native_width:
            return

        actual = int(frame.shape[1])
        if actual <= wanted * 1.05:
            # Honoured (the 5% slack absorbs a backend that rounds its
            # output to a codec-friendly size).
            self._capture_width = actual
            self._capture_height = int(frame.shape[0])
            return

        self._decode_scale_supported = False
        self._capture_width = self._native_width
        self._capture_height = self._native_height

    def open(self, path: str, *, use_proxy: bool | None = None) -> MediaInfo | None:
        """Open ``path`` and return media info, or ``None`` on failure.

        When a verified editing proxy exists for ``path`` and proxy use is
        enabled, pixels are read from the proxy while the *source's*
        properties are reported to the timeline. The substitution is
        invisible above this class: frame numbers, frame rate, dimensions,
        and audio all still describe the original media.

        Parameters:
            use_proxy: Per-source override for proxy substitution.
        """
        adopted = self._adopt_proxy(path, use_proxy)
        decode_path = adopted[0] if adopted is not None else path

        with _CAPTURE_LOCK:
            if self._path == decode_path and self._source_path == path and self.is_open:
                return self.info()

            self._close_unlocked()
            capture = cv2.VideoCapture(decode_path, cv2.CAP_FFMPEG)
            _apply_decode_threads(capture, self._decode_threads)
            if _HARDWARE_DECODE_ENABLED:
                _try_enable_hardware_acceleration(capture)
            if not capture.isOpened() and adopted is not None:
                # A broken proxy must never make the media unopenable: fall
                # back to the original file and carry on.
                capture.release()
                adopted = None
                decode_path = path
                capture = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
                _apply_decode_threads(capture, self._decode_threads)
            if not capture.isOpened():
                capture.release()
                return None

            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0.001:
                fps = 30.0
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            # Read the *native* size before anything can change it. These
            # are the codec's real dimensions, and they are what decode
            # scaling is a fraction of.
            native_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            native_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            width, height = native_width, native_height
            if width <= 0 or height <= 0:
                capture.release()
                return None

            if adopted is not None:
                # Prefer the source's own metadata over the proxy's.
                manifest = adopted[1]
                source_width = _manifest_int(manifest, "source_width")
                source_height = _manifest_int(manifest, "source_height")
                source_frames = _manifest_int(manifest, "frame_count")
                source_fps = _manifest_float(manifest, "fps")
                if source_width > 0 and source_height > 0:
                    width, height = source_width, source_height
                if source_frames > 0:
                    frame_count = source_frames
                if source_fps > 0.0:
                    fps = source_fps

            self._capture = capture
            self._path = decode_path
            self._source_path = path
            self._proxy_path = decode_path if adopted is not None else None
            self._fps = fps
            self._frame_count = max(0, frame_count)
            self._width = width
            self._height = height
            self._next_index = 0

            # Decode-time scaling state. The capture currently emits the
            # codec's own size; ``_ensure_decode_scale`` will ask for less
            # on the first read that wants less. A newly opened capture
            # deserves a fresh chance at honouring a resize, so the
            # "unsupported" flag is re-armed per open — it may be a
            # different container, codec, or size this time.
            self._native_width = native_width
            self._native_height = native_height
            self._capture_width = native_width
            self._capture_height = native_height
            self._decode_scale_supported = True
            self._force_seek = False

            self._frame_cache.clear()

            # A keyframe index makes seeks exact instead of probe-and-walk.
            # It is looked up (never built) here so opening media stays fast;
            # building happens on the background scheduler.
            self._keyframes = _lookup_keyframe_index(path, fps)

            # Open audio decoder
            self._audio_info = self._audio_decoder.open(path)

            return self.info()

    def info(self) -> MediaInfo | None:
        if not self.is_open:
            return None
        duration = (
            self._frame_count / self._fps
            if self._frame_count > 0
            else 0.0
        )

        # Get audio info if available
        has_audio = False
        audio_sample_rate = 48000
        audio_channels = 2
        if self._audio_info is not None:
            has_audio = self._audio_info.has_audio
            audio_sample_rate = self._audio_info.sample_rate
            audio_channels = self._audio_info.num_channels

        return MediaInfo(
            fps=self._fps,
            duration_sec=duration,
            width=self._width,
            height=self._height,
            frame_count=self._frame_count,
            has_audio=has_audio,
            audio_sample_rate=audio_sample_rate,
            audio_channels=audio_channels,
        )

    def close(self) -> None:
        with _CAPTURE_LOCK:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._path = None
        self._source_path = None
        self._proxy_path = None
        self._keyframes = None
        self._next_index = 0
        self._native_width = 0
        self._native_height = 0
        self._capture_width = 0
        self._capture_height = 0
        self._decode_scale_supported = True
        self._force_seek = False
        self._frame_cache.clear()
        self._audio_decoder.close()
        self._audio_info = None

    def read_rgb(self, frame_num: int, max_width: int) -> np.ndarray | None:
        """Return an RGB frame at ``frame_num``, optionally proxy-scaled.

        Decode-time scaling
        -------------------
        Before anything is decoded, the capture is asked to emit a frame no
        wider than the caller can use (see ``_ensure_decode_scale``). This
        is the change that makes high-resolution sources usable: without
        it, a 4K source feeding a 960-pixel Viewer materialises a
        3840×2160 BGR frame — roughly 24 MB — and then discards 94% of it
        in a software resize, for every frame, effects or no effects. With
        it the rescale happens inside the codec pipeline and only the small
        frame is ever allocated.

        Representation and caching
        --------------------------
        The cache is keyed by ``(frame, output_width)`` and stores the frame
        *already at that width*. Previously it stored the full-resolution
        RGB frame and re-ran ``cv2.resize`` on every read — including every
        cache **hit**, which is precisely the case playback hits most often
        while prefetching. A cache hit is now a pure dict lookup with no
        pixel work at all.

        Conversion and scaling are fused
        ---------------------------------
        On a miss the decoder produces BGR and needs RGB at (possibly) a
        smaller width. The old path was ``cvtColor`` (full-frame allocation
        + pass) then ``resize`` (second allocation + pass). The kernels in
        ``core.native`` do one of two cheaper things:

        * **no downscale needed** — swap channels *in place* in the buffer
          ``cv2`` already returned, which allocates nothing at all;
        * **downscale needed** — one fused pass writing into the destination,
          eliminating both the intermediate full-resolution RGB frame and
          one full-frame memory pass.

        Both are mathematically identical to what they replace, and the
        pure-Python fallback implements the same contract.

        Which branch runs is decided from the frame the decoder *actually*
        returned, not from the size that was requested, so an honoured
        decode-time scale is never scaled a second time.
        """
        with profiler.scope("decode"):
            with _CAPTURE_LOCK:
                if not self.is_open or self._capture is None:
                    return None

                target = max(0, int(frame_num))
                if self._frame_count > 0:
                    target = min(target, self._frame_count - 1)

                key = (target, int(max_width))
                cached = self._frame_cache.get(key)
                if cached is not None:
                    self._frame_cache.move_to_end(key)
                    return cached

                # Ask the decoder to emit the size we actually need before
                # decoding anything. This is the difference between a 4K
                # source costing a full 4K decode plus a software downscale
                # and costing a small decode: the rescale happens inside
                # the codec pipeline, before the frame is materialised.
                self._ensure_decode_scale(self._effective_decode_width(max_width))

                if not self._position_to(target):
                    return self._held_frame(max_width)

                frame = self._read_bgr_with_retry()
                if frame is None:
                    # Hard seeks into H.264 often fail once; hold last good frame.
                    return self._held_frame(max_width)

                self._observe_decoded_size(frame)
                self._next_index = target + 1
                rgb = self._convert_bgr_to_rgb(frame, max_width)
                if rgb is None:
                    return self._held_frame(max_width)

                self._remember(key, rgb)
                return rgb

    def _convert_bgr_to_rgb(
        self, frame: np.ndarray, max_width: int
    ) -> np.ndarray | None:
        """Convert a decoded BGR frame to RGB at the requested width.

        Order matters, and this order was chosen from measurement rather
        than intuition. On a 4K source scaled to a 960-pixel preview:

        ==========================================  ==========
        ``cvtColor`` at 4K then ``resize``          ~25.9 ms
        fused single-pass native kernel             ~45.0 ms
        **``resize`` first, then convert small**    ~15.2 ms
        ==========================================  ==========

        The first two both touch ~24 MB of pixels that are about to be
        discarded. Scaling first means only the small frame is ever colour
        converted, and the 4K frame is read exactly once. The fused native
        kernel loses because ``cv2.resize`` is SIMD-vectorised and runs
        across every core, while a scalar single-threaded box filter cannot
        keep up — a useful reminder that "native" is not automatically
        faster than a library that has been tuned for twenty years.

        The in-place channel swap is still used, because a small frame the
        resize just allocated is exclusively ours: swapping it costs no
        allocation at all, where ``cvtColor`` would allocate a second copy
        of the result for nothing.
        """
        source_height, source_width = frame.shape[:2]
        target_width = max(0, int(max_width))

        if target_width > 0 and source_width > target_width:
            scale = target_width / float(source_width)
            out_width = max(1, int(round(source_width * scale)))
            out_height = max(1, int(round(source_height * scale)))
            try:
                frame = cv2.resize(
                    frame, (out_width, out_height), interpolation=cv2.INTER_AREA
                )
            except cv2.error:
                return None

        # No scaling left to do: swap channels in place in the buffer we
        # already own (either OpenCV's own, or the resize result). Nothing
        # else references it, so mutating is safe and costs one pass with
        # zero allocation.
        try:
            _kernels().swap_bgr_rgb_inplace(frame)
            return frame
        except Exception:  # noqa: BLE001 - fall back to the library path
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def _remember(self, key: tuple[int, int], rgb: np.ndarray) -> None:
        """Insert ``rgb`` into the bounded LRU, evicting the oldest entry."""
        self._frame_cache[key] = rgb
        self._frame_cache.move_to_end(key)
        while len(self._frame_cache) > max(1, _DECODE_CACHE_FRAMES):
            self._frame_cache.popitem(last=False)

    def clear_frame_cache(self) -> None:
        """Drop the decoded-frame LRU.

        Public because benchmarks need to measure genuinely cold seeks, and
        a private-attribute poke from outside the class is exactly the kind
        of coupling this module should not encourage.
        """
        with _CAPTURE_LOCK:
            self._frame_cache.clear()

    def cache_stats(self) -> dict[str, int]:
        """Return decode-cache counters (entries, capacity, proxy status).

        ``decode_width`` is the size the decoder is currently emitting,
        which is the number to look at when a high-resolution source plays
        slowly: if it equals the native width while the Viewer is a tenth
        of that, the backend refused to scale and is being paid in full.
        """
        return {
            "entries": len(self._frame_cache),
            "capacity": max(1, _DECODE_CACHE_FRAMES),
            "is_proxy": 1 if self._proxy_path else 0,
            "native_width": self._native_width,
            "decode_width": self._capture_width,
            "scale_supported": 1 if self._decode_scale_supported else 0,
        }

    def decode_status(self) -> dict[str, int | bool]:
        """Describe the active decode configuration for diagnostics."""
        return {
            "native_width": self._native_width,
            "native_height": self._native_height,
            "decode_width": self._capture_width,
            "decode_height": self._capture_height,
            "scaled_at_decode": self._capture_width < self._native_width,
            "scale_supported": self._decode_scale_supported,
            "is_proxy": self._proxy_path is not None,
            "quality_scale": self._quality_scale if self._quality_scale is not None else -1.0,
            "width_cap": self._decode_width_cap,
            "threads": self._decode_threads or _DECODE_THREADS,
        }

    def _held_frame(self, max_width: int) -> np.ndarray | None:
        """Return the most recently decoded frame, for held-frame recovery.

        Entries are already stored at a width, so this prefers a frame
        cached at exactly the requested width and otherwise rescales the
        newest entry rather than failing.
        """
        if not self._frame_cache:
            return None

        newest_key = next(reversed(self._frame_cache))
        exact = self._frame_cache.get((newest_key[0], int(max_width)))
        if exact is not None:
            return exact

        _, last_rgb = next(reversed(self._frame_cache.items()))
        return self._scale_rgb(last_rgb, max_width)

    def _read_bgr_with_retry(self) -> np.ndarray | None:
        if self._capture is None:
            return None
        for _ in range(_SEEK_READ_RETRIES):
            ok, bgr = self._capture.read()
            if ok and bgr is not None:
                return bgr
        return None

    def _position_to(self, target: int) -> bool:
        """Seek or advance so the next ``read()`` yields ``target``."""
        if self._capture is None:
            return False

        if self._force_seek:
            # A decode-scale change reshapes the output stream, so the
            # decoder's position is no longer trustworthy — not even the
            # "we are already sitting on the right frame" case. Clear the
            # flag and fall through to a real seek.
            self._force_seek = False
        elif target == self._next_index:
            return True
        else:
            forward_gap = target - self._next_index
            if 0 < forward_gap <= _MAX_FORWARD_GRABS:
                for _ in range(forward_gap):
                    if not self._capture.grab():
                        return False
                self._next_index = target
                return True

        # --------------------------------------------------------------
        # Precise seek using the keyframe index when one is available.
        #
        # Without an index this has to seek, read back where the decoder
        # actually landed, then walk forward towards the target — a probe
        # loop whose length depends on the GOP structure it is discovering.
        # With an index we already know the keyframe that starts the target
        # GOP, so we can seek straight to it and count the remaining frames
        # without guessing.
        # --------------------------------------------------------------
        seek_target = target
        index = self._keyframes
        if index is not None and index.complete:
            seek_target = index.nearest_before(target)

        time_ms = (seek_target / max(self._fps, 0.001)) * 1000.0
        with profiler.scope("seek"):
            seeked = self._capture.set(cv2.CAP_PROP_POS_MSEC, time_ms)
            if not seeked:
                seeked = self._capture.set(
                    cv2.CAP_PROP_POS_FRAMES, float(seek_target))
        if not seeked:
            return False

        # After a hard seek, reported position can be a nearby keyframe.
        reported = int(self._capture.get(
            cv2.CAP_PROP_POS_FRAMES) or seek_target)
        self._next_index = max(0, reported)

        remaining = target - self._next_index
        if remaining <= 0:
            return True

        # A known GOP lets us cap the walk; an unknown one falls back to the
        # historical heuristic rather than risking a very long grab loop.
        horizon = _MAX_FORWARD_GRABS
        if index is not None and index.complete:
            horizon = max(_MAX_FORWARD_GRABS, remaining)

        for _ in range(min(remaining, horizon)):
            if not self._capture.grab():
                break
            self._next_index += 1
        return True

    @staticmethod
    def _scale_rgb(rgb: np.ndarray, max_width: int) -> np.ndarray:
        if max_width <= 0:
            return np.ascontiguousarray(rgb)
        height, width = rgb.shape[:2]
        if width <= max_width:
            return np.ascontiguousarray(rgb)
        scale = max_width / float(width)
        new_w = max(1, int(round(width * scale)))
        new_h = max(1, int(round(height * scale)))
        scaled = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(scaled)

    def read_audio(self, frame_num: int) -> "AudioData | None":
        """Read audio samples for a specific frame."""
        if not self.is_open or self._audio_info is None or not self._audio_info.has_audio:
            duration_per_frame = 1.0 / max(self._fps, 0.001)
            return AudioData.silence(
                duration=duration_per_frame,
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2
            )

        duration_per_frame = 1.0 / max(self._fps, 0.001)
        return self._audio_decoder.extract_audio_for_frame(
            frame_num=frame_num,
            fps=self._fps,
            duration_per_frame=duration_per_frame
        )

    def read_audio_range(self, start_time_sec: float, duration_sec: float) -> "AudioData | None":
        """Read a contiguous audio range by time for smoother preview playback."""
        if not self.is_open or self._audio_info is None or not self._audio_info.has_audio:
            return AudioData.silence(
                duration=max(0.0, float(duration_sec)),
                sample_rate=self._audio_info.sample_rate if self._audio_info else 48000,
                channels=self._audio_info.num_channels if self._audio_info else 2,
            )
        return self._audio_decoder.extract_audio_for_time_range(start_time_sec, duration_sec)


def _lookup_keyframe_index(path: str, fps: float):
    """Return a cached keyframe index for ``path``, or ``None``.

    Deliberately lookup-only: opening media must never block on indexing.
    :func:`prepare_media` queues the build on the background scheduler.
    """
    try:
        from core.media.index import get_keyframe_index_cache

        return get_keyframe_index_cache().cached(path, fps)
    except Exception:  # noqa: BLE001 - indexing is best-effort
        return None


def _manifest_int(manifest: dict[str, object], key: str) -> int:
    """Read an integer from a proxy manifest, tolerating missing/garbage data."""
    try:
        return int(manifest.get(key) or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _manifest_float(manifest: dict[str, object], key: str) -> float:
    """Read a float from a proxy manifest, tolerating missing/garbage data."""
    try:
        return float(manifest.get(key) or 0.0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def prepare_media(
    path: str,
    *,
    fps: float = 0.0,
    frame_count: int = 0,
    generate_proxy: bool = True,
    build_index: bool = True,
) -> None:
    """Queue background proxy generation and keyframe indexing for ``path``.

    Called when media enters a project. It returns immediately: the original
    file is usable straight away, and the two artefacts that make *later*
    interaction fast are produced on the background scheduler, which yields
    to interactive work and pauses entirely during playback.

    Parameters:
        path: Media file to prepare.
        fps: Source frame rate; probed when omitted.
        frame_count: Source frame count; probed when omitted.
        generate_proxy: Queue an editing proxy when none exists.
        build_index: Queue a keyframe index when none exists.
    """
    if not path:
        return

    resolved_fps = float(fps)
    resolved_frames = int(frame_count)

    if resolved_fps <= 0.0 or resolved_frames <= 0:
        info = probe_video(path)
        if info is not None:
            resolved_fps = resolved_fps or info.fps
            resolved_frames = resolved_frames or info.frame_count

    if build_index and resolved_fps > 0.0 and resolved_frames > 0:
        try:
            from core.media.index import get_keyframe_index_cache

            get_keyframe_index_cache().ensure(path, resolved_fps, resolved_frames)
        except Exception:  # noqa: BLE001
            pass

    if generate_proxy:
        try:
            from core.media.proxy import get_proxy_manager

            manager = get_proxy_manager()
            if manager.enabled:
                manager.ensure(path)
        except Exception:  # noqa: BLE001
            pass


def _probe_video_metadata(path: str) -> tuple[float, int, int, int] | None:
    """Return ``(fps, frame_count, width, height)`` or ``None`` on failure."""
    with _CAPTURE_LOCK:
        capture = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            capture.release()
            return None
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0.001:
            fps = 30.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        capture.release()
    if width <= 0 or height <= 0 or frame_count <= 0:
        return None
    return fps, frame_count, width, height


def _probe_audio_metadata(path: str) -> AudioInfo | None:
    """Return audio metadata for ``path`` without retaining decoder state."""
    audio_decoder = AudioDecoder()
    try:
        return audio_decoder.open(path)
    finally:
        audio_decoder.close()


def probe_video(path: str) -> MediaInfo | None:
    """Return metadata for ``path``, reusing a cached result when possible.

    Metadata only changes when the file itself changes, so results are
    keyed by canonical path + size + mtime. Probing runs on the shared
    priority scheduler with the video and audio probes in parallel — the
    old implementation created (and tore down) a fresh
    ``ThreadPoolExecutor`` on every call, which is measurable when a
    project lists many sources.
    """
    key = _probe_cache_key(path)
    if key is not None:
        with _PROBE_CACHE_LOCK:
            cached = _PROBE_CACHE.get(key)
            if cached is not None:
                _PROBE_CACHE.move_to_end(key)
                return cached
            if key in _PROBE_FAILURES:
                return None

    _configure_decoder_logging()

    scheduler = get_scheduler()
    video_future = scheduler.submit(
        _probe_video_metadata,
        path,
        priority=JobPriority.BACKGROUND,
        name="probe-video-metadata",
    )
    audio_future = scheduler.submit(
        _probe_audio_metadata,
        path,
        priority=JobPriority.BACKGROUND,
        name="probe-audio-metadata",
    )

    try:
        video_info = video_future.result(timeout=_PROBE_TIMEOUT_SECONDS)
        audio_info = audio_future.result(timeout=_PROBE_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - probing must never crash the UI
        return None

    if video_info is None:
        if key is not None:
            with _PROBE_CACHE_LOCK:
                _PROBE_FAILURES.add(key)
        return None

    fps, frame_count, width, height = video_info
    has_audio = audio_info.has_audio if audio_info else False
    audio_sample_rate = audio_info.sample_rate if audio_info else 48000
    audio_channels = audio_info.num_channels if audio_info else 2

    info = MediaInfo(
        fps=fps,
        duration_sec=frame_count / fps,
        width=width,
        height=height,
        frame_count=frame_count,
        has_audio=has_audio,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
    )

    if key is not None:
        with _PROBE_CACHE_LOCK:
            _PROBE_CACHE[key] = info
            _PROBE_CACHE.move_to_end(key)
            while len(_PROBE_CACHE) > _PROBE_CACHE_LIMIT:
                _PROBE_CACHE.popitem(last=False)

    return info


def clear_probe_cache() -> None:
    """Drop cached media metadata (used by tests and on project close)."""
    with _PROBE_CACHE_LOCK:
        _PROBE_CACHE.clear()
        _PROBE_FAILURES.clear()


def probe_cache_stats() -> dict[str, int]:
    """Return the number of cached media metadata entries."""
    with _PROBE_CACHE_LOCK:
        return {"entries": len(_PROBE_CACHE), "failures": len(_PROBE_FAILURES)}
