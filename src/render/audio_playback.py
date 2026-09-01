"""Real-time audio playback system for preview."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import numpy as np

_FALLBACK_SAMPLE_RATES: tuple[int, ...] = (48000, 44100)
_MAX_WRITE_CHUNKS: int = 4

from core.audio import AudioData
from utils.logging_setup import get_logger


def _resample_audio(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample ``samples`` from ``src_rate`` to ``dst_rate`` with linear interpolation."""
    if src_rate <= 0 or dst_rate <= 0 or src_rate == dst_rate or samples.shape[0] == 0:
        return samples
    ratio = float(dst_rate) / float(src_rate)
    sample_positions = np.arange(
        max(1, int(round(samples.shape[0] * ratio))),
        dtype=np.float32,
    ) / ratio
    source_positions = np.arange(samples.shape[0], dtype=np.float32)
    resampled = np.empty((sample_positions.shape[0], samples.shape[1]), dtype=np.float32)
    for channel in range(samples.shape[1]):
        resampled[:, channel] = np.interp(
            sample_positions,
            source_positions,
            samples[:, channel],
        )
    return resampled

_LOG = get_logger("audio")


@dataclass
class AudioDeviceInfo:
    """Information about an available audio output device."""

    name: str
    """Device name"""

    index: int
    """Device index"""

    host_api_name: str
    """Underlying driver / host API name, e.g. WASAPI, MME, ASIO"""

    max_channels: int
    """Maximum number of output channels"""

    default_sample_rate: int
    """Default sample rate"""


