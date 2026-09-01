"""Viewer node — preview sink with playback/display settings."""

from __future__ import annotations

import numpy as np

from config.constants import DEFAULT_MAX_PREFETCH_FRAMES, DEFAULT_PREVIEW_MAX_WIDTH
from core.audio import AudioData, FrameWithAudio
from core.nodes.base import Node, NodeProperty, NodePropertyInputType, NodeSocketType
from render.preview import ViewerBackground, ViewportFitMode


class ViewerNode(Node):
    """Connects to an input source to view a video stream."""

    node_type = "Viewer"
    node_category = "Input/Output"
    node_description = "Connects to an input source to view a video stream"
    node_color = (200, 50, 50)

    def _setup_sockets(self) -> None:
        self.add_input("frame", NodeSocketType.Frame)
        self.set_property(
            "enabled",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=0,
                group="Display",
                label="Enabled",
                description="Show the connected frame in the viewport.",
            ),
        )
        self.set_property(
            "fit_mode",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=ViewportFitMode.Fit,
                priority=10,
                group="Display",
                label="Fit",
                description="How the frame is fitted inside the viewport.",
            ),
        )
        self.set_property(
            "preview_max_width",
            NodeProperty(
                input_type=NodePropertyInputType.Slider,
                value=DEFAULT_PREVIEW_MAX_WIDTH,
                slider_min_value=320,
                slider_max_value=1920,
                priority=20,
                group="Performance",
                label="Proxy Width",
                description="Maximum decode width used for interactive preview.",
                suffix=" px",
            ),
        )
        self.set_property(
            "apply_exposure",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=30,
                group="Display Transform",
                label="Apply Exposure",
                description="Apply the viewer-only exposure multiplier.",
            ),
        )
        self.set_property(
            "exposure",
            NodeProperty(
                input_type=NodePropertyInputType.Slider,
                value=100,
                slider_min_value=25,
                slider_max_value=200,
                priority=31,
                group="Display Transform",
                label="Exposure",
                description="Viewer-only display gain.",
                suffix="%",
            ),
        )
        self.set_property(
            "flip_horizontal",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=False,
                priority=40,
                group="Display Transform",
                label="Flip H",
                description="Mirror the preview horizontally.",
            ),
        )
        self.set_property(
            "flip_vertical",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=False,
                priority=41,
                group="Display Transform",
                label="Flip V",
                description="Mirror the preview vertically.",
            ),
        )
        self.set_property(
            "background",
            NodeProperty(
                input_type=NodePropertyInputType.CustomChoice,
                value=ViewerBackground.Black,
                priority=50,
                group="Display",
                label="Background",
                description="Viewport background behind the displayed frame.",
            ),
        )
        self.set_property(
            "prefetch_frames",
            NodeProperty(
                input_type=NodePropertyInputType.Number,
                value=min(6, DEFAULT_MAX_PREFETCH_FRAMES),
                slider_min_value=0,
                slider_max_value=12,
                priority=60,
                group="Performance",
                label="Prefetch",
                description="Frames requested ahead during playback.",
                suffix=" fr",
            ),
        )
        self.set_property(
            "audio_enabled",
            NodeProperty(
                input_type=NodePropertyInputType.Checkbox,
                value=True,
                priority=70,
                group="Audio",
                label="Enabled",
                description="Enable audio playback in the viewer.",
            ),
        )
        self.set_property(
            "audio_volume",
            NodeProperty(
                input_type=NodePropertyInputType.Slider,
                value=1.0,
                slider_min_value=0.0,
                slider_max_value=2.0,
                priority=71,
                group="Audio",
                label="Volume",
                description="Master audio volume for preview playback.",
                suffix="×",
            ),
        )

    def _bool_prop(self, key: str, default: bool) -> bool:
        prop = self.get_property(key)
        if prop is None or prop.value is None:
            return default
        return bool(prop.value)

    def evaluate(self, frame_num: int) -> np.ndarray | FrameWithAudio:
        """Return the connected frame with optional exposure / flips and audio."""
        del frame_num
        if not self._bool_prop("enabled", True):
            return self.blank_frame()

        input_frame: object | None = self.get_input_value("frame")

        # Handle FrameWithAudio input
        if isinstance(input_frame, FrameWithAudio):
            frame = input_frame.frame
            audio = input_frame.audio
        elif isinstance(input_frame, np.ndarray):
            frame = input_frame
            audio = None
        else:
            return self.blank_frame()

        # Apply display transforms
        if self._bool_prop("flip_horizontal", False):
            frame = np.ascontiguousarray(np.fliplr(frame))
        if self._bool_prop("flip_vertical", False):
            frame = np.ascontiguousarray(np.flipud(frame))

        if not self._bool_prop("apply_exposure", True):
            # Apply audio volume if we have audio
            if audio is not None and self._bool_prop("audio_enabled", True):
                audio = self._apply_viewer_volume(audio)
            return FrameWithAudio(frame=frame, audio=audio) if audio is not None else frame

        exposure_prop = self.get_property("exposure")
        if exposure_prop is None or exposure_prop.value is None:
            if audio is not None and self._bool_prop("audio_enabled", True):
                audio = self._apply_viewer_volume(audio)
            return FrameWithAudio(frame=frame, audio=audio) if audio is not None else frame

        gain = float(exposure_prop.value) / 100.0
        if abs(gain - 1.0) < 0.001:
            if audio is not None and self._bool_prop("audio_enabled", True):
                audio = self._apply_viewer_volume(audio)
            return FrameWithAudio(frame=frame, audio=audio) if audio is not None else frame

        adjusted: np.ndarray = frame * np.float32(gain)

        # Apply audio volume if we have audio
        if audio is not None and self._bool_prop("audio_enabled", True):
            audio = self._apply_viewer_volume(audio)

        return FrameWithAudio(frame=adjusted, audio=audio) if audio is not None else adjusted

    def _apply_viewer_volume(self, audio: AudioData) -> AudioData:
        """Apply viewer volume control to audio."""
        volume_prop = self.get_property("audio_volume")
        if volume_prop is None or volume_prop.value is None:
            return audio

        volume = float(volume_prop.value)
        if volume == 1.0:
            return audio

        samples = audio.samples * volume
        samples = np.clip(samples, -1.0, 1.0)
        return AudioData(samples=samples.astype(np.float32), sample_rate=audio.sample_rate)
