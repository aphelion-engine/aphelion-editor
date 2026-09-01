"""Built-in audio routing and processing nodes."""

from __future__ import annotations

from enum import IntEnum, auto

import numpy as np

from core.audio import AudioData, FrameWithAudio
from core.nodes.base import NodeProperty, NodePropertyInputType, NodeSocketType, NodeValue
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import choice_property, number_property, slider_property, toggle_property
from utils.logging_setup import get_logger

AUDIO_CATEGORY: str = "Audio"
AUDIO_NODE_COLOR: tuple[int, int, int] = (110, 140, 220)
_AUDIO_LOG = get_logger("audio.nodes")


class EqBandMode(IntEnum):
    Balanced = auto()
    Warm = auto()
    Bright = auto()
    Vocal = auto()
    BassBoost = auto()
    MidCut = auto()
    Presence = auto()
    Air = auto()
    Custom = auto()


class AudioMixQuality(IntEnum):
    Fast = auto()
    Balanced = auto()
    High = auto()


def _ensure_2d(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 1:
        return samples[:, np.newaxis]
    return samples


def _restore_channels(samples: np.ndarray, channels: int) -> np.ndarray:
    if channels == 1:
        return samples[:, 0]
    return samples


def _apply_audio_gate(samples: np.ndarray, threshold: float, ratio: float) -> np.ndarray:
    if threshold <= 0.0:
        return samples
    magnitude = np.abs(samples)
    quiet = magnitude < threshold
    gated = np.copy(samples)
    gated[quiet] *= max(0.0, min(1.0, ratio))
    return gated


def _moving_average(samples: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 1 or samples.shape[0] <= 1:
        return samples
    kernel = np.ones(radius, dtype=np.float32) / float(radius)
    filtered = np.empty_like(samples)
    for channel in range(samples.shape[1]):
        filtered[:, channel] = np.convolve(samples[:, channel], kernel, mode="same")
    return filtered


def _apply_peaking_eq(samples: np.ndarray, sample_rate: int, bands: list[dict[str, float]]) -> np.ndarray:
    if samples.shape[0] == 0 or not bands:
        return samples
    source = _ensure_2d(samples)
    spectrum = np.fft.rfft(source, axis=0)
    freqs = np.fft.rfftfreq(source.shape[0], d=1.0 / float(sample_rate))
    response = np.ones(freqs.shape, dtype=np.float32)
    log_freqs = np.log2(np.maximum(freqs, 1.0))
    for band in bands:
        center = max(20.0, min(20000.0, float(band.get("freq", 1000.0))))
        gain_db = max(-24.0, min(24.0, float(band.get("gain", 0.0))))
        q = max(0.2, min(10.0, float(band.get("q", 1.0))))
        width = max(0.08, 1.25 / q)
        shape = np.exp(-0.5 * ((log_freqs - np.log2(center)) / width) ** 2)
        response *= np.power(np.float32(_db_to_gain(gain_db)), shape, dtype=np.float32)
    wet = np.fft.irfft(spectrum * response[:, np.newaxis], n=source.shape[0], axis=0)
    return np.clip(wet.astype(np.float32, copy=False), -1.0, 1.0)


def _simple_reverb(samples: np.ndarray, sample_rate: int, decay: float, pre_delay_ms: float, taps: int) -> np.ndarray:
    if decay <= 0.0 or taps <= 0:
        return np.copy(samples)
    wet = np.copy(samples) * np.float32(0.35)
    base_delay = max(1, int(sample_rate * max(0.0, pre_delay_ms) / 1000.0))
    spread = max(1, base_delay // 2)
    for tap in range(1, taps + 1):
        delay = base_delay + (tap - 1) * spread
        if delay >= samples.shape[0]:
            break
        gain = (decay ** tap) * (0.9 - min(0.6, tap * 0.08))
        wet[delay:] += samples[:-delay] * gain
    if samples.shape[1] >= 2:
        stereo_wet = np.copy(wet)
        stereo_wet[1:, 0] += wet[:-1, 1] * 0.08
        stereo_wet[1:, 1] += wet[:-1, 0] * 0.08
        wet = stereo_wet
    return np.clip(wet, -1.0, 1.0)


def _resample_audio_to(samples: np.ndarray, source_rate: int, target_rate: int, quality: AudioMixQuality = AudioMixQuality.Balanced) -> np.ndarray:
    if source_rate == target_rate or samples.shape[0] == 0:
        return samples
    samples_2d = _ensure_2d(samples)
    source_len = samples_2d.shape[0]
    target_len = max(1, int(round(source_len * float(target_rate) / float(source_rate))))
    if target_len == source_len:
        return samples_2d
    src_positions = np.arange(source_len, dtype=np.float32)
    dst_positions = np.linspace(0.0, max(0.0, float(source_len - 1)), target_len, dtype=np.float32)
    if quality == AudioMixQuality.Fast:
        indices = np.clip(np.rint(dst_positions).astype(np.int32), 0, source_len - 1)
        return samples_2d[indices]
    out = np.empty((target_len, samples_2d.shape[1]), dtype=np.float32)
    for channel in range(samples_2d.shape[1]):
        out[:, channel] = np.interp(dst_positions, src_positions, samples_2d[:, channel]).astype(np.float32, copy=False)
    if quality == AudioMixQuality.High and target_len >= 8:
        kernel = np.array([1.0, 4.0, 6.0, 4.0, 1.0], dtype=np.float32)
        kernel /= np.sum(kernel)
        smoothed = np.empty_like(out)
        for channel in range(out.shape[1]):
            smoothed[:, channel] = np.convolve(out[:, channel], kernel, mode="same")
        return smoothed
    return out


def _match_audio_layout(audio: AudioData, sample_rate: int, channels: int, quality: AudioMixQuality = AudioMixQuality.Balanced) -> np.ndarray:
    samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
    if audio.sample_rate != sample_rate:
        samples = _resample_audio_to(samples, int(audio.sample_rate), int(sample_rate), quality)
    if samples.shape[1] > channels:
        samples = samples[:, :channels]
    elif samples.shape[1] < channels:
        if samples.shape[1] == 1 and channels == 2:
            samples = np.repeat(samples, 2, axis=1)
        else:
            samples = np.concatenate((samples, np.zeros((samples.shape[0], channels - samples.shape[1]), dtype=np.float32)), axis=1)
    return samples


def _pad_audio_length(samples: np.ndarray, length: int) -> np.ndarray:
    if samples.shape[0] >= length:
        return samples
    return np.concatenate((samples, np.zeros((length - samples.shape[0], samples.shape[1]), dtype=np.float32)), axis=0)


def _db_to_gain(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _blend_dry_wet(dry: np.ndarray, wet: np.ndarray, dry_level: float, wet_level: float) -> np.ndarray:
    return np.clip(dry * dry_level + wet * wet_level, -1.0, 1.0)


def _apply_output_gain(samples: np.ndarray, output_gain_percent: float) -> np.ndarray:
    return np.clip(samples * (output_gain_percent / 100.0), -1.0, 1.0)


def _wrap_audio(samples: np.ndarray, sample_rate: int, channels: int) -> AudioData:
    return AudioData(samples=np.ascontiguousarray(_restore_channels(samples, channels).astype(np.float32, copy=False)), sample_rate=sample_rate)


def _input_audio_payload(node: FrameNode, slot: str = "audio") -> tuple[AudioData | None, np.ndarray | None]:
    payload = node.input_frame_with_audio(slot)
    if payload is not None:
        return payload.audio, payload.frame
    return node.input_audio(slot), None


def _effect_result(audio: AudioData, frame: np.ndarray | None) -> NodeValue:
    del frame
    return {"audio": audio}


def _log_effect_flow(node: FrameNode, audio: AudioData | None, frame: np.ndarray | None) -> None:
    if audio is None:
        _AUDIO_LOG.debug("%s: no audio payload", node.node_type)
        return
    _AUDIO_LOG.debug(
        "%s: samples=%s rate=%s channels=%s has_frame=%s",
        node.node_type,
        np.asarray(audio.samples).shape,
        audio.sample_rate,
        audio.num_channels,
        frame is not None,
    )


def _effect_levels(node: FrameNode, group: str, default_wet: float = 100.0) -> tuple[float, float, float]:
    del group
    dry_level = node.float_value("dry", 100.0) / 100.0
    wet_level = node.float_value("wet", default_wet) / 100.0
    output_gain = node.float_value("output_gain", 100.0)
    return dry_level, wet_level, output_gain


def _add_standard_effect_mix(node: FrameNode, *, group: str, wet_default: int = 100, output_priority: int = 99) -> None:
    node.set_property("dry", slider_property(100, 0, 200, priority=90, group=group, label="Dry", description="Dry/original signal level.", suffix="%"))
    node.set_property("wet", slider_property(wet_default, 0, 200, priority=91, group=group, label="Wet", description="Processed signal level.", suffix="%"))
    node.set_property("output_gain", slider_property(100, 0, 200, priority=output_priority, group=group, label="Output", description="Final output level after dry/wet mix.", suffix="%"))


class AudioExtractNode(FrameNode):
    node_type = "Extract Audio"
    node_category = AUDIO_CATEGORY
    node_description = "Split a frame-with-audio stream into audio and a silent frame stream"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)
        self.add_output("audio", NodeSocketType.Audio)
        self.add_output("frame", NodeSocketType.Frame)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        payload = self.input_frame_with_audio("frame")
        if payload is not None:
            audio = payload.audio
            if audio is None:
                audio = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            silent = AudioData.silence(
                duration=audio.duration,
                sample_rate=audio.sample_rate,
                channels=audio.num_channels,
            )
            return {
                "audio": audio,
                "frame": FrameWithAudio(frame=payload.frame, audio=silent),
            }
        frame = self.input_frame("frame")
        if frame is None:
            frame = self.blank_frame()
        silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
        return {
            "audio": silent,
            "frame": FrameWithAudio(frame=frame, audio=silent),
        }


class AudioAttachNode(FrameNode):
    node_type = "Attach Audio"
    node_category = AUDIO_CATEGORY
    node_description = "Attach an audio stream to a frame stream"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("frame", NodeSocketType.Frame)
        self.set_property(
            "replace_existing_audio",
            toggle_property(
                True,
                priority=0,
                group="Attach",
                label="Replace Existing",
                description="Replace any audio already present on the frame input.",
            ),
        )

    def evaluate(self, frame_num: int) -> np.ndarray | FrameWithAudio:
        del frame_num
        payload = self.input_frame_with_audio("frame")
        frame = payload.frame if payload is not None else self.input_frame("frame")
        if frame is None:
            return self.blank_frame()
        audio_input = self.get_input_value("audio")
        audio = self.input_audio("audio")
        if audio is None and isinstance(audio_input, FrameWithAudio):
            audio = audio_input.audio
        if audio is None:
            return payload if payload is not None else frame
        if payload is not None and payload.audio is not None and not self.bool_value("replace_existing_audio", True):
            audio = payload.audio
        return FrameWithAudio(frame=frame, audio=audio)


class AudioGainNode(FrameNode):
    node_type = "Audio Gain"
    node_category = AUDIO_CATEGORY
    node_description = "Adjust audio level with gain and mute controls"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("enabled", toggle_property(True, priority=0, group="Gain", label="Enabled", description="Bypass this node without removing it."))
        self.set_property("gain", slider_property(100, 0, 300, priority=10, group="Gain", label="Gain", description="Linear output gain.", suffix="%"))
        self.set_property("mute", toggle_property(False, priority=11, group="Gain", label="Mute", description="Silence the output."))

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        if not self.bool_value("enabled", True):
            return _effect_result(audio, frame)
        if self.bool_value("mute", False):
            return _effect_result(AudioData.silence(duration=audio.duration, sample_rate=audio.sample_rate, channels=audio.num_channels), frame)
        gain = self.float_value("gain", 100.0) / 100.0
        samples = np.clip(np.asarray(audio.samples, dtype=np.float32) * gain, -1.0, 1.0)
        return _effect_result(AudioData(samples=np.ascontiguousarray(samples), sample_rate=audio.sample_rate), frame)


class AudioMixNode(FrameNode):
    node_type = "Audio Mix"
    node_category = AUDIO_CATEGORY
    node_description = "Crossfade and mix two audio inputs together"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("a", NodeSocketType.Audio)
        self.add_input("b", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("mix", slider_property(50, 0, 100, priority=0, group="Mix", label="Balance", description="Crossfade between A and B.", suffix="%"))
        self.set_property("a_level", slider_property(100, 0, 200, priority=1, group="Mix", label="A Level", description="Level applied to input A.", suffix="%"))
        self.set_property("b_level", slider_property(100, 0, 200, priority=2, group="Mix", label="B Level", description="Level applied to input B.", suffix="%"))
        self.set_property("quality", choice_property(AudioMixQuality.Balanced, priority=3, group="Mix", label="Quality", description="Resampling quality used when inputs differ."))
        self.set_property("normalize", toggle_property(True, priority=4, group="Mix", label="Normalize", description="Prevent clipping by normalizing the mixed output."))
        self.set_property("output_gain", slider_property(100, 0, 200, priority=5, group="Mix", label="Output", description="Final output level.", suffix="%"))

    def evaluate(self, frame_num: int) -> AudioData:
        del frame_num
        audio_a = self.input_audio("a")
        audio_b = self.input_audio("b")
        if audio_a is None:
            return audio_b if audio_b is not None else AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
        if audio_b is None:
            return audio_a
        quality = self.enum_value("quality", AudioMixQuality, AudioMixQuality.Balanced)
        sample_rate = max(audio_a.sample_rate, audio_b.sample_rate)
        channels = max(audio_a.num_channels, audio_b.num_channels)
        a = _match_audio_layout(audio_a, sample_rate, channels, quality)
        b = _match_audio_layout(audio_b, sample_rate, channels, quality)
        length = max(a.shape[0], b.shape[0])
        a = _pad_audio_length(a, length)
        b = _pad_audio_length(b, length)
        a *= self.float_value("a_level", 100.0) / 100.0
        b *= self.float_value("b_level", 100.0) / 100.0
        mix = self.float_value("mix", 50.0) / 100.0
        out = a * (1.0 - mix) + b * mix
        if self.bool_value("normalize", True):
            peak = float(np.max(np.abs(out))) if out.size else 0.0
            if peak > 1.0:
                out = out / peak
        out = _apply_output_gain(out, self.float_value("output_gain", 100.0))
        return _wrap_audio(out, sample_rate, channels)


class AudioDelayNode(FrameNode):
    node_type = "Audio Delay"
    node_category = AUDIO_CATEGORY
    node_description = "Delay audio with feedback for echo-style effects"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("delay_ms", number_property(120.0, 1.0, 2000.0, priority=0, group="Delay", label="Delay", description="Delay time in milliseconds.", suffix=" ms"))
        self.set_property("feedback", slider_property(35, 0, 95, priority=1, group="Delay", label="Feedback", description="Amount of delayed signal fed back.", suffix="%"))
        _add_standard_effect_mix(self, group="Delay", wet_default=70)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        delay_samples = max(1, int(audio.sample_rate * self.float_value("delay_ms", 120.0) / 1000.0))
        feedback = self.float_value("feedback", 35.0) / 100.0
        wet = np.zeros_like(samples)
        wet += samples * 0.2
        for i in range(delay_samples, samples.shape[0]):
            wet[i] += samples[i - delay_samples]
            if i >= delay_samples * 2:
                wet[i] += wet[i - delay_samples] * feedback
        dry_level, wet_level, output_gain = _effect_levels(self, "Delay", default_wet=70.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioReverbNode(FrameNode):
    node_type = "Audio Reverb"
    node_category = AUDIO_CATEGORY
    node_description = "Apply a simple multi-tap reverb to audio"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("decay", slider_property(55, 0, 95, priority=0, group="Reverb", label="Decay", description="Strength of successive reflections.", suffix="%"))
        self.set_property("pre_delay_ms", number_property(35.0, 0.0, 250.0, priority=1, group="Reverb", label="Pre-Delay", description="Gap before the first reflection.", suffix=" ms"))
        self.set_property("reflections", slider_property(4, 1, 8, priority=2, group="Reverb", label="Reflections", description="Number of simulated reflections."))
        _add_standard_effect_mix(self, group="Reverb", wet_default=70)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        wet = _simple_reverb(
            samples,
            audio.sample_rate,
            self.float_value("decay", 55.0) / 100.0,
            self.float_value("pre_delay_ms", 35.0),
            self.int_value("reflections", 4),
        )
        dry_level, wet_level, output_gain = _effect_levels(self, "Reverb", default_wet=70.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioEqNode(FrameNode):
    node_type = "Audio EQ"
    node_category = AUDIO_CATEGORY
    node_description = "Apply a simple three-band tone-shaping equalizer"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("preset", choice_property(EqBandMode.Balanced, priority=0, group="EQ", label="Preset", description="Quick tone-shaping preset."))
        self.set_property("low_gain", slider_property(0, -24, 24, priority=1, group="EQ", label="Low", description="Low band gain.", suffix=" dB"))
        self.set_property("mid_gain", slider_property(0, -24, 24, priority=2, group="EQ", label="Mid", description="Mid band gain.", suffix=" dB"))
        self.set_property("high_gain", slider_property(0, -24, 24, priority=3, group="EQ", label="High", description="High band gain.", suffix=" dB"))
        self.set_property("eq_curve", NodeProperty(input_type=NodePropertyInputType.Custom, value={"low": 0, "mid": 0, "high": 0}, priority=4, group="EQ", label="EQ Curve", description="Visual EQ editor."))
        _add_standard_effect_mix(self, group="EQ", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        preset = self.enum_value("preset", EqBandMode, EqBandMode.Balanced)
        low_db = self.float_value("low_gain", 0.0)
        mid_db = self.float_value("mid_gain", 0.0)
        high_db = self.float_value("high_gain", 0.0)
        preset_map: dict[EqBandMode, tuple[float, float, float]] = {
            EqBandMode.Balanced: (low_db, mid_db, high_db),
            EqBandMode.Warm: (4.0, -1.0, -2.0),
            EqBandMode.Bright: (-2.0, 0.0, 4.0),
            EqBandMode.Vocal: (-3.0, 3.0, 2.0),
            EqBandMode.BassBoost: (6.0, -1.0, -2.0),
            EqBandMode.MidCut: (0.0, -4.0, 1.0),
            EqBandMode.Presence: (-1.0, 2.0, 3.0),
            EqBandMode.Air: (0.0, -1.0, 5.0),
            EqBandMode.Custom: (low_db, mid_db, high_db),
        }
        low_db, mid_db, high_db = preset_map.get(preset, (low_db, mid_db, high_db))
        eq_curve_prop = self.get_property("eq_curve")
        custom_bands: list[dict[str, float]] = []
        if isinstance(eq_curve_prop.value if eq_curve_prop else None, dict):
            raw_bands = eq_curve_prop.value.get("bands")
            if isinstance(raw_bands, list):
                custom_bands = [dict(item) for item in raw_bands if isinstance(item, dict)]
        if preset == EqBandMode.Custom and custom_bands:
            wet = _apply_peaking_eq(samples, audio.sample_rate, custom_bands)
        else:
            low = _moving_average(samples, max(3, int(audio.sample_rate * 0.002)))
            high = samples - _moving_average(samples, max(3, int(audio.sample_rate * 0.0005)))
            mid = samples - low - high
            low_gain = 10.0 ** (low_db / 20.0)
            mid_gain = 10.0 ** (mid_db / 20.0)
            high_gain = 10.0 ** (high_db / 20.0)
            wet = np.clip(low * low_gain + mid * mid_gain + high * high_gain, -1.0, 1.0)
        dry_level, wet_level, output_gain = _effect_levels(self, "EQ", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioPanNode(FrameNode):
    node_type = "Audio Pan"
    node_category = AUDIO_CATEGORY
    node_description = "Pan mono or stereo audio left and right"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("pan", slider_property(0, -100, 100, priority=0, group="Pan", label="Pan", description="Left/right stereo placement.", suffix="%"))
        _add_standard_effect_mix(self, group="Pan", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0), channels=2)
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        if samples.shape[1] == 1:
            samples = np.repeat(samples, 2, axis=1)
        pan = np.clip(self.float_value("pan", 0.0) / 100.0, -1.0, 1.0)
        left = np.cos((pan + 1.0) * np.pi / 4.0)
        right = np.sin((pan + 1.0) * np.pi / 4.0)
        wet = np.empty_like(samples)
        wet[:, 0] = samples[:, 0] * left
        wet[:, 1] = samples[:, 1] * right
        dry_level, wet_level, output_gain = _effect_levels(self, "Pan", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, 2), frame)


class AudioCompressorNode(FrameNode):
    node_type = "Audio Compressor"
    node_category = AUDIO_CATEGORY
    node_description = "Reduce dynamic range above a threshold"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("threshold", slider_property(70, 1, 100, priority=0, group="Compressor", label="Threshold", description="Compression threshold.", suffix="%"))
        self.set_property("ratio", number_property(4.0, 1.0, 20.0, priority=1, group="Compressor", label="Ratio", description="Compression ratio above threshold.", suffix=":1"))
        self.set_property("makeup_gain", slider_property(100, 0, 200, priority=2, group="Compressor", label="Makeup", description="Output gain after compression.", suffix="%"))
        _add_standard_effect_mix(self, group="Compressor", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        samples = np.asarray(audio.samples, dtype=np.float32)
        threshold = self.float_value("threshold", 70.0) / 100.0
        ratio = max(1.0, self.float_value("ratio", 4.0))
        makeup = self.float_value("makeup_gain", 100.0) / 100.0
        sign = np.sign(samples)
        magnitude = np.abs(samples)
        over = magnitude > threshold
        compressed = np.copy(magnitude)
        compressed[over] = threshold + (compressed[over] - threshold) / ratio
        wet = np.clip(sign * compressed * makeup, -1.0, 1.0)
        dry_level, wet_level, output_gain = _effect_levels(self, "Compressor", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(_ensure_2d(samples), _ensure_2d(wet), dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioLimiterNode(FrameNode):
    node_type = "Audio Limiter"
    node_category = AUDIO_CATEGORY
    node_description = "Hard-limit peaks to prevent clipping"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("ceiling", slider_property(95, 1, 100, priority=0, group="Limiter", label="Ceiling", description="Maximum allowed peak level.", suffix="%"))
        _add_standard_effect_mix(self, group="Limiter", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        ceiling = self.float_value("ceiling", 95.0) / 100.0
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        wet = np.clip(samples, -ceiling, ceiling)
        dry_level, wet_level, output_gain = _effect_levels(self, "Limiter", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioGateNode(FrameNode):
    node_type = "Audio Gate"
    node_category = AUDIO_CATEGORY
    node_description = "Reduce very quiet signal below a threshold"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("threshold", slider_property(4, 0, 40, priority=0, group="Gate", label="Threshold", description="Signals below this level are attenuated.", suffix="%"))
        self.set_property("reduction", slider_property(0, 0, 100, priority=1, group="Gate", label="Reduction", description="Remaining level below the threshold.", suffix="%"))
        _add_standard_effect_mix(self, group="Gate", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        threshold = self.float_value("threshold", 4.0) / 100.0
        reduction = self.float_value("reduction", 0.0) / 100.0
        wet = _apply_audio_gate(samples, threshold, reduction)
        dry_level, wet_level, output_gain = _effect_levels(self, "Gate", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioNormalizeNode(FrameNode):
    node_type = "Audio Normalize"
    node_category = AUDIO_CATEGORY
    node_description = "Scale audio to a target peak level"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("target_peak", slider_property(95, 1, 100, priority=0, group="Normalize", label="Target Peak", description="Desired peak output level.", suffix="%"))
        _add_standard_effect_mix(self, group="Normalize", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0))
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak <= 1e-6:
            return _effect_result(audio, frame)
        target = self.float_value("target_peak", 95.0) / 100.0
        wet = np.clip(samples * (target / peak), -1.0, 1.0)
        dry_level, wet_level, output_gain = _effect_levels(self, "Normalize", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, audio.num_channels), frame)


class AudioStereoWidthNode(FrameNode):
    node_type = "Stereo Width"
    node_category = AUDIO_CATEGORY
    node_description = "Narrow or widen stereo image"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("width", slider_property(100, 0, 200, priority=0, group="Stereo", label="Width", description="0 collapses to mono, 200 exaggerates side information.", suffix="%"))
        _add_standard_effect_mix(self, group="Stereo", wet_default=100)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0), channels=2)
            return _effect_result(silent, frame)
        samples = _ensure_2d(np.asarray(audio.samples, dtype=np.float32))
        if samples.shape[1] == 1:
            samples = np.repeat(samples, 2, axis=1)
        mid = (samples[:, 0] + samples[:, 1]) * 0.5
        side = (samples[:, 0] - samples[:, 1]) * 0.5
        width = self.float_value("width", 100.0) / 100.0
        left = np.clip(mid + side * width, -1.0, 1.0)
        right = np.clip(mid - side * width, -1.0, 1.0)
        wet = np.column_stack((left, right)).astype(np.float32, copy=False)
        dry_level, wet_level, output_gain = _effect_levels(self, "Stereo", default_wet=100.0)
        out = _apply_output_gain(_blend_dry_wet(samples, wet, dry_level, wet_level), output_gain)
        return _effect_result(_wrap_audio(out, audio.sample_rate, 2), frame)


class AudioAdvancedMixerNode(FrameNode):
    node_type = "Advanced Audio Mixer"
    node_category = AUDIO_CATEGORY
    node_description = "Mix up to four audio inputs with per-channel levels, pan, mute, solo, and quality controls"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        for slot in ("a", "b", "c", "d"):
            self.add_input(slot, NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("quality", choice_property(AudioMixQuality.High, priority=0, group="Mixer", label="Quality", description="Resampling quality used to align all inputs."))
        self.set_property("normalize", toggle_property(True, priority=1, group="Mixer", label="Normalize", description="Prevent clipping by reducing summed peaks when needed."))
        self.set_property("master_gain", slider_property(100, 0, 200, priority=2, group="Mixer", label="Master", description="Master output level.", suffix="%"))
        self.set_property("stereo_pan_law", slider_property(100, 50, 150, priority=3, group="Mixer", label="Pan Law", description="How strongly panning attenuates the opposite side.", suffix="%"))
        priority = 10
        for slot in ("a", "b", "c", "d"):
            group = f"Input {slot.upper()}"
            self.set_property(f"{slot}_level", slider_property(100, 0, 200, priority=priority, group=group, label="Level", description=f"Level for input {slot.upper()}.", suffix="%"))
            self.set_property(f"{slot}_pan", slider_property(0, -100, 100, priority=priority + 1, group=group, label="Pan", description=f"Stereo pan for input {slot.upper()}.", suffix="%"))
            self.set_property(f"{slot}_mute", toggle_property(False, priority=priority + 2, group=group, label="Mute", description=f"Mute input {slot.upper()}."))
            self.set_property(f"{slot}_solo", toggle_property(False, priority=priority + 3, group=group, label="Solo", description=f"Solo input {slot.upper()}."))
            priority += 10

    def evaluate(self, frame_num: int) -> AudioData:
        del frame_num
        inputs: dict[str, AudioData] = {}
        for slot in ("a", "b", "c", "d"):
            audio = self.input_audio(slot)
            if audio is not None:
                inputs[slot] = audio
        if not inputs:
            return AudioData.silence(duration=1.0 / max(self._project_fps, 1.0), channels=2)
        quality = self.enum_value("quality", AudioMixQuality, AudioMixQuality.High)
        sample_rate = max(audio.sample_rate for audio in inputs.values())
        channels = max(2, max(audio.num_channels for audio in inputs.values()))
        solo_slots = {slot for slot in inputs if self.bool_value(f"{slot}_solo", False)}
        active_slots = solo_slots if solo_slots else set(inputs)
        target_length = 0
        prepared: dict[str, np.ndarray] = {}
        for slot, audio in inputs.items():
            prepared_samples = _match_audio_layout(audio, sample_rate, channels, quality)
            prepared[slot] = prepared_samples
            target_length = max(target_length, prepared_samples.shape[0])
        mix = np.zeros((target_length, channels), dtype=np.float32)
        pan_law = self.float_value("stereo_pan_law", 100.0) / 100.0
        for slot, samples in prepared.items():
            if slot not in active_slots or self.bool_value(f"{slot}_mute", False):
                continue
            channel_audio = _pad_audio_length(samples, target_length)
            channel_audio = np.copy(channel_audio)
            channel_audio *= self.float_value(f"{slot}_level", 100.0) / 100.0
            if channels >= 2:
                pan = np.clip(self.float_value(f"{slot}_pan", 0.0) / 100.0, -1.0, 1.0)
                left = np.cos((pan + 1.0) * np.pi / 4.0)
                right = np.sin((pan + 1.0) * np.pi / 4.0)
                left = 1.0 - ((1.0 - left) * pan_law)
                right = 1.0 - ((1.0 - right) * pan_law)
                channel_audio[:, 0] *= left
                channel_audio[:, 1] *= right
            mix += channel_audio
        if self.bool_value("normalize", True):
            peak = float(np.max(np.abs(mix))) if mix.size else 0.0
            if peak > 1.0:
                mix = mix / peak
        out = _apply_output_gain(mix, self.float_value("master_gain", 100.0))
        return _wrap_audio(out, sample_rate, channels)


class AudioToMonoNode(FrameNode):
    node_type = "Audio To Mono"
    node_category = AUDIO_CATEGORY
    node_description = "Downmix stereo audio to mono"
    node_color = AUDIO_NODE_COLOR

    def _setup_sockets(self) -> None:
        self.add_input("audio", NodeSocketType.Audio)
        self.add_output("audio", NodeSocketType.Audio)

    def evaluate(self, frame_num: int) -> NodeValue:
        del frame_num
        audio, frame = _input_audio_payload(self, "audio")
        if audio is None:
            silent = AudioData.silence(duration=1.0 / max(self._project_fps, 1.0), channels=1)
            return _effect_result(silent, frame)
        samples = np.asarray(audio.samples, dtype=np.float32)
        if samples.ndim == 1:
            return _effect_result(audio, frame)
        mono = np.mean(samples, axis=1).astype(np.float32, copy=False)
        return _effect_result(AudioData(samples=np.ascontiguousarray(mono), sample_rate=audio.sample_rate), frame)
