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
import wave
from enum import Enum, auto
from pathlib import Path
from types import TracebackType

import imageio_ffmpeg
import numpy as np

from core.audio import AudioData
from render.audio_playback import _resample_audio


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


# ============================================================================
# Encoder configuration
# ============================================================================


class VideoEncoder(Enum):
    AUTO = auto()
    CPU = auto()
    INTEL_QSV = auto()
    NVIDIA_NVENC = auto()
    AMD_AMF = auto()


_ENCODER_CACHE: dict[str, bool] | None = None
_ENCODER_CACHE_LOCK = threading.Lock()


def _detect_encoders(
    ffmpeg_exe: str,
) -> dict[str, bool]:
    """Detect hardware H.264 encoders exposed by this FFmpeg build."""

    global _ENCODER_CACHE

    with _ENCODER_CACHE_LOCK:
        if _ENCODER_CACHE is not None:
            return _ENCODER_CACHE.copy()

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
                result[encoder] = encoder in text

        except Exception:
            pass

        _ENCODER_CACHE = result
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
                "Intel QSV H.264 encoder is unavailable "
                "in the bundled FFmpeg."
            )

        return "h264_qsv"

    if requested == VideoEncoder.NVIDIA_NVENC:
        if not encoders["h264_nvenc"]:
            raise RuntimeError(
                "NVIDIA NVENC H.264 encoder is unavailable "
                "in the bundled FFmpeg."
            )

        return "h264_nvenc"

    if requested == VideoEncoder.AMD_AMF:
        if not encoders["h264_amf"]:
            raise RuntimeError(
                "AMD AMF H.264 encoder is unavailable "
                "in the bundled FFmpeg."
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
        "_output_path",
        "_width",
        "_height",
        "_fps",
        "_pad_right",
        "_pad_bottom",
        "_encoded_width",
        "_encoded_height",
        "_audio_sample_rate",
        "_audio_channels",
        "_include_audio",
        "_quality",
        "_encoder",
        "_closed",
        "_frame_count",
        "_write_error",
        "_audio_wav_path",
        "_audio_wave",
        "_audio_lock",
        "_audio_buffer",
        "_audio_buffer_bytes",
        "_audio_flush_bytes",
        "_temp_video_path",
        "_ffmpeg_exe",
        "_process",
        "_stderr_file",
        "_frame_queue",
        "_encoder_thread",
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
        queue_size: int = 12,
        encoder: VideoEncoder = VideoEncoder.AUTO,
    ) -> None:
        output_path = Path(output_path)

        width = int(width)
        height = int(height)
        fps = float(fps)

        if width <= 0 or height <= 0:
            raise ValueError(
                f"Video dimensions must be positive, "
                f"got {width}x{height}"
            )

        if not np.isfinite(fps) or fps <= 0.0:
            raise ValueError(
                f"FPS must be positive, got {fps!r}"
            )

        self._output_path = output_path

        self._width = width
        self._height = height
        self._fps = fps

        # yuv420p requires even dimensions.
        self._pad_right = width & 1
        self._pad_bottom = height & 1

        self._encoded_width = width + self._pad_right
        self._encoded_height = height + self._pad_bottom

        self._audio_sample_rate = max(
            1,
            int(audio_sample_rate),
        )

        channels = int(audio_channels)
        self._audio_channels = (
            1 if channels == 1 else 2
        )

        self._include_audio = bool(
            include_audio
        )

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

        self._temp_video_path = (
            self._make_temp_video_path()
            if self._include_audio
            else output_path
        )

        self._ffmpeg_exe = (
            imageio_ffmpeg.get_ffmpeg_exe()
        )

        # ==================================================================
        # Encoder selection
        # ==================================================================

        self._encoder = _select_encoder(
            self._ffmpeg_exe,
            encoder,
        )

        preset, crf = _EXPORT_PROFILE_SETTINGS.get(
            quality,
            _EXPORT_PROFILE_SETTINGS[
                ExportQuality.FAST
            ],
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

            # --------------------------------------------------------------
            # Raw RGB input
            # --------------------------------------------------------------

            "-f",
            "rawvideo",

            "-pixel_format",
            "rgb24",

            "-video_size",
            f"{self._encoded_width}x"
            f"{self._encoded_height}",

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
                    "0",
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
                    "-preset",
                    "veryfast",
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
            cmd.extend(
                (
                    "-preset",
                    "p1",
                    "-tune",
                    "ll",
                    "-rc",
                    "constqp",
                    "-qp",
                    str(
                        max(
                            1,
                            min(51, crf),
                        )
                    ),
                )
            )

        # --------------------------------------------------------------
        # AMD AMF
        # --------------------------------------------------------------

        elif self._encoder == "h264_amf":
            cmd.extend(
                (
                    "-quality",
                    "speed",
                    "-rc",
                    "cqp",
                    "-qp_i",
                    str(
                        max(
                            1,
                            min(51, crf),
                        )
                    ),
                    "-qp_p",
                    str(
                        max(
                            1,
                            min(51, crf),
                        )
                    ),
                )
            )

        cmd.extend(
            (
                # Broad MP4 compatibility.
                "-pix_fmt",
                "yuv420p",

                "-movflags",
                "+faststart",

                str(self._temp_video_path),
            )
        )

        # ==================================================================
        # FFmpeg stderr
        # ==================================================================

        self._stderr_file = tempfile.TemporaryFile(
            mode="w+b",
        )

        try:
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

        if self._process.stdin is None:
            try:
                self._process.kill()
            except Exception:
                pass

            self._stderr_file.close()
            self._cleanup_temp_video()

            raise RuntimeError(
                "Failed to open FFmpeg stdin"
            )

        # ==================================================================
        # Frame queue
        # ==================================================================

        self._frame_queue: queue.Queue[
            np.ndarray | _EndOfFrames
        ] = queue.Queue(
            maxsize=max(
                2,
                int(queue_size),
            )
        )

        self._encoder_thread = threading.Thread(
            target=self._encoder_worker,
            name="Mp4VideoEncoder",
            daemon=True,
        )

        self._encoder_thread.start()

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
        if (
            self._temp_video_path
            != self._output_path
        ):
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
            raise TypeError(
                f"Video frames must be uint8, "
                f"got {frame.dtype}"
            )

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

        if (
            not self._pad_right
            and not self._pad_bottom
            and frame.flags.c_contiguous
        ):
            return frame

        if (
            not self._pad_right
            and not self._pad_bottom
        ):
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
            :self._height,
            :self._width,
        ] = frame

        if self._pad_right:
            padded[
                :self._height,
                self._width:,
            ] = frame[
                :,
                -1:,
                :,
            ]

        if self._pad_bottom:
            padded[
                self._height:,
                :,
            ] = padded[
                self._height - 1:self._height,
                :,
            ]

        return padded

    # ======================================================================
    # Encoder thread
    # ======================================================================

    def _encoder_worker(self) -> None:
        """Continuously feed frames into FFmpeg."""

        process = self._process
        stdin = process.stdin
        frame_queue = self._frame_queue

        if stdin is None:
            self._write_error = RuntimeError(
                "FFmpeg stdin is unavailable"
            )
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
                    view = memoryview(item)

                    # Usually one write is sufficient, but FileIO is allowed
                    # to perform partial writes.
                    while view:
                        written = write(view)

                        if written is None:
                            raise BrokenPipeError(
                                "FFmpeg stdin write returned None"
                            )

                        if written <= 0:
                            raise BrokenPipeError(
                                "FFmpeg stdin closed"
                            )

                        view = view[
                            written:
                        ]

                finally:
                    task_done()

        except (
            BrokenPipeError,
            OSError,
        ) as exc:
            error = self._read_ffmpeg_error()

            self._write_error = RuntimeError(
                "FFmpeg stopped accepting frames"
                + (
                    f": {error}"
                    if error
                    else ""
                )
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
        audio_wave.writeframes(
            memoryview(
                self._audio_buffer
            )
        )

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
            raise ValueError(
                "Audio samples must be 1D or 2D, "
                f"got {source.shape}"
            )

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
                :self._audio_channels,
            ]

        elif channels < self._audio_channels:
            if (
                channels == 1
                and self._audio_channels == 2
            ):
                samples = np.repeat(
                    samples,
                    2,
                    axis=1,
                )

            else:
                padding = np.zeros(
                    (
                        samples.shape[0],
                        self._audio_channels
                        - channels,
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
            raise ValueError(
                f"Invalid audio sample rate: "
                f"{source_rate}"
            )

        if (
            source_rate
            != self._audio_sample_rate
        ):
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
        # ==============================================================

        np.clip(
            samples,
            -1.0,
            1.0,
            out=samples,
        )

        samples *= 32767.0

        return samples.astype(
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
            raise RuntimeError(
                "Cannot write to a closed Mp4VideoWriter"
            )

        write_error = self._write_error

        if write_error is not None:
            raise RuntimeError(
                "FFmpeg encoder failed"
            ) from write_error

        # ==============================================================
        # VIDEO
        # ==============================================================

        frame = self._prepare_frame(
            frame_rgb,
        )

        self._frame_queue.put(
            frame,
        )

        self._frame_count += 1

        # ==============================================================
        # AUDIO
        #
        # Accumulate PCM rather than touching the WAV object on every
        # frame.
        # ==============================================================

        if (
            self._include_audio
            and audio is not None
        ):
            audio_pcm = self._prepare_audio(
                audio,
            )

            if audio_pcm.size:
                with self._audio_lock:
                    # Extend from the NumPy buffer without calling
                    # .tobytes() explicitly.
                    self._audio_buffer.extend(
                        memoryview(
                            audio_pcm
                        ).cast("B")
                    )

                    self._audio_buffer_bytes = (
                        len(self._audio_buffer)
                    )

                    if (
                        self._audio_buffer_bytes
                        >= self._audio_flush_bytes
                    ):
                        self._flush_audio_buffer_locked()

    def write_video_only(
        self,
        frame_rgb: np.ndarray,
    ) -> None:
        self.write(
            frame_rgb,
        )

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

            self._frame_queue.put(
                _END,
            )

            # Wait for every frame to enter FFmpeg.
            self._frame_queue.join()

            self._encoder_thread.join()

            # ==============================================================
            # Close FFmpeg stdin.
            # ==============================================================

            stdin = self._process.stdin

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

            return_code = self._process.wait(
                timeout=300,
            )

            stderr = self._read_ffmpeg_error()

            if self._write_error is not None:
                raise RuntimeError(
                    "FFmpeg encoding failed"
                    + (
                        f": {stderr}"
                        if stderr
                        else ""
                    )
                ) from self._write_error

            if return_code != 0:
                raise RuntimeError(
                    "FFmpeg video encode failed "
                    f"({return_code})"
                    + (
                        f": {stderr}"
                        if stderr
                        else ""
                    )
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

            if (
                self._include_audio
                and self._audio_wav_path is not None
            ):
                self._mux_audio()

            elif (
                self._temp_video_path
                != self._output_path
            ):
                os.replace(
                    self._temp_video_path,
                    self._output_path,
                )

        finally:
            self._cleanup_audio()

            try:
                self._stderr_file.close()
            except Exception:
                pass

            if self._process.poll() is None:
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

                error = stderr_file.read().decode(
                    "utf-8",
                    errors="replace",
                ).strip()

                raise RuntimeError(
                    "FFmpeg audio mux failed "
                    f"({result.returncode})"
                    + (
                        f": {error}"
                        if error
                        else ""
                    )
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
        self.close()
