"""Test audio integration with video streaming and export."""

import numpy as np
import pytest

from core.audio import AudioData, FrameWithAudio


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
