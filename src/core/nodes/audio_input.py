"""Audio file source with sample-accurate timeline mapping."""
from __future__ import annotations
import numpy as np
from core.audio import AudioData, frame_sample_bounds
from core.nodes.base import NodeProperty, NodePropertyInputType, NodeSocketType
from core.nodes.frame_base import FrameNode
from core.nodes.property_factory import number_property, slider_property, toggle_property
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
        self.set_property("file_path", NodeProperty(NodePropertyInputType.File, "", label="Audio File"))
        self.set_property("enabled", toggle_property(True, label="Enabled"))
        self.set_property("gain", slider_property(100, 0, 300, label="Gain", suffix="%"))
        self.set_property("start_seconds", number_property(0, 0, 86400, label="Source Start", suffix=" s"))
        self.set_property("offset_frames", number_property(0, -100000, 100000, label="Timeline Offset", suffix=" fr"))
        self.set_property("speed", number_property(1, .01, 16, label="Speed"))
        self.set_property("loop", toggle_property(False, label="Loop"))
        self.set_property("reverse", toggle_property(False, label="Reverse"))

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
