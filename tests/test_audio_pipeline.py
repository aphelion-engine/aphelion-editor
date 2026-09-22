"""Graph-to-device/export audio regressions without an audio device."""
import threading
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from core.audio import (AudioData, FrameWithAudio, convert_audio,
                        frame_sample_bounds)
from core.nodes.audio_nodes import (AudioDelayNode, AudioLimiterNode,
                                    AudioMixNode, AudioReverbNode)
from core.nodes.base import Node, NodeSocketType
from core.nodes.video_input import VideoInputNode
from core.nodes.viewer import ViewerNode
from core.project import Project


class Impulse(Node):
    is_temporal = True
    def _setup_sockets(self):
        self.add_output("audio", NodeSocketType.Audio)
    def evaluate(self, frame_num):
        start, stop = frame_sample_bounds(frame_num, self._project_fps, 4800)
        data = np.zeros(stop-start, np.float32)
        if start == 0:
            data[0] = .5
        return AudioData(data, 4800)


def graph(effect):
    project = Project()
    project.fps = 30
    project.width = project.height = 2
    source = project.add_node(Impulse())
    fx = project.add_node(effect)
    viewer = project.add_node(ViewerNode())
    assert project.connect_nodes(source, "audio", fx, "audio")
    assert project.connect_nodes(fx, "audio", viewer, "audio")
    return project, fx, viewer


@pytest.mark.parametrize("export", [False, True])
def test_delay_crosses_frame_boundaries_and_seeks(export):
    delay = AudioDelayNode()
    delay.set_property("delay_ms", 120)
    delay.set_property("feedback", 50)
    delay.set_property("dry", 0)
    delay.set_property("wet", 100)
    project, fx, viewer = graph(delay)
    project.set_export_mode(export)
    blocks = [project.evaluate_node(viewer, f, "audio").samples for f in range(12)]
    samples = np.concatenate(blocks)
    assert samples[576] == pytest.approx(.5)
    assert samples[1152] == pytest.approx(.25)
    assert samples[1728] == pytest.approx(.125)
    assert np.count_nonzero(samples) == 3
    project.clear_cache()
    for f in (10, 3, 7, 3):
        np.testing.assert_array_equal(project.evaluate_node(viewer, f, "audio").samples, blocks[f])


def test_reverb_tail_beyond_input_block():
    reverb = AudioReverbNode()
    reverb.set_property("pre_delay_ms", 70)
    reverb.set_property("dry", 0)
    reverb.set_property("wet", 100)
    project, _, viewer = graph(reverb)
    result = project.evaluate_node(viewer, 2, "audio")
    assert result.samples[16] > 0  # 336 samples = 70ms at 4800Hz


def test_audio_viewer_with_no_video_and_direct_output():
    project, _, viewer = graph(AudioLimiterNode())
    payload = project.evaluate_node(viewer, 0)
    assert isinstance(payload, FrameWithAudio)
    assert payload.audio is not None
    np.testing.assert_array_equal(payload.audio.samples, project.evaluate_node(viewer, 0, "audio").samples)
    assert "audio" in VideoInputNode().outputs


def test_audio_output_does_not_evaluate_unrelated_video():
    class BrokenVideo(Node):
        def _setup_sockets(self): self.add_output("frame", NodeSocketType.Frame)
        def evaluate(self, frame_num): raise AssertionError("video evaluated for audio")
    project, _, viewer = graph(AudioLimiterNode())
    bad = project.add_node(BrokenVideo())
    project.connect_nodes(bad, "frame", viewer, "frame")
    assert isinstance(project.evaluate_node(viewer, 0, "audio"), AudioData)
    assert not project.nodes[bad].exception_log


def test_limiter_defaults_process_instead_of_adding_dry_signal():
    node = AudioLimiterNode()
    node.set_input_value("audio", AudioData(np.ones(8, np.float32), 48000))
    node.set_property("ceiling", 20)
    np.testing.assert_allclose(node.evaluate(0)["audio"].samples, .2)
    node.set_property("enabled", False)
    np.testing.assert_allclose(node.evaluate(0)["audio"].samples, 1)


def test_mixer_does_not_mutate_shared_inputs_and_honors_single_input_controls():
    node = AudioMixNode()
    source = AudioData(np.full(10, .5, np.float32), 48000)
    node.set_input_value("a", source)
    node.set_input_value("b", source)
    node.set_property("a_level", 50)
    node.evaluate(0)
    np.testing.assert_allclose(source.samples, .5)
    node.clear_input_values()
    node.set_input_value("a", source)
    node.set_property("mix", 0)
    node.set_property("output_gain", 50)
    np.testing.assert_allclose(node.evaluate(0).samples, .125)


def test_sample_boundaries_do_not_drift():
    fps = 30000/1001
    count = sum(b-a for a,b in (frame_sample_bounds(f, fps, 44100) for f in range(30000)))
    assert count == 44100*1001
    assert AudioData(np.zeros(0, np.float32), 48000).is_silent()


def test_device_queue_mono_duplication_and_backpressure():
    from render.audio_playback import AudioPlaybackEngine
    engine = AudioPlaybackEngine()
    engine._playing = True  # Test queue without starting a device.
    engine.set_buffer_size(1)
    audio = AudioData(np.full(10, .25, np.float32), 48000)
    assert engine.feed_audio(audio)
    assert not engine.feed_audio(audio)
    assert len(engine._buffer) == 1
    np.testing.assert_allclose(engine._buffer[0], .25)
    assert engine._buffer[0].shape == (10,2)
    np.testing.assert_allclose(audio.samples, .25)
    engine._playing = False