class AudioPlaybackEngine:
    """Real-time audio playback engine synchronized with video preview."""

    def __init__(self) -> None:
        self._playing: bool = False
        self._paused: bool = False
        self._enabled: bool = True
        self._volume: float = 1.0
        self._buffer_limit: int = 12
        self._buffer: deque[np.ndarray] = deque(maxlen=self._buffer_limit)
        self._sample_rate: int = 48000
        self._channels: int = 2
        self._preferred_sample_rate: int = 48000
        self._preferred_channels: int = 2
        self._stream_blocksize: int = 512
        self._latency: str = "high"
        self._current_device: AudioDeviceInfo | None = None
        self._lock = threading.RLock()
        self._playback_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stream: object | None = None
        self._stream_device_index: int | None = None

    @property
    def is_playing(self) -> bool:
        return self._playing and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_enabled(self, enabled: bool) -> None:
        """Globally enable or disable audio playback."""
        should_stop = False
        with self._lock:
            enabled = bool(enabled)
            self._enabled = enabled
            self._buffer.clear()
            if not enabled and self._playing:
                should_stop = True
        if should_stop:
            self.stop()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_volume(self, volume: float) -> None:
        """Set master volume (0.0 to 2.0)."""
        self._volume = max(0.0, min(2.0, volume))

    def set_buffer_size(self, chunk_count: int) -> None:
        """Resize the queued-chunk buffer used for preview playback."""
        size = max(1, int(chunk_count))
        with self._lock:
            self._buffer_limit = size
            retained = list(self._buffer)[-size:]
            self._buffer = deque(retained, maxlen=size)

    def set_stream_config(
        self,
        *,
        sample_rate: int,
        channels: int,
        blocksize: int,
        latency_preset: str,
    ) -> None:
        """Set preferred output stream parameters."""
        restart = False
        latency_key = str(latency_preset).lower()
        if latency_key == "low":
            latency = "low"
            resolved_blocksize = blocksize if blocksize > 0 else 256
        elif latency_key == "safe":
            latency = "high"
            resolved_blocksize = max(512, int(blocksize)) if blocksize > 0 else 1024
        else:
            latency = "high"
            resolved_blocksize = blocksize if blocksize > 0 else 512
        requested_rate = max(1, int(sample_rate))
        with self._lock:
            self._preferred_sample_rate = requested_rate
            self._preferred_channels = 1 if int(channels) == 1 else 2
            self._stream_blocksize = max(0, int(resolved_blocksize))
            self._latency = latency
            restart = self._playing
        if restart:
            self.stop()
            self.start()

    def get_volume(self) -> float:
        return self._volume

    def set_device(self, device: AudioDeviceInfo | None) -> None:
        """Set the audio output device."""
        restart = False
        with self._lock:
            self._current_device = device
            restart = self._playing
        if restart:
            self.stop()
            self.start()

    def get_device(self) -> AudioDeviceInfo | None:
        return self._current_device

    def start(self) -> None:
        """Start audio playback."""
        with self._lock:
            if self._playing or not self._enabled:
                return
            self._playing = True
            self._paused = False
            self._stop_event.clear()
            self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
            self._playback_thread.start()
            _LOG.info("Audio playback engine started")

    def stop(self) -> None:
        """Stop audio playback."""
        thread = None
        with self._lock:
            if not self._playing:
                self._buffer.clear()
                return
            self._playing = False
            self._stop_event.set()
            thread = self._playback_thread
            self._playback_thread = None
            self._buffer.clear()
        if thread is not None:
            thread.join(timeout=1.0)
        _LOG.info("Audio playback engine stopped")

    def clear_buffer(self) -> None:
        """Drop any queued preview audio chunks."""
        with self._lock:
            self._buffer.clear()

    def pause(self) -> None:
        """Pause audio playback."""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        """Resume audio playback."""
        with self._lock:
            self._paused = False

    def feed_audio(self, audio: AudioData) -> None:
        """Feed audio data for playback."""
        if not self._playing or self._paused or not self._enabled:
            return

        with self._lock:
            samples = np.asarray(audio.samples, dtype=np.float32)
            target_channels = max(1, int(audio.num_channels))

            if samples.ndim == 1:
                samples = samples[:, np.newaxis]

            if samples.shape[1] > target_channels:
                samples = samples[:, :target_channels]
            elif samples.shape[1] < target_channels:
                padding = np.zeros(
                    (samples.shape[0], target_channels - samples.shape[1]),
                    dtype=np.float32,
                )
                samples = np.concatenate((samples, padding), axis=1)

            # Avoid mid-playback device/stream reconfiguration churn.
            target_sample_rate = self._sample_rate if self._buffer else self._preferred_sample_rate
            target_channels = self._channels if self._buffer else self._preferred_channels
            samples = _resample_audio(samples, int(audio.sample_rate), int(target_sample_rate))
            if samples.shape[1] > target_channels:
                samples = samples[:, :target_channels]
            elif samples.shape[1] < target_channels:
                padding = np.zeros(
                    (samples.shape[0], target_channels - samples.shape[1]),
                    dtype=np.float32,
                )
                samples = np.concatenate((samples, padding), axis=1)
            self._sample_rate = max(1, int(target_sample_rate))
            self._channels = max(1, int(target_channels))

            samples = np.clip(samples * self._volume, -1.0, 1.0).astype(np.float32, copy=False)
            if len(self._buffer) == self._buffer.maxlen:
                self._buffer.popleft()
            self._buffer.append(samples)

    def _open_stream(self, sd: object, device_index: int | None, sample_rate: int, channels: int) -> object:
        preferred_rates: list[int] = [sample_rate]
        if self._current_device is not None and self._current_device.default_sample_rate > 0:
            preferred_rates.append(int(self._current_device.default_sample_rate))
        preferred_rates.extend(_FALLBACK_SAMPLE_RATES)
        preferred_rates.extend((96000, 88200, 32000, 24000, 22050))
        seen: set[int] = set()
        last_error: Exception | None = None
        for candidate_rate in preferred_rates:
            if candidate_rate in seen or candidate_rate <= 0:
                continue
            seen.add(candidate_rate)
            try:
                return sd.OutputStream(
                    samplerate=candidate_rate,
                    channels=channels,
                    dtype="float32",
                    device=device_index,
                    blocksize=self._stream_blocksize,
                    latency=self._latency,
                )
            except Exception as exc:
                last_error = exc
                try:
                    return sd.OutputStream(
                        samplerate=candidate_rate,
                        channels=channels,
                        dtype="float32",
                        device=device_index,
                        blocksize=0,
                        latency="high",
                    )
                except Exception as fallback_exc:
                    last_error = fallback_exc
                    continue
        assert last_error is not None
        raise last_error

    def _playback_loop(self) -> None:
        """Main playback loop running in background thread."""
        try:
            import sounddevice as sd
        except ImportError:
            _LOG.warning("sounddevice is unavailable; preview audio playback disabled")
            while not self._stop_event.is_set():
                with self._lock:
                    if self._buffer:
                        self._buffer.popleft()
                self._stop_event.wait(0.01)
            return

        stream = None
        stream_failed = False
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    paused = self._paused
                    buffered_chunks = len(self._buffer)
                    sample_rate = self._sample_rate
                    channels = self._channels
                    device_index = (
                        None
                        if self._current_device is None or self._current_device.index < 0
                        else self._current_device.index
                    )

                    if paused or buffered_chunks == 0:
                        chunk = None
                        wait_time = 0.005
                    else:
                        write_chunks = min(buffered_chunks, _MAX_WRITE_CHUNKS)
                        pieces = [self._buffer.popleft() for _ in range(write_chunks)]
                        chunk = pieces[0] if len(pieces) == 1 else np.concatenate(pieces, axis=0)
                        wait_time = 0.0

                if chunk is None:
                    self._stop_event.wait(wait_time)
                    continue

                try:
                    needs_new_stream = True
                    if stream is not None:
                        current_samplerate = int(getattr(stream, "samplerate", sample_rate))
                        current_channels = int(getattr(stream, "channels", channels))
                        current_device = self._stream_device_index
                        needs_new_stream = (
                            current_samplerate != sample_rate
                            or current_channels != channels
                            or current_device != device_index
                        )

                    if needs_new_stream:
                        if stream is not None:
                            stream.stop()
                            stream.close()
                        stream = self._open_stream(sd, device_index, sample_rate, channels)
                        stream.start()
                        opened_rate = int(getattr(stream, "samplerate", sample_rate))
                        with self._lock:
                            self._sample_rate = opened_rate
                            self._channels = channels
                            self._stream = stream
                            self._stream_device_index = device_index
                        _LOG.info(
                            "Opened audio output stream device=%s rate=%s channels=%s blocksize=%s latency=%s",
                            device_index if device_index is not None else "default",
                            opened_rate,
                            channels,
                            self._stream_blocksize,
                            self._latency,
                        )
                        stream_failed = False

                    active_rate = int(getattr(stream, "samplerate", sample_rate))
                    if active_rate != sample_rate:
                        chunk = _resample_audio(chunk, int(sample_rate), active_rate)
                        with self._lock:
                            self._sample_rate = active_rate
                    stream.write(chunk)
                except Exception as exc:  # noqa: BLE001
                    if not stream_failed:
                        _LOG.warning("Audio playback chunk failed: %s", exc, exc_info=exc)
                    stream_failed = True
                    if stream is not None:
                        try:
                            stream.stop()
                            stream.close()
                        except Exception:
                            pass
                        stream = None
                    with self._lock:
                        self._stream = None
                        self._stream_device_index = None
                    self._stop_event.wait(0.1)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            with self._lock:
                self._stream = None
                self._stream_device_index = None

    @staticmethod
    def get_available_devices() -> list[AudioDeviceInfo]:
        """Get list of available audio output devices."""
        devices: list[AudioDeviceInfo] = [
            AudioDeviceInfo(
                name="Default System Device",
                index=-1,
                host_api_name="System Default",
                max_channels=2,
                default_sample_rate=48000,
            )
        ]
        try:
            import sounddevice as sd

            raw_devices = sd.query_devices()
            host_apis = sd.query_hostapis()
            for i, dev in enumerate(raw_devices):
                max_output_channels = int(dev.get("max_output_channels", 0) or 0)
                if max_output_channels <= 0:
                    continue
                api_name = "Unknown Driver"
                hostapi_index = dev.get("hostapi")
                if isinstance(hostapi_index, int) and 0 <= hostapi_index < len(host_apis):
                    api_name = str(host_apis[hostapi_index].get("name", api_name))
                name = f"{dev.get('name', f'Device {i}')} ({api_name})"
                devices.append(
                    AudioDeviceInfo(
                        name=name,
                        index=i,
                        host_api_name=api_name,
                        max_channels=max_output_channels,
                        default_sample_rate=int(dev.get("default_samplerate", 48000) or 48000),
                    )
                )
        except ImportError:
            _LOG.warning("sounddevice is unavailable; only default audio device placeholder is exposed")
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Failed to enumerate audio devices: %s", exc, exc_info=exc)
        return devices

    @staticmethod
    def get_default_device() -> AudioDeviceInfo | None:
        """Get the default audio output device."""
        devices = AudioPlaybackEngine.get_available_devices()
        if devices:
            return devices[0]
        return None

    def test_device(
        self,
        device: AudioDeviceInfo | None = None,
        *,
        duration: float = 0.75,
        frequency: float = 440.0,
    ) -> None:
        """Play a short test tone on the requested device."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is not installed") from exc

        preferred_rate = self._preferred_sample_rate
        channels = self._preferred_channels
        duration = max(0.05, float(duration))
        frequency = max(20.0, float(frequency))
        device_index = None if device is None or device.index < 0 else device.index
        stream = self._open_stream(sd, device_index, preferred_rate, channels)
        actual_rate = int(getattr(stream, "samplerate", preferred_rate))
        frames = max(1, int(actual_rate * duration))
        t = np.arange(frames, dtype=np.float32) / float(actual_rate)
        envelope = np.minimum(1.0, t * 30.0) * np.minimum(1.0, (duration - t) * 30.0)
        tone = 0.2 * np.sin(2.0 * np.pi * frequency * t) * envelope
        if channels <= 1:
            test_buffer = tone.astype(np.float32)
        else:
            test_buffer = np.column_stack([tone for _ in range(channels)]).astype(np.float32)
        try:
            stream.start()
            stream.write(test_buffer)
        finally:
            stream.stop()
            stream.close()


# Global audio playback engine instance
_audio_engine: AudioPlaybackEngine | None = None


def get_audio_engine() -> AudioPlaybackEngine:
    """Get the global audio playback engine instance."""
    global _audio_engine
    if _audio_engine is None:
        _audio_engine = AudioPlaybackEngine()
    return _audio_engine
