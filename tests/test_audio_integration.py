"""Test audio integration with video streaming and export."""

import numpy as np
import pytest

from core.audio import AudioData, FrameWithAudio
from core.project import Project
from core.nodes.audio_nodes import AudioAttachNode, AudioEqNode, AudioExtractNode, AudioGainNode, AudioReverbNode
from core.nodes.base import Node, NodeSocketType
from core.nodes.viewer import ViewerNode


def test_audio_data_creation():
    """Test basic AudioData creation and properties."""
    # Create silence audio
    audio = AudioData.silence(duration=1.0, sample_rate=48000, channels=2)
    assert audio.sample_rate == 48000
    assert audio.num_channels == 2
    assert audio.num_samples == 48000
    assert audio.duration == 1.0
    assert audio.is_silent()


def test_audio_data_validation():
    """Test AudioData validation."""
    samples = np.zeros(48000, dtype=np.float32)
    audio = AudioData(samples=samples, sample_rate=48000)
    assert audio.sample_rate == 48000
    assert audio.num_samples == 48000

    # Test invalid dtype
    with pytest.raises(TypeError):
        AudioData(samples=np.zeros(48000, dtype=np.float64), sample_rate=48000)

    # Test invalid sample rate
    with pytest.raises(ValueError):
        AudioData(samples=samples, sample_rate=0)


def test_audio_data_serialization():
    """Test AudioData serialization/deserialization."""
    samples = np.random.rand(48000).astype(np.float32) * 0.1
    audio = AudioData(samples=samples, sample_rate=48000)

    # Serialize
    data_bytes = audio.to_bytes()
    assert len(data_bytes) == 48000 * 4  # 4 bytes per float32

    # Deserialize
    restored = AudioData.from_bytes(data_bytes, sample_rate=48000, num_channels=1)
    assert restored.sample_rate == 48000
    assert restored.num_samples == 48000
    assert np.allclose(restored.samples, samples)


def test_audio_data_multichannel():
    """Test multi-channel audio data."""
    samples = np.random.rand(48000, 2).astype(np.float32) * 0.1
    audio = AudioData(samples=samples, sample_rate=48000)
    assert audio.num_channels == 2
    assert audio.samples.shape == (48000, 2)


def test_audio_data_silence_threshold():
    """Test silence detection with threshold."""
    # Definitely silent
    silent = AudioData.silence(duration=0.1, sample_rate=48000)
    assert silent.is_silent()

    # Not silent
    samples = np.ones(48000, dtype=np.float32) * 0.5
    loud = AudioData(samples=samples, sample_rate=48000)
    assert not loud.is_silent()

    # Below threshold
    quiet = AudioData(samples=np.ones(48000, dtype=np.float32) * 1e-7, sample_rate=48000)
    assert quiet.is_silent(threshold=1e-6)


def test_frame_with_audio_creation():
    """Test FrameWithAudio creation and properties."""
    # Create a video frame
    frame = np.random.rand(480, 640, 3).astype(np.float32)
    audio = AudioData.silence(duration=1.0, sample_rate=48000, channels=2)

    # Create FrameWithAudio
    frame_with_audio = FrameWithAudio(frame=frame, audio=audio)
    assert frame_with_audio.frame.shape == (480, 640, 3)
    assert frame_with_audio.audio is not None
    assert frame_with_audio.has_audio is False  # Silence is not considered "has audio"

    # Create with loud audio
    loud_audio = AudioData(samples=np.ones(48000, dtype=np.float32) * 0.5, sample_rate=48000)
    frame_with_loud = FrameWithAudio(frame=frame, audio=loud_audio)
    assert frame_with_loud.has_audio is True


def test_frame_with_audio_no_audio():
    """Test FrameWithAudio with None audio."""
    frame = np.random.rand(480, 640, 3).astype(np.float32)
    frame_with_audio = FrameWithAudio(frame=frame, audio=None)

    assert frame_with_audio.audio is None
    assert frame_with_audio.has_audio is False
    assert frame_with_audio.audio_sample_rate == 48000  # Default
    assert frame_with_audio.audio_channels == 2  # Default


def test_frame_with_audio_properties():
    """Test FrameWithAudio property accessors."""
    frame = np.random.rand(480, 640, 3).astype(np.float32)
    audio = AudioData.silence(duration=1.0, sample_rate=44100, channels=1)

    frame_with_audio = FrameWithAudio(frame=frame, audio=audio)
    assert frame_with_audio.audio_sample_rate == 44100
    assert frame_with_audio.audio_channels == 1


def _constant_frame_with_audio_node(frame: np.ndarray, audio: AudioData):
    class ConstantFrameAudioNode(Node):
        node_type = "Constant Frame Audio Test Source"

        def _setup_sockets(self) -> None:
            self.add_output("frame", NodeSocketType.Frame)

        def evaluate(self, frame_num: int):
            del frame_num
            return FrameWithAudio(frame=frame, audio=audio)

    return ConstantFrameAudioNode()


def test_audio_effect_nodes_are_audio_only():
    gain = AudioGainNode()
    eq = AudioEqNode()
    assert set(gain.outputs) == {"audio"}
    assert set(eq.outputs) == {"audio"}