def test_graph_audio_producer_is_ordered_and_inserts_silence():
    from render.audio_graph import GraphAudioProducer
    done = threading.Event()
    calls, samples = [], []
    class ProjectProbe:
        fps = 30
        max_frame = 5
        def evaluate_node(self, viewer, frame, slot):
            calls.append((frame, slot))
            if frame == 2: return None
            return AudioData(np.full(1600, frame/10, np.float32), 48000)
    class EngineProbe:
        _preferred_sample_rate = 48000
        _preferred_channels = 2
        buffered_chunks = 0
        def feed_audio(self, audio):
            samples.append(audio.samples.copy())
            if len(samples) == 6: done.set()
            return True
    producer = GraphAudioProducer(ProjectProbe(), EngineProbe())
    producer.start("viewer", 0)
    assert done.wait(3)
    producer.stop()
    assert calls == [(i, "audio") for i in range(6)]
    np.testing.assert_allclose(samples[2], 0)
    np.testing.assert_allclose(samples[5], .5)


def test_stopped_producer_cannot_deliver_stale_audio():
    from render.audio_graph import GraphAudioProducer
    entered, release = threading.Event(), threading.Event()
    samples=[]
    class ProjectProbe:
        fps=30
        max_frame=0
        def evaluate_node(self, *args):
            entered.set()
            release.wait(3)
            return AudioData(np.ones(1600,np.float32),48000)
    engine=SimpleNamespace(_preferred_sample_rate=48000,_preferred_channels=2,buffered_chunks=0,
                           feed_audio=lambda block: samples.append(block) or True)
    producer=GraphAudioProducer(ProjectProbe(),engine)
    producer.start("viewer",0)
    assert entered.wait(3)
    producer.stop()
    release.set()
    producer._thread.join(3)
    assert not samples


def test_export_writes_silence_and_exact_fractional_frame_durations(monkeypatch):
    from render.video_writer import Mp4VideoWriter
    writer=object.__new__(Mp4VideoWriter)
    writer._closed=False
    writer._write_error=None
    writer._frame_queue=SimpleNamespace(put=lambda frame: None)
    writer._include_audio=True
    writer._frame_count=0
    writer._fps=30000/1001
    writer._audio_sample_rate=44100
    writer._audio_channels=2
    writer._audio_lock=threading.Lock()
    writer._audio_buffer=bytearray()
    writer._audio_buffer_bytes=0
    writer._audio_flush_bytes=10**9
    monkeypatch.setattr(Mp4VideoWriter,"_prepare_frame",lambda self, frame: frame)
    frame=np.zeros((2,2,3),np.uint8)
    for index in range(30):
        audio=None if index<10 else AudioData(np.full(2000,.25,np.float32),44100)
        writer.write(frame,audio)
    pcm=np.frombuffer(writer._audio_buffer,np.int16).reshape(-1,2)
    assert len(pcm)==round(30*44100/writer._fps)
    assert not pcm[:round(10*44100/writer._fps)].any()
    assert pcm[-1,0]>0
    writer._closed=True


def test_audio_input_decodes_wav_and_roundtrips(tmp_path):
    from core.nodes.audio_input import AudioInputNode
    from core.nodes.registry import global_node_registry
    path=tmp_path/"tone.wav"
    rate=48000
    tone=(np.sin(np.arange(rate//10)*2*np.pi*440/rate)*10000).astype(np.int16)
    with wave.open(str(path),"wb") as file:
        file.setnchannels(1); file.setsampwidth(2); file.setframerate(rate); file.writeframes(tone.tobytes())
    node=AudioInputNode()
    node.set_property("file_path",str(path))
    node.prepare_evaluation(2,2,project_fps=30,frame_num=0)
    block=node.evaluate(0)
    assert block.num_samples==1600
    assert not block.is_silent()
    project=Project()
    source=project.add_node(node)
    viewer=project.add_node(ViewerNode())
    project.connect_nodes(source,"audio",viewer,"audio")
    global_node_registry.register(AudioInputNode,AudioInputNode.node_category,AudioInputNode.node_type)
    global_node_registry.register(ViewerNode,ViewerNode.node_category,ViewerNode.node_type)
    restored=Project.from_dict(project.to_dict())
    assert restored.nodes[source].node_type=="Audio Input"
    assert isinstance(restored.evaluate_node(viewer,0,"audio"),AudioData)


def test_video_source_audio_mapping_uses_project_sample_clock():
    from render.audio_decoder import AudioDecoder, AudioInfo
    decoder=AudioDecoder()
    decoder._audio_info=AudioInfo(48000,1,1.0)
    decoder._decoded_samples=np.linspace(0,.5,48000,dtype=np.float32)
    node=VideoInputNode()
    node._decoder=SimpleNamespace(read_audio_times=decoder.sample_at_times)
    info=SimpleNamespace(audio_sample_rate=48000,audio_channels=1,frame_count=24,fps=24)
    node._project_fps=30
    blocks=[node._timeline_audio(frame,info).samples for frame in range(30)]
    np.testing.assert_allclose(np.concatenate(blocks),decoder._decoded_samples,atol=1e-6)
    node.set_property("reverse",True)
    assert node._timeline_audio(0,info).samples[0]>.49
