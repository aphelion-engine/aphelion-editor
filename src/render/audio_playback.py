"""Real-time audio playback system for preview."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import numpy as np

from core.audio import AudioData
from utils.logging_setup import get_logger

_LOG = get_logger("audio")


@dataclass
class AudioDeviceInfo:
    """Information about an available audio output device."""

    name: str
    """Device name"""

    index: int
    """Device index"""

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
        self._buffer_limit: int = 10
        self._buffer: deque[np.ndarray] = deque(maxlen=self._buffer_limit)
        self._sample_rate: int = 48000
        self._channels: int = 2
        self._current_device: AudioDeviceInfo | None = None
        self._lock = threading.RLock()
        self._playback_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stream: object | None = None

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

    def stop(self) -> None:
        """Stop audio playback."""
        with self._lock:
            if not self._playing:
                return
            self._playing = False
            self._stop_event.set()
            if self._playback_thread:
                self._playback_thread.join(timeout=1.0)
                self._playback_thread = None
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
            if self._buffer:
                target_sample_rate = self._sample_rate
                target_channels = self._channels
                if audio.sample_rate != target_sample_rate:
                    ratio = float(target_sample_rate) / float(audio.sample_rate)
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
                    samples = resampled
                if samples.shape[1] > target_channels:
                    samples = samples[:, :target_channels]
                elif samples.shape[1] < target_channels:
                    padding = np.zeros(
                        (samples.shape[0], target_channels - samples.shape[1]),
                        dtype=np.float32,
                    )
                    samples = np.concatenate((samples, padding), axis=1)
            else:
                self._sample_rate = max(1, int(audio.sample_rate))
                self._channels = max(1, int(target_channels))

            samples = np.clip(samples * self._volume, -1.0, 1.0).astype(np.float32, copy=False)
            self._buffer.append(samples)

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
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    if not self._buffer or self._paused:
                        chunk = None
                        wait_time = 0.01
                    else:
                        chunk = self._buffer.popleft()
                        wait_time = 0.0
                        sample_rate = self._sample_rate
                        channels = self._channels
                        device_index = (
                            None
                            if self._current_device is None or self._current_device.index < 0
                            else self._current_device.index
                        )

                if chunk is None:
                    self._stop_event.wait(wait_time)
                    continue

                try:
                    needs_new_stream = True
                    if stream is not None:
                        current_samplerate = int(getattr(stream, "samplerate", sample_rate))
                        current_channels = int(getattr(stream, "channels", channels))
                        current_device = getattr(stream, "device", device_index)
                        if isinstance(current_device, tuple):
                            current_device = current_device[1]
                        needs_new_stream = (
                            current_samplerate != sample_rate
                            or current_channels != channels
                            or current_device != device_index
                        )

                    if needs_new_stream:
                        if stream is not None:
                            stream.stop()
                            stream.close()
                        stream = sd.OutputStream(
                            samplerate=sample_rate,
                            channels=channels,
                            dtype="float32",
                            device=device_index,
                            blocksize=0,
                        )
                        stream.start()
                        with self._lock:
                            self._stream = stream

                    stream.write(chunk)
                except Exception as exc:  # noqa: BLE001
                    _LOG.warning("Audio playback chunk failed: %s", exc, exc_info=exc)
                    if stream is not None:
                        try:
                            stream.stop()
                            stream.close()
                        except Exception:
                            pass
                        stream = None
                        with self._lock:
                            self._stream = None
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            with self._lock:
                self._stream = None

    @staticmethod
    def get_available_devices() -> list[AudioDeviceInfo]:
        """Get list of available audio output devices."""
        devices: list[AudioDeviceInfo] = [
            AudioDeviceInfo(
                name="Default System Device",
                index=-1,
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
                api_name = "Unknown API"
                hostapi_index = dev.get("hostapi")
                if isinstance(hostapi_index, int) and 0 <= hostapi_index < len(host_apis):
                    api_name = str(host_apis[hostapi_index].get("name", api_name))
                name = f"{dev.get('name', f'Device {i}')} ({api_name})"
                devices.append(
                    AudioDeviceInfo(
                        name=name,
                        index=i,
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

        sample_rate = 48000
        duration = max(0.05, float(duration))
        frequency = max(20.0, float(frequency))
        frames = max(1, int(sample_rate * duration))
        t = np.arange(frames, dtype=np.float32) / float(sample_rate)
        envelope = np.minimum(1.0, t * 30.0) * np.minimum(1.0, (duration - t) * 30.0)
        tone = 0.2 * np.sin(2.0 * np.pi * frequency * t) * envelope
        stereo = np.column_stack((tone, tone)).astype(np.float32)
        device_index = None if device is None or device.index < 0 else device.index
        sd.play(stereo, samplerate=sample_rate, device=device_index)
        sd.wait()


# Global audio playback engine instance
_audio_engine: AudioPlaybackEngine | None = None


def get_audio_engine() -> AudioPlaybackEngine:
    """Get the global audio playback engine instance."""
    global _audio_engine
    if _audio_engine is None:
        _audio_engine = AudioPlaybackEngine()
    return _audio_engine
