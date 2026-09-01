"""Authoritative built-in node catalog grouped by editor purpose."""

from __future__ import annotations

from core.nodes.advanced_color_nodes import (
    ClarityNode,
    ColorBalanceNode,
    LevelsNode,
    ShadowsHighlightsNode,
    VibranceNode,
)
from core.nodes.audio_nodes import (
    AudioAdvancedMixerNode,
    AudioAttachNode,
    AudioCompressorNode,
    AudioDelayNode,
    AudioEqNode,
    AudioExtractNode,
    AudioGainNode,
    AudioGateNode,
    AudioLimiterNode,
    AudioMixNode,
    AudioNormalizeNode,
    AudioPanNode,
    AudioReverbNode,
    AudioStereoWidthNode,
    AudioToMonoNode,
)
from core.nodes.base import Node
from core.nodes.color_effects import (
    ChannelMixerNode,
    ExposureContrastNode,
    HueSaturationNode,
    InvertNode,
    MonochromeNode,
    PosterizeNode,
    ThresholdNode,
    WhiteBalanceNode,
)
from core.nodes.color_grading import ColorGradingNode
from core.nodes.compositing import DissolveNode, MergeNode
from core.nodes.creative_nodes import (
    ChromaticAberrationNode,
    GlitchNode,
    KaleidoscopeNode,
    LensDistortionNode,
    MirrorNode,
    RGBSplitNode,
    RippleNode,
    Transform3DNode,
)
from core.nodes.distort_nodes import BulgeNode, TileNode, TwirlNode, WaveWarpNode
from core.nodes.filter_effects import (
    DenoiseNode,
    EdgeDetectNode,
    GaussianBlurNode,
    MotionBlurNode,
    PixelateNode,
    SharpenNode,
    VignetteNode,
)
from core.nodes.generator_nodes import (
    CheckerboardNode,
    ColorBarsNode,
    GradientNode,
    SolidColorNode,
)
from core.nodes.image_input import ImageInputNode
from core.nodes.keying_nodes import (
    ChromaKeyNode,
    CombineMasksNode,
    MatteEdgeNode,
    SpillSuppressNode,
)
from core.nodes.math_nodes import (
    ClampNode,
    MathFunctionNode,
    MathNode,
    PropertyDriveNode,
    PropertyLinkNode,
    RemapNode,
    ValueNode,
)
from core.nodes.value_nodes import (
    TimelineFpsNode,
    TimelineFrameNode,
    TimelineMaxFrameNode,
    TimelineNormalizedNode,
    TimelineTimeNode,
)
from core.nodes.roto_nodes import RotoNode
from core.nodes.stylize_nodes import BloomNode, FilmGrainNode, RadialBlurNode, ScanlinesNode
from core.nodes.timing_nodes import (
    FilmFlickerNode,
    FrameHoldNode,
    PulseExposureNode,
    StrobeNode,
    TimeRemapNode,
)
from core.nodes.tracking_nodes import PlanarTrackerNode, TrackerNode
from core.nodes.transform_nodes import (
    CornerPinMaskNode,
    CornerPinNode,
    CropNode,
    Transform2DNode,
)
from core.nodes.utility_nodes import ChannelMaskNode, FrameSwitchNode, InvertMaskNode
from core.nodes.video_input import VideoInputNode
from core.nodes.viewer import ViewerNode

BUILTIN_NODE_TYPES: tuple[type[Node], ...] = (
    # Input / output
    VideoInputNode,
    ImageInputNode,
    ViewerNode,
    # Audio
    AudioExtractNode,
    AudioAttachNode,
    AudioGainNode,
    AudioMixNode,
    AudioAdvancedMixerNode,
    AudioDelayNode,
    AudioReverbNode,
    AudioEqNode,
    AudioPanNode,
    AudioCompressorNode,
    AudioLimiterNode,
    AudioGateNode,
    AudioNormalizeNode,
    AudioStereoWidthNode,
    AudioToMonoNode,
    # Generators
    SolidColorNode,
    GradientNode,
    CheckerboardNode,
    ColorBarsNode,
    # Color
    ColorGradingNode,
    ExposureContrastNode,
    HueSaturationNode,
    WhiteBalanceNode,
    ChannelMixerNode,
    LevelsNode,
    VibranceNode,
    ShadowsHighlightsNode,
    ColorBalanceNode,
    ClarityNode,
    MonochromeNode,
    ThresholdNode,
    PosterizeNode,
    InvertNode,
    # Filters
    GaussianBlurNode,
    SharpenNode,
    DenoiseNode,
    EdgeDetectNode,
    PixelateNode,
    VignetteNode,
    MotionBlurNode,
    # Compositing
    MergeNode,
    DissolveNode,
    # Transform
    Transform2DNode,
    Transform3DNode,
    CropNode,
    CornerPinNode,
    CornerPinMaskNode,
    # Creative
    KaleidoscopeNode,
    MirrorNode,
    LensDistortionNode,
    ChromaticAberrationNode,
    RGBSplitNode,
    GlitchNode,
    RippleNode,
    # Timing
    FilmFlickerNode,
    StrobeNode,
    PulseExposureNode,
    TimeRemapNode,
    FrameHoldNode,
    # Distort
    TwirlNode,
    BulgeNode,
    WaveWarpNode,
    TileNode,
    # Effects / stylize
    FilmGrainNode,
    ScanlinesNode,
    BloomNode,
    RadialBlurNode,
    # Routing / keying utilities
    FrameSwitchNode,
    ChannelMaskNode,
    InvertMaskNode,
    ChromaKeyNode,
    SpillSuppressNode,
    MatteEdgeNode,
    CombineMasksNode,
    # Roto
    RotoNode,
    # Tracking
    TrackerNode,
    PlanarTrackerNode,
    # Math / values
    ValueNode,
    TimelineFrameNode,
    TimelineTimeNode,
    TimelineFpsNode,
    TimelineMaxFrameNode,
    TimelineNormalizedNode,
    MathNode,
    MathFunctionNode,
    ClampNode,
    RemapNode,
    PropertyLinkNode,
    PropertyDriveNode,
)
