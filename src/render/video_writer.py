"""Ultra-high-throughput H.264 MP4 writer.

Optimized for video-editor export workloads.

Key optimizations:

- Dedicated FFmpeg encoder thread.
- Direct memoryview frame writes.
- No ndarray.tobytes() allocation in the video hot path.
- Batched audio WAV writes.
- Minimal Python work per video frame.
- Optional hardware H.264 encoding.
- Automatic hardware encoder detection.
- CPU x264 fallback.
- No stderr PIPE deadlocks.
- Video encoded exactly once.
- Audio mux uses video stream copy.
- Atomic final output replacement.
"""

from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time
import wave
from enum import Enum, auto
from pathlib import Path
from types import TracebackType

import imageio_ffmpeg
import numpy as np
from core.audio import AudioData, convert_audio, frame_sample_bounds

from render.audio_playback import _resample_audio
from render.resource_limits import codec_threads, queue_capacity
from utils.logging_setup import get_logger

_LOG = get_logger('render.encoder')

# ============================================================================
# Export quality
# ============================================================================


class ExportQuality(Enum):
    DRAFT = auto()
    FAST = auto()
    BALANCED = auto()
    HIGH_QUALITY = auto()


_EXPORT_PROFILE_SETTINGS: dict[
    ExportQuality,
    tuple[str, int],
] = {
    ExportQuality.DRAFT: ("ultrafast", 28),
    ExportQuality.FAST: ("ultrafast", 23),
    ExportQuality.BALANCED: ("veryfast", 20),
    ExportQuality.HIGH_QUALITY: ("medium", 18),
}

# Hardware encoders expose their own preset vocabularies. Mapping the
# shared ExportQuality enum onto each one means the quality slider keeps
# meaning something after AUTO selects a GPU encoder, instead of always
# pinning NVENC to "p1" and QSV to "veryfast".
_HW_PRESET_SETTINGS: dict[
    str,
    dict[ExportQuality, str],
] = {
    "h264_nvenc": {
        ExportQuality.DRAFT: "p1",
        ExportQuality.FAST: "p3",
        ExportQuality.BALANCED: "p5",
        ExportQuality.HIGH_QUALITY: "p7",
    },
    "h264_qsv": {
        ExportQuality.DRAFT: "veryfast",
        ExportQuality.FAST: "veryfast",
        ExportQuality.BALANCED: "faster",
        ExportQuality.HIGH_QUALITY: "medium",
    },
    "h264_amf": {
        ExportQuality.DRAFT: "speed",
        ExportQuality.FAST: "speed",
        ExportQuality.BALANCED: "balanced",
        ExportQuality.HIGH_QUALITY: "quality",
    },
}


def _hw_preset(
    encoder: str,
    quality: ExportQuality,
    fallback: str,
) -> str:
    """Return the hardware-encoder preset for ``quality``."""
    return _HW_PRESET_SETTINGS.get(encoder, {}).get(quality, fallback)


# How many decoded/encoded frames the writer may buffer ahead of FFmpeg.
# A deeper queue hides encoder hiccups and keeps the evaluator feeling
# serial, which matters most for long exports.
_DEFAULT_QUEUE_SIZE: int = 32


# ============================================================================
# Encoder configuration
# ============================================================================


class VideoEncoder(Enum):
    AUTO = auto()
    CPU = auto()
    INTEL_QSV = auto()
    NVIDIA_NVENC = auto()
    AMD_AMF = auto()


_ENCODER_CACHE: dict[str, dict[str, bool]] = {}
_ENCODER_CACHE_LOCK = threading.Lock()


