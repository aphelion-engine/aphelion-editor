"""Audio file source with sample-accurate timeline mapping."""
from __future__ import annotations

import numpy as np
from core.audio import AudioData, frame_sample_bounds
from core.nodes.base import NodeProperty, NodePropertyInputType, NodeSocketType
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import (number_property, slider_property,
                                         toggle_property)
from render.audio_decoder import AudioDecoder


class AudioInputNode(FrameNode):
    node_type = "Audio Input"
    node_category = "Input/Output"
    node_description = "Read audio files into the audio graph"
    node_color = (110, 140, 220)
    is_temporal = True

    def __init__(self, name=None):
        self._decoder = AudioDecoder()
        super().__init__(name)

    def _setup_sockets(self):
        self.add_output("audio", NodeSocketType.Audio)
        self.set_property("file_path", NodeProperty(
            input_type=NodePropertyInputType.File,
            value="",
            priority=0,
            group="Source",
            label="Audio File",
            description="Audio file decoded by this source node.",
        ))
        self.set_property("enabled", toggle_property(
            True, priority=1, group="Source", label="Enabled",
            description="Disable decoding without removing graph connections."))
        self.set_property("gain", slider_property(
            100, 0, 300, priority=2, group="Source", label="Gain",
            description="Linear output gain.", suffix="%"))
        self.set_property("start_seconds", number_property(
            0, 0, 86400, priority=10, group="Timing", label="Source Start",
            description="Time offset into the source file.", suffix=" s"))
        self.set_property("offset_frames", number_property(
            0, -100000, 100000, priority=11, group="Timing", label="Timeline Offset",
            description="Project-frame delay before source playback begins.", suffix=" fr"))
        self.set_property("speed", number_property(
            1, .01, 16, priority=12, group="Timing", label="Speed",
            description="Playback speed multiplier."))
        self.set_property("loop", toggle_property(
            False, priority=13, group="Timing", label="Loop",
            description="Loop the source when it runs past its end."))
        self.set_property("reverse", toggle_property(
            False, priority=14, group="Timing", label="Reverse",
            description="Read source audio in reverse order."))

    def evaluate(self, frame_num):
        path = self.string_value("file_path")
        info = self._decoder.open(path) if path else None
        rate = info.sample_rate if info else 48000
        channels = info.num_channels if info else 2
        first, last = frame_sample_bounds(frame_num, self._project_fps, rate)
        if not info or not info.has_audio or not self.bool_value("enabled", True):
            return AudioData(np.zeros((last - first, channels), np.float32), rate)
        start = self.float_value("start_seconds", 0)
        length = max(0.0, info.duration_sec - start)
        times = np.arange(first, last, dtype=np.float64) / rate
        local = (times - self.float_value("offset_frames", 0) / self._project_fps) * self.float_value("speed", 1)
        if self.bool_value("loop", False) and length > 0:
            local %= length
        if self.bool_value("reverse", False):
            local = length - 1 / rate - local
        local[(local < 0) | (local >= length)] = -1 - start
        audio = self._decoder.sample_at_times(local + start)
        return AudioData(np.asarray(audio.samples * (self.float_value("gain", 100) / 100), dtype=np.float32), rate)