def test_extract_effect_attach_graph_changes_audio():
    frame = np.ones((16, 16, 3), dtype=np.float32) * 0.5
    samples = np.linspace(-0.5, 0.5, 4096, dtype=np.float32)
    audio = AudioData(samples=samples, sample_rate=48000)

    project = Project("audio-extract")
    source_id = project.add_node(_constant_frame_with_audio_node(frame, audio), "source")
    extract_id = project.add_node(AudioExtractNode(), "extract")
    fx_id = project.add_node(AudioEqNode(), "eq")
    attach_id = project.add_node(AudioAttachNode(), "attach")
    viewer_id = project.add_node(ViewerNode(), "viewer")

    project.nodes[fx_id].set_property("preset", 9)
    project.nodes[fx_id].set_property("low_gain", 12)
    project.nodes[fx_id].set_property("mid_gain", -12)
    project.nodes[fx_id].set_property("high_gain", 12)

    assert project.connect_nodes(source_id, "frame", extract_id, "frame")
    assert project.connect_nodes(extract_id, "audio", fx_id, "audio")
    assert project.connect_nodes(extract_id, "frame", attach_id, "frame")
    assert project.connect_nodes(fx_id, "audio", attach_id, "audio")
    assert project.connect_nodes(attach_id, "frame", viewer_id, "frame")

    result = project.evaluate_node(viewer_id, 0)
    assert isinstance(result, FrameWithAudio)
    assert result.audio is not None
    assert np.allclose(result.frame, frame)
    assert not np.allclose(result.audio.samples, samples)


def test_custom_eq_bands_change_audio():
    frame = np.ones((16, 16, 3), dtype=np.float32) * 0.5
    samples = np.zeros(4096, dtype=np.float32)
    samples[256:512] = 0.5
    audio = AudioData(samples=samples, sample_rate=48000)

    project = Project("audio-custom-eq")
    source_id = project.add_node(_constant_frame_with_audio_node(frame, audio), "source")
    extract_id = project.add_node(AudioExtractNode(), "extract")
    fx_id = project.add_node(AudioEqNode(), "eq")
    attach_id = project.add_node(AudioAttachNode(), "attach")
    viewer_id = project.add_node(ViewerNode(), "viewer")

    project.nodes[fx_id].set_property("preset", 9)
    project.nodes[fx_id].set_property(
        "eq_curve",
        {
            "bands": [
                {"freq": 120.0, "gain": 12.0, "q": 0.8},
                {"freq": 3000.0, "gain": -10.0, "q": 1.5},
                {"freq": 9000.0, "gain": 8.0, "q": 1.0},
            ],
            "low": 12.0,
            "mid": -10.0,
            "high": 8.0,
        },
    )

    assert project.connect_nodes(source_id, "frame", extract_id, "frame")
    assert project.connect_nodes(extract_id, "audio", fx_id, "audio")
    assert project.connect_nodes(extract_id, "frame", attach_id, "frame")
    assert project.connect_nodes(fx_id, "audio", attach_id, "audio")
    assert project.connect_nodes(attach_id, "frame", viewer_id, "frame")

    result = project.evaluate_node(viewer_id, 0)
    assert isinstance(result, FrameWithAudio)
    assert result.audio is not None
    assert not np.allclose(result.audio.samples, samples)



def test_extract_reverb_attach_graph_changes_audio():
    frame = np.ones((16, 16, 3), dtype=np.float32) * 0.25
    impulse = np.zeros(4096, dtype=np.float32)
    impulse[0] = 1.0
    audio = AudioData(samples=impulse, sample_rate=48000)

    project = Project("audio-reverb")
    source_id = project.add_node(_constant_frame_with_audio_node(frame, audio), "source")
    extract_id = project.add_node(AudioExtractNode(), "extract")
    fx_id = project.add_node(AudioReverbNode(), "reverb")
    attach_id = project.add_node(AudioAttachNode(), "attach")
    viewer_id = project.add_node(ViewerNode(), "viewer")

    project.nodes[fx_id].set_property("decay", 90)
    project.nodes[fx_id].set_property("pre_delay_ms", 1.0)
    project.nodes[fx_id].set_property("reflections", 6)
    project.nodes[fx_id].set_property("dry", 0)
    project.nodes[fx_id].set_property("wet", 150)

    assert project.connect_nodes(source_id, "frame", extract_id, "frame")
    assert project.connect_nodes(extract_id, "audio", fx_id, "audio")
    assert project.connect_nodes(extract_id, "frame", attach_id, "frame")
    assert project.connect_nodes(fx_id, "audio", attach_id, "audio")
    assert project.connect_nodes(attach_id, "frame", viewer_id, "frame")

    result = project.evaluate_node(viewer_id, 0)
    assert isinstance(result, FrameWithAudio)
    assert result.audio is not None
    assert np.allclose(result.frame, frame)
    assert not np.allclose(result.audio.samples, impulse)
    assert np.count_nonzero(np.abs(result.audio.samples[1:]) > 1e-5) > 0


if __name__ == "__main__":
    # Run basic tests
    test_audio_data_creation()
    print("✓ Audio data creation test passed")

    test_audio_data_validation()
    print("✓ Audio data validation test passed")

    test_audio_data_serialization()
    print("✓ Audio data serialization test passed")

    test_audio_data_multichannel()
    print("✓ Multi-channel audio test passed")

    test_audio_data_silence_threshold()
    print("✓ Silence threshold test passed")

    test_frame_with_audio_creation()
    print("✓ FrameWithAudio creation test passed")

    test_frame_with_audio_no_audio()
    print("✓ FrameWithAudio with no audio test passed")

    test_frame_with_audio_properties()
    print("✓ FrameWithAudio properties test passed")

    print("\nAll audio integration tests passed!")