def _detect_encoders(
    ffmpeg_exe: str,
) -> dict[str, bool]:
    """Probe actual encode sessions; compiled-in support is not a device."""

    global _ENCODER_CACHE

    with _ENCODER_CACHE_LOCK:
        if ffmpeg_exe in _ENCODER_CACHE:
            return _ENCODER_CACHE[ffmpeg_exe].copy()

        result: dict[str, bool] = {
            "h264_qsv": False,
            "h264_nvenc": False,
            "h264_amf": False,
        }

        try:
            completed = subprocess.run(
                (
                    ffmpeg_exe,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-encoders",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )

            text = completed.stdout.decode(
                "utf-8",
                errors="ignore",
            )

            for encoder in result:
                if encoder not in text:
                    continue
                try:
                    trial = subprocess.run(
                        [
                            ffmpeg_exe,
                            "-v",
                            "error",
                            "-nostdin",
                            "-f",
                            "lavfi",
                            "-i",
                            "color=size=128x128:rate=30",
                            "-frames:v",
                            "1",
                            "-c:v",
                            encoder,
                            "-pix_fmt",
                            "yuv420p",
                            "-f",
                            "null",
                            "-",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        timeout=10,
                    )
                    result[encoder] = trial.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    result[encoder] = False

        except Exception:
            pass

        _ENCODER_CACHE[ffmpeg_exe] = result
        return result.copy()


def _select_encoder(
    ffmpeg_exe: str,
    requested: VideoEncoder,
) -> str:
    """Select an H.264 encoder."""

    if requested == VideoEncoder.CPU:
        return "libx264"

    encoders = _detect_encoders(
        ffmpeg_exe,
    )

    if requested == VideoEncoder.INTEL_QSV:
        if not encoders["h264_qsv"]:
            raise RuntimeError(
                "Intel QSV H.264 encoder is unavailable in the bundled FFmpeg."
            )

        return "h264_qsv"

    if requested == VideoEncoder.NVIDIA_NVENC:
        if not encoders["h264_nvenc"]:
            raise RuntimeError(
                "NVIDIA NVENC H.264 encoder is unavailable in the bundled FFmpeg."
            )

        return "h264_nvenc"

    if requested == VideoEncoder.AMD_AMF:
        if not encoders["h264_amf"]:
            raise RuntimeError(
                "AMD AMF H.264 encoder is unavailable in the bundled FFmpeg."
            )

        return "h264_amf"

    # AUTO:
    #
    # Prefer hardware encoding.
    #
    # Intel is checked first because integrated Intel GPUs are extremely
    # common in laptops and QSV generally has excellent H.264 throughput.
    if encoders["h264_qsv"]:
        return "h264_qsv"

    if encoders["h264_nvenc"]:
        return "h264_nvenc"

    if encoders["h264_amf"]:
        return "h264_amf"

    return "libx264"


# ============================================================================
# Sentinel
# ============================================================================


class _EndOfFrames:
    __slots__ = ()


_END = _EndOfFrames()


# ============================================================================
# Writer
# ============================================================================


class Mp4VideoWriter:
    """Ultra-high-throughput RGB -> H.264 MP4 writer."""

    __slots__ = (
        "_audio_buffer",
        "_audio_buffer_bytes",
        "_audio_channels",
        "_audio_flush_bytes",
        "_audio_lock",
        "_audio_sample_rate",
        "_audio_wav_path",
        "_audio_wave",
        "_closed",
        "_encoded_height",
        "_encoded_width",
        "_encoder",
        "_encoder_thread",
        "_ffmpeg_exe",
        "_fps",
        "_frame_count",
        "_frame_queue",
        "_height",
        "_include_audio",
        "_native_encoder",
        "_pipe_write_started",
        "_watchdog_stop",
        "_watchdog_thread",
        "_output_path",
        "_pad_bottom",
        "_pad_right",
        "_process",
        "_quality",
        "_stderr_file",
        "_temp_video_path",
        "_width",
        "_write_error",
    )

    def __init__(
        self,
        output_path: Path,
        *,
        fps: float,
        width: int,
        height: int,
        audio_sample_rate: int = 48000,
        audio_channels: int = 2,
        include_audio: bool = True,
        quality: ExportQuality = ExportQuality.FAST,
        queue_size: int = _DEFAULT_QUEUE_SIZE,
        encoder: VideoEncoder = VideoEncoder.AUTO,
        memory_budget_bytes: int = 64 * 1024 * 1024,
        backend: str = "auto",
    ) -> None:
        from core.native import require_available

        require_available()
        output_path = Path(output_path)

        width = int(width)
        height = int(height)
        fps = float(fps)

        if width <= 0 or height <= 0:
            raise ValueError(f"Video dimensions must be positive, got {width}x{height}")

        if not np.isfinite(fps) or fps <= 0.0:
            raise ValueError(f"FPS must be positive, got {fps!r}")
        if backend not in ("auto", "pipe", "libav"):
            raise ValueError(f"Unknown encoder backend: {backend}")

        self._output_path = output_path

        self._width = width
        self._height = height
        self._fps = fps

        # yuv420p requires even dimensions.
        self._pad_right = width & 1
        self._pad_bottom = height & 1

        self._encoded_width = width + self._pad_right
        self._encoded_height = height + self._pad_bottom
        capacity = queue_capacity(self._encoded_width * self._encoded_height * 3,
                                  queue_size, memory_budget_bytes)

        self._audio_sample_rate = max(
            1,
            int(audio_sample_rate),
        )

        channels = int(audio_channels)
        self._audio_channels = 1 if channels == 1 else 2

        self._include_audio = bool(include_audio)

        self._quality = quality

        self._closed = False
        self._frame_count = 0
        self._write_error: BaseException | None = None

        # ==================================================================
        # Audio buffering
        # ==================================================================

        self._audio_wav_path: str | None = None
        self._audio_wave: wave.Wave_write | None = None

        self._audio_lock = threading.Lock()

        # Instead of calling wave.writeframes() once per video frame,
        # accumulate PCM and write larger blocks.
        #
        # This matters when rendering thousands of frames.
        self._audio_buffer = bytearray()

        # Flush around 1 MiB at a time.
        self._audio_flush_bytes = 1024 * 1024
        self._audio_buffer_bytes = 0

        # ==================================================================
        # Temporary video
        # ==================================================================

        self._ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        # ==================================================================
        # Encoder selection
        # ==================================================================

        self._encoder = _select_encoder(
            self._ffmpeg_exe,
            encoder,
        )
        self._temp_video_path = self._make_temp_video_path()
        _LOG.info('Opening encoder=%s resolution=%dx%d fps=%g queue=%d threads=%d',
                  self._encoder,self._encoded_width,self._encoded_height,self._fps,capacity,codec_threads())

        preset, crf = _EXPORT_PROFILE_SETTINGS.get(
            quality,
            _EXPORT_PROFILE_SETTINGS[ExportQuality.FAST],
        )

        # ==================================================================
        # FFmpeg command
        # ==================================================================

        cmd = [
            self._ffmpeg_exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-filter_threads",
            str(codec_threads()),
            # --------------------------------------------------------------
            # Raw RGB input
            # --------------------------------------------------------------
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{self._encoded_width}x{self._encoded_height}",
            "-framerate",
            f"{self._fps:.12g}",
            "-i",
            "-",
            # --------------------------------------------------------------
            # Video only
            # --------------------------------------------------------------
            "-an",
            "-c:v",
            self._encoder,
        ]

        # --------------------------------------------------------------
        # CPU x264
        # --------------------------------------------------------------

        if self._encoder == "libx264":
            cmd.extend(
                (
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    # Let x264 determine optimal thread count.
                    "-threads",
                    str(codec_threads()),
                )
            )

            if quality == ExportQuality.DRAFT:
                cmd.extend(
                    (
                        "-tune",
                        "zerolatency",
                    )
                )

        # --------------------------------------------------------------
        # Intel Quick Sync
        # --------------------------------------------------------------

        elif self._encoder == "h264_qsv":
            # QSV's rate-control parameters differ from x264's CRF.
            #
            # CQP is extremely fast and predictable.
            cmd.extend(
                (
                    "-async_depth",
                    "1",
                    "-preset",
                    _hw_preset(self._encoder, quality, "veryfast"),
                    "-global_quality",
                    str(
                        max(
                            1,
                            min(51, crf),
                        )
                    ),
                )
            )

        # --------------------------------------------------------------
        # NVIDIA NVENC
        # --------------------------------------------------------------

        elif self._encoder == "h264_nvenc":
            qp = str(
                max(
                    1,
                    min(51, crf),
                )
            )
            cmd.extend(
                (
                    "-surfaces",
                    "4",
                    "-delay",
                    "0",
                    "-preset",
                    _hw_preset(self._encoder, quality, "p3"),
                    "-rc",
                    "constqp",
                    "-qp",
                    qp,
                    # Keep latency low without reordering frames, which
                    # keeps encode throughput predictable for exports.
                    "-zerolatency",
                    "1",
                )
            )

        # --------------------------------------------------------------
        # AMD AMF
        # --------------------------------------------------------------

        elif self._encoder == "h264_amf":
            qp = str(
                max(
                    1,
                    min(51, crf),
                )
            )
            cmd.extend(
                (
                    "-quality",
                    _hw_preset(self._encoder, quality, "speed"),
                    "-rc",
                    "cqp",
                    "-qp_i",
                    qp,
                    "-qp_p",
                    qp,
                )
            )

        cmd.extend(
            (
                # Broad MP4 compatibility.
                "-pix_fmt",
                "yuv420p" if self._encoder == "libx264" else "nv12",
            )
        )

        # ``+faststart`` relocates the moov atom, which requires rewriting
        # the whole file. When audio is muxed afterwards the temporary
        # video is copied into the final container anyway, so paying for a
        # second pass over a multi-gigabyte file is pure waste — the mux
        # step applies faststart to the real output instead.
        if not self._include_audio:
            cmd.extend(
                (
                    "-movflags",
                    "+faststart",
                )
            )

        cmd.append(str(self._temp_video_path))

        # ==================================================================
        # FFmpeg stderr
        # ==================================================================

        self._stderr_file = tempfile.TemporaryFile(
            mode="w+b",
        )
        self._native_encoder = None
        self._process = None
        try:
            if backend != "pipe" and self._encoder == "libx264":
                try:
                    from render.libav_encoder import LibavEncoder

                    self._native_encoder = LibavEncoder(
                        self._temp_video_path,
                        width=self._encoded_width,
                        height=self._encoded_height,
                        fps=self._fps,
                        preset=preset,
                        crf=crf,
                    )
                except ImportError:
                    if backend == "libav":
                        raise
            if self._native_encoder is None:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=self._stderr_file,
                    bufsize=0,
                )

        except Exception:
            self._stderr_file.close()
            self._cleanup_temp_video()
            raise

        if self._process is not None and self._process.stdin is None:
            try:
                self._process.kill()
            except Exception:
                pass

            self._stderr_file.close()
            self._cleanup_temp_video()

            raise RuntimeError("Failed to open FFmpeg stdin")

        # ==================================================================
        # Frame queue
        # ==================================================================

        self._frame_queue: queue.Queue[np.ndarray | _EndOfFrames] = queue.Queue(
            maxsize=capacity
        )

        self._encoder_thread = threading.Thread(
            target=self._encoder_worker,
            name="Mp4VideoEncoder",
            daemon=True,
        )

        self._pipe_write_started = 0.0
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = None
        if self._process is not None:
            self._watchdog_thread = threading.Thread(target=self._watch_encoder,
                                                     name='EncoderWatchdog',daemon=True)
            self._watchdog_thread.start()

        self._encoder_thread.start()

    def _watch_encoder(self) -> None:
        while not self._watchdog_stop.wait(.25):
            started = self._pipe_write_started
            if started and time.monotonic() - started > 15:
                _LOG.error('Encoder stalled: backend=%s resolution=%dx%d; stopping child process',
                           self._encoder,self._encoded_width,self._encoded_height)
                self._write_error = TimeoutError('Encoder stopped accepting frames for 15 seconds')
                self.cancel_pending()
                return

    # ======================================================================
    # Temporary files
    # ======================================================================

    def _make_temp_video_path(self) -> Path:
        self._output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fd, path = tempfile.mkstemp(
            prefix=f".{self._output_path.stem}.",
            suffix=".video.mp4",
            dir=str(self._output_path.parent),
        )

        os.close(fd)

        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

        return Path(path)

    def _cleanup_temp_video(self) -> None:
        if self._temp_video_path != self._output_path:
            self._temp_video_path.unlink(
                missing_ok=True,
            )

    # ======================================================================
    # Diagnostics
    # ======================================================================

    def _read_ffmpeg_error(self) -> str:
        try:
            self._stderr_file.flush()
            self._stderr_file.seek(0)

            data = self._stderr_file.read()

            if not data:
                return ""

            return data.decode(
                "utf-8",
                errors="replace",
            ).strip()

        except Exception:
            return ""

    # ======================================================================
    # Frame preparation
    # ======================================================================

    def _prepare_frame(
        self,
        frame: np.ndarray,
    ) -> np.ndarray:
        """Validate RGB frame and make it queue-safe."""

        if not isinstance(
            frame,
            np.ndarray,
        ):
            frame = np.asarray(frame)

        # Fast validation.
        if frame.dtype != np.uint8:
            raise TypeError(f"Video frames must be uint8, got {frame.dtype}")

        if (
            frame.ndim != 3
            or frame.shape[0] != self._height
            or frame.shape[1] != self._width
            or frame.shape[2] != 3
        ):
            raise ValueError(
                "Invalid frame shape: expected "
                f"({self._height}, "
                f"{self._width}, 3), "
                f"got {frame.shape}"
            )

        # ==============================================================
        # HOT PATH
        #
        # This should be the overwhelmingly common case.
        # ==============================================================

        if not self._pad_right and not self._pad_bottom and frame.flags.c_contiguous:
            # An SDK node may reuse its output array on the next evaluation.
            # The asynchronous queue must own a stable snapshot; libav still
            # reads this owned NumPy buffer directly without another RGB copy.
            return frame.copy()

        if not self._pad_right and not self._pad_bottom:
            return np.ascontiguousarray(
                frame,
            )

        # ==============================================================
        # Odd dimensions.
        # ==============================================================

        padded = np.empty(
            (
                self._encoded_height,
                self._encoded_width,
                3,
            ),
            dtype=np.uint8,
        )

        padded[
            : self._height,
            : self._width,
        ] = frame

        if self._pad_right:
            padded[
                : self._height,
                self._width :,
            ] = frame[
                :,
                -1:,
                :,
            ]

        if self._pad_bottom:
            padded[
                self._height :,
                :,
            ] = padded[
                self._height - 1 : self._height,
                :,
            ]

        return padded

    # ======================================================================
    # Encoder thread
    # ======================================================================

    def _encoder_worker(self) -> None:
        """Continuously feed frames into FFmpeg."""

        if self._native_encoder is not None:
            self._libav_worker()
            return

        process = self._process
        stdin = process.stdin
        frame_queue = self._frame_queue

        if stdin is None:
            self._write_error = RuntimeError("FFmpeg stdin is unavailable")
            return

        # Local bindings eliminate repeated attribute lookups.
        write = stdin.write
        task_done = frame_queue.task_done
        get = frame_queue.get

        try:
            while True:
                item = get()

                try:
                    if item is _END:
                        return

                    # Direct view over NumPy memory.
                    view = memoryview(item).cast("B")

                    # Usually one write is sufficient, but FileIO is allowed
                    # to perform partial writes.
                    while view:
                        self._pipe_write_started = time.monotonic()
                        written = write(view)
                        self._pipe_write_started = 0.0

                        if written is None:
                            raise BrokenPipeError("FFmpeg stdin write returned None")

                        if written <= 0:
                            raise BrokenPipeError("FFmpeg stdin closed")

                        view = view[written:]

                finally:
                    self._pipe_write_started = 0.0
                    task_done()

        except (
            BrokenPipeError,
            OSError,
        ) as exc:
            error = self._read_ffmpeg_error()

            self._write_error = RuntimeError(
                "FFmpeg stopped accepting frames" + (f": {error}" if error else "")
            )

            self._write_error.__cause__ = exc

            # Drain queue so close() cannot deadlock.
            while True:
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    break

                frame_queue.task_done()

        except BaseException as exc:
            self._write_error = exc

            while True:
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    break

                frame_queue.task_done()

    # ======================================================================
    # Audio
    # ======================================================================

    def _ensure_audio_writer(
        self,
    ) -> wave.Wave_write:
        audio_wave = self._audio_wave

        if audio_wave is not None:
            return audio_wave

        temp = tempfile.NamedTemporaryFile(
            prefix=".ap2-audio-",
            suffix=".wav",
            delete=False,
        )

        path = temp.name
        temp.close()

        audio_wave = wave.open(
            path,
            "wb",
        )

        audio_wave.setnchannels(
            self._audio_channels,
        )

        audio_wave.setsampwidth(2)

        audio_wave.setframerate(
            self._audio_sample_rate,
        )

        self._audio_wav_path = path
        self._audio_wave = audio_wave

        return audio_wave

    def _flush_audio_buffer_locked(
        self,
    ) -> None:
        if not self._audio_buffer:
            return

        audio_wave = self._ensure_audio_writer()

        # memoryview avoids an intermediate bytes copy.
        audio_wave.writeframes(memoryview(self._audio_buffer))

        self._audio_buffer.clear()
        self._audio_buffer_bytes = 0

    def _prepare_audio(
        self,
        audio: AudioData,
    ) -> np.ndarray:
        source = np.asarray(
            audio.samples,
        )

        if source.size == 0:
            return np.empty(
                (
                    0,
                    self._audio_channels,
                ),
                dtype=np.int16,
            )

        if source.ndim == 1:
            source = source.reshape(
                -1,
                1,
            )

        elif source.ndim != 2:
            raise ValueError(f"Audio samples must be 1D or 2D, got {source.shape}")

        samples = source.astype(
            np.float32,
            copy=False,
        )

        channels = samples.shape[1]

        # ==============================================================
        # Channel conversion.
        # ==============================================================

        if channels > self._audio_channels:
            samples = samples[
                :,
                : self._audio_channels,
            ]

        elif channels < self._audio_channels:
            if channels == 1 and self._audio_channels == 2:
                samples = np.repeat(
                    samples,
                    2,
                    axis=1,
                )

            else:
                padding = np.zeros(
                    (
                        samples.shape[0],
                        self._audio_channels - channels,
                    ),
                    dtype=np.float32,
                )

                samples = np.concatenate(
                    (
                        samples,
                        padding,
                    ),
                    axis=1,
                )

        # ==============================================================
        # Resample only when necessary.
        # ==============================================================

        source_rate = int(
            audio.sample_rate,
        )

        if source_rate <= 0:
            raise ValueError(f"Invalid audio sample rate: {source_rate}")

        if source_rate != self._audio_sample_rate:
            samples = _resample_audio(
                samples,
                source_rate,
                self._audio_sample_rate,
            )

            if samples.dtype != np.float32:
                samples = samples.astype(
                    np.float32,
                    copy=False,
                )

        # ==============================================================
        # Float -> signed 16-bit PCM.
        #
        # ``samples`` may alias the caller's ``AudioData.samples`` buffer
        # (``astype`` with ``copy=False`` is a no-op when the source is
        # already float32), so the conversion must never write in place.
        # Doing so used to scale the node's audio by 32767 permanently,
        # corrupting preview playback after an export.
        # ==============================================================

        scaled = np.clip(
            samples,
            -1.0,
            1.0,
        )

        np.multiply(
            scaled,
            32767.0,
            out=scaled,
        )

        return scaled.astype(
            np.int16,
            copy=False,
        )

    # ======================================================================
    # Public write
    # ======================================================================

    def write(
        self,
        frame_rgb: np.ndarray,
        audio: AudioData | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("Cannot write to a closed Mp4VideoWriter")

        write_error = self._write_error

        if write_error is not None:
            raise RuntimeError("FFmpeg encoder failed") from write_error

        # ==============================================================
        # VIDEO
        # ==============================================================

        frame = self._prepare_frame(
            frame_rgb,
        )

        # Prepared storage belongs to the queue; callers may reuse their array.
        # Polling also observes an encoder that dies while backpressure applies.
        self._enqueue(frame)

        # ==============================================================
        # AUDIO
        #
        # Accumulate PCM rather than touching the WAV object on every
        # frame.
        # ==============================================================

        if self._include_audio:
            first, last = frame_sample_bounds(
                self._frame_count, self._fps, self._audio_sample_rate
            )
            block = convert_audio(
                audio, self._audio_sample_rate, self._audio_channels, last - first
            )
            audio_pcm = self._prepare_audio(block)

            if audio_pcm.size:
                with self._audio_lock:
                    # Extend from the NumPy buffer without calling
                    # .tobytes() explicitly.
                    self._audio_buffer.extend(memoryview(audio_pcm).cast("B"))

                    self._audio_buffer_bytes = len(self._audio_buffer)

                    if self._audio_buffer_bytes >= self._audio_flush_bytes:
                        self._flush_audio_buffer_locked()

        self._frame_count += 1

    def write_video_only(
        self,
        frame_rgb: np.ndarray,
    ) -> None:
        self.write(
            frame_rgb,
        )

    def _enqueue(self, item: np.ndarray | _EndOfFrames) -> None:
        while True:
            if self._write_error is not None or not self._encoder_thread.is_alive():
                raise RuntimeError("FFmpeg encoder stopped") from self._write_error
            try:
                self._frame_queue.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    def abort(self) -> None:
        """Discard an unfinished export and unblock a pending pipe write."""
        if self._closed:
            return
        self._closed = True
        self.cancel_pending()
        self._watchdog_stop.set()
        if self._process is not None:
            self._process.wait(timeout=5)
        # Wake an encoder waiting for a frame rather than inside write().
        try:
            self._frame_queue.put_nowait(_END)
        except queue.Full:
            pass
        self._encoder_thread.join(timeout=5)
        if self._process is not None and self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if self._audio_wave is not None:
            self._audio_wave.close()
            self._audio_wave = None
        self._cleanup_audio()
        self._stderr_file.close()
        self._cleanup_temp_video()

    def cancel_pending(self) -> None:
        """Thread-safe request; resource cleanup remains on the owner thread."""
        if self._native_encoder is not None:
            self._native_encoder.cancelled.set()
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.kill()
            except OSError:
                pass

    # ======================================================================
    # Close
    # ======================================================================

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        try:
            # ==============================================================
            # Stop accepting video.
            # ==============================================================

            self._enqueue(_END)
            # Queue.join can deadlock when the consumer fails after draining
            # but before the producer inserts the end marker.
            self._encoder_thread.join(timeout=300)
            if self._encoder_thread.is_alive():
                raise TimeoutError("FFmpeg frame submission timed out")

            # ==============================================================
            # Close FFmpeg stdin.
            # ==============================================================

            stdin = self._process.stdin if self._process is not None else None

            if stdin is not None:
                try:
                    stdin.close()
                except (
                    BrokenPipeError,
                    OSError,
                ):
                    pass

            # ==============================================================
            # Wait for encode.
            # ==============================================================

            return_code = (
                self._process.wait(
                    timeout=300,
                )
                if self._process is not None
                else 0
            )

            stderr = self._read_ffmpeg_error()

            if self._write_error is not None:
                raise RuntimeError(
                    "FFmpeg encoding failed" + (f": {stderr}" if stderr else "")
                ) from self._write_error

            if return_code != 0:
                raise RuntimeError(
                    "FFmpeg video encode failed "
                    f"({return_code})" + (f": {stderr}" if stderr else "")
                )

            # ==============================================================
            # Flush remaining audio.
            # ==============================================================

            with self._audio_lock:
                self._flush_audio_buffer_locked()

                audio_wave = self._audio_wave

                if audio_wave is not None:
                    audio_wave.close()
                    self._audio_wave = None

            # ==============================================================
            # Mux.
            # ==============================================================

            if self._include_audio and self._audio_wav_path is not None:
                self._mux_audio()

            elif self._temp_video_path != self._output_path:
                os.replace(
                    self._temp_video_path,
                    self._output_path,
                )

        finally:
            self._watchdog_stop.set()
            self._cleanup_audio()

            try:
                self._stderr_file.close()
            except Exception:
                pass

            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.kill()
                    self._process.wait(
                        timeout=5,
                    )
                except Exception:
                    pass

            self._cleanup_temp_video()

    # ======================================================================
    # Audio mux
    # ======================================================================

    def _mux_audio(self) -> None:
        audio_path = self._audio_wav_path

        if audio_path is None:
            return

        self._output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self._output_path.stem}.",
            suffix=".muxed.mp4",
            dir=str(self._output_path.parent),
        )

        os.close(fd)

        temp_output = Path(
            temp_path,
        )

        stderr_file = tempfile.TemporaryFile(
            mode="w+b",
        )

        try:
            cmd = [
                self._ffmpeg_exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(self._temp_video_path),
                "-i",
                audio_path,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                # Zero video re-encoding.
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-ar",
                str(self._audio_sample_rate),
                "-ac",
                str(self._audio_channels),
                "-movflags",
                "+faststart",
                str(temp_output),
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                check=False,
                timeout=300,
            )

            if result.returncode != 0:
                stderr_file.flush()
                stderr_file.seek(0)

                error = (
                    stderr_file.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                    .strip()
                )

                raise RuntimeError(
                    "FFmpeg audio mux failed "
                    f"({result.returncode})" + (f": {error}" if error else "")
                )

            os.replace(
                temp_output,
                self._output_path,
            )

            self._temp_video_path.unlink(
                missing_ok=True,
            )

        finally:
            try:
                stderr_file.close()
            except Exception:
                pass

            temp_output.unlink(
                missing_ok=True,
            )

    # ======================================================================
    # Cleanup
    # ======================================================================

    def _cleanup_audio(self) -> None:
        path = self._audio_wav_path

        if path is None:
            return

        try:
            Path(path).unlink(
                missing_ok=True,
            )
        finally:
            self._audio_wav_path = None

    # ======================================================================
    # Context manager
    # ======================================================================

    def __enter__(self) -> Mp4VideoWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.abort()
        else:
            self.close()

    def _libav_worker(self) -> None:
        backend = self._native_encoder
        try:
            while True:
                item = self._frame_queue.get()
                try:
                    if item is _END:
                        backend.close()
                        return
                    backend.write(item)
                finally:
                    self._frame_queue.task_done()
        except BaseException as exc:
            self._write_error = exc
            backend.close(flush=False)
            while True:
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    break
                self._frame_queue.task_done()
