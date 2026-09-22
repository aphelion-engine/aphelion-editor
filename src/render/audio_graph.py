"""Ordered graph audio production, independent of dropped viewport frames."""
from __future__ import annotations

import threading
from core.audio import AudioData, FrameWithAudio, convert_audio, frame_sample_bounds
from utils.logging_setup import get_logger


class GraphAudioProducer:
    """One bounded producer per playback session; stale jobs cannot enqueue audio."""
    def __init__(self, project, engine):
        self.project = project
        self.engine = engine
        self._stop = threading.Event()
        self._thread = None
        self._generation = 0
        self._lock = threading.Lock()

    def start(self, viewer_id: str, frame_num: int) -> None:
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
            stopped = threading.Event()
            self._stop = stopped
        self._thread = threading.Thread(target=self._run, args=(viewer_id, frame_num, generation, stopped), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self._stop.set()
        # Evaluation may be expensive. Never block the Qt thread waiting for it.
        # Generation validation below prevents late results reaching the device.

    def _run(self, viewer_id, frame_num, generation, stopped):
        try:
            while not stopped.is_set() and frame_num <= self.project.max_frame:
                if self.engine.buffered_chunks >= 4:
                    stopped.wait(0.005)
                    continue
                result = self.project.evaluate_node(viewer_id, frame_num, "audio")
                audio = result.audio if isinstance(result, FrameWithAudio) else result
                if not isinstance(audio, AudioData):
                    audio = None
                # Normalize at device rate using absolute timeline boundaries.
                rate = self.engine._preferred_sample_rate
                channels = self.engine._preferred_channels
                start, end = frame_sample_bounds(frame_num, self.project.fps, rate)
                block = convert_audio(audio, rate, channels, end - start)
                while not stopped.is_set():
                    with self._lock:
                        if generation != self._generation:
                            return
                        accepted = self.engine.feed_audio(block)
                    if accepted:
                        break
                    stopped.wait(0.005)
                frame_num += 1
        except Exception:
            get_logger("audio.graph").exception("Graph audio playback failed at frame %s", frame_num)
