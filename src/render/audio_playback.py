"""Real-time audio playback system for preview."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from core.audio import AudioData

if TYPE_CHECKING:
    pass


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
        self._volume: float = 1.0
        self._buffer: deque[np.ndarray] = deque(maxlen=10)  # Buffer of audio chunks
        self._sample_rate: int = 48000
        self._channels: int = 2
        self._current_device: AudioDeviceInfo | None = None
        self._lock = threading.Lock()
        self._playback_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_playing(self) -> bool:
        return self._playing and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_volume(self, volume: float) -> None:
        """Set master volume (0.0 to 2.0)."""
        self._volume = max(0.0, min(2.0, volume))

    def get_volume(self) -> float:
        return self._volume

    def set_device(self, device: AudioDeviceInfo | None) -> None:
        """Set the audio output device."""
        with self._lock:
            self._current_device = device
            if self._playing:
                self.stop()
                self.start()

    def get_device(self) -> AudioDeviceInfo | None:
        return self._current_device

    def start(self) -> None:
        """Start audio playback."""
        with self._lock:
            if self._playing:
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
        if not self._playing or self._paused:
            return

        with self._lock:
            # Apply volume
            samples = audio.samples * self._volume
            samples = np.clip(samples, -1.0, 1.0)

            # Ensure correct channels
            if samples.ndim == 1 and self._channels > 1:
                samples = np.repeat(samples[:, np.newaxis], self._channels, axis=1)
            elif samples.ndim == 2 and samples.shape[1] != self._channels:
                if samples.shape[1] > self._channels:
                    samples = samples[:, :self._channels]
                else:
                    # Pad with zeros
                    padding = np.zeros((samples.shape[0], self._channels - samples.shape[1]), dtype=np.float32)
                    samples = np.concatenate([samples, padding], axis=1)

            # Add to buffer
            self._buffer.append(samples.astype(np.float32))

    def _playback_loop(self) -> None:
        """Main playback loop running in background thread."""
        try:
            import sounddevice as sd
        except ImportError:
            # Fallback: just consume the buffer without actual playback
            while not self._stop_event.is_set():
                with self._lock:
                    if self._buffer:
                        self._buffer.popleft()
                self._stop_event.wait(0.01)
            return

        while not self._stop_event.is_set():
            with self._lock:
                if not self._buffer or self._paused:
                    self._stop_event.wait(0.01)
                    continue

                samples = self._buffer.popleft()

            # Play the audio chunk
            try:
                device_args = {}
                if self._current_device is not None:
                    device_args['device'] = self._current_device.index

                sd.play(
                    samples,
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    **device_args
                )
                # Wait for playback to complete (approximately)
                duration = len(samples) / self._sample_rate
                self._stop_event.wait(duration * 0.9)  # Slightly less to avoid gaps
            except Exception:
                # If playback fails, continue consuming buffer
                continue

    @staticmethod
    def get_available_devices() -> list[AudioDeviceInfo]:
        """Get list of available audio output devices."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            output_devices = []

            for i, dev in enumerate(devices):
                if dev['max_output_channels'] > 0:
                    output_devices.append(AudioDeviceInfo(
                        name=dev['name'],
                        index=i,
                        max_channels=dev['max_output_channels'],
                        default_sample_rate=int(dev.get('default_samplerate', 48000))
                    ))

            return output_devices
        except ImportError:
            # Return default device info if sounddevice not available
            return [AudioDeviceInfo(
                name="Default Output",
                index=-1,
                max_channels=2,
                default_sample_rate=48000
            )]

    @staticmethod
    def get_default_device() -> AudioDeviceInfo | None:
        """Get the default audio output device."""
        devices = AudioPlaybackEngine.get_available_devices()
        if devices:
            return devices[0]
        return None


# Global audio playback engine instance
_audio_engine: AudioPlaybackEngine | None = None


def get_audio_engine() -> AudioPlaybackEngine:
    """Get the global audio playback engine instance."""
    global _audio_engine
    if _audio_engine is None:
        _audio_engine = AudioPlaybackEngine()
    return _audio_engine
