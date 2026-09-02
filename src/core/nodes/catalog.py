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
from core.nodes.compositing import (
    DissolveNode,
    MergeNode,
    AlphaOverNode,
    AlphaUnderNode,
    StencilNode,
    MatteCombineProNode,
)

from core.nodes.creative_nodes import (
    ChromaticAberrationNode,
    GlitchNode,
    KaleidoscopeNode,
    LensDistortionNode,
    MirrorNode,
    RGBSplitNode,
    RippleNode,
    Transform3DNode,
    GlowNode,
    LightWrapNode,
    GlowEdgesNode,
    PosterEdgesNode,
    HalftoneNode,
    VHSNode,
)

from core.nodes.distort_nodes import (
    BulgeNode,
    TileNode,
    TwirlNode,
    WaveWarpNode,
    DisplaceNode,
    DirectionalDisplaceNode
)
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
    RampNode,
    UVMapNode,
    LensFlareNode,
    HeatDistortionNode,
    FogNode,
    NoiseNode,
    VolumetricLightNode,
    ZFogNode
)
from core.nodes.depth_generator_nodes import (
    DepthRampNode,
    DepthNoiseNode,
    DepthShapeNode,
    DepthGradientNode,
    NormalFromDepthNode,
    NormalShapeNode,
    PositionMapNode,
    CameraDepthNode,
    HeightMapNode,
    DisplacementMapNode,
    UVGridNode,
    UVSphereNode,
    VolumeNoiseNode,
    VolumeSliceNode,
)

from core.nodes.image_input import ImageInputNode
from core.nodes.keying_nodes import (
    ChromaKeyNode,
    CombineMasksNode,
    MatteEdgeNode,
    SpillSuppressNode,
    PremultNode,
    CleanPlateNode,
    DespillProNode,
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
from core.nodes.tracking_nodes import (
    PlanarTrackerNode,
    TrackerNode,
    SurfaceTrackerNode,
    PlanarHomographyTrackerNode,
)

from core.nodes.transform_nodes import (
    CornerPinMaskNode,
    CornerPinNode,
    CropNode,
    Transform2DNode,
    SphericalWarpNode,
    PolarWarpNode,
    SwirlNode,
    ShearNode,
    PerspectiveNode,
)

from core.nodes.depth_nodes import (
    DepthDisplaceNode,
    DepthRimLightNode,
    DepthEdgeNode,
    DepthParallaxNode,
    DepthTiltShiftNode,
    ZFogAdvancedNode,
    ZGlowAdvancedNode,
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
    RampNode,
    UVMapNode,
    LensFlareNode,
    HeatDistortionNode,
    FogNode,
    NoiseNode,
    VolumetricLightNode,
    ZFogNode,

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
    AlphaOverNode,
    AlphaUnderNode,
    StencilNode,
    MatteCombineProNode,
    # Transform
    Transform2DNode,
    Transform3DNode,
    CropNode,
    CornerPinNode,
    CornerPinMaskNode,
    SphericalWarpNode,
    PolarWarpNode,
    SwirlNode,
    ShearNode,
    PerspectiveNode,
    # Creative
    KaleidoscopeNode,
    MirrorNode,
    LensDistortionNode,
    ChromaticAberrationNode,
    RGBSplitNode,
    GlitchNode,
    RippleNode,
    GlowNode,
    LightWrapNode,
    GlowEdgesNode,
    PosterEdgesNode,
    HalftoneNode,
    VHSNode,
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
    DisplaceNode,
    DirectionalDisplaceNode,
    # Effects / stylize
    FilmGrainNode,
    ScanlinesNode,
    BloomNode,
    RadialBlurNode,
    # Depth-based effects
    DepthDisplaceNode,
    DepthRimLightNode,
    DepthEdgeNode,
    DepthParallaxNode,
    DepthTiltShiftNode,
    ZFogAdvancedNode,
    ZGlowAdvancedNode,
    # Depth-Generators
    DepthRampNode,
    DepthNoiseNode,
    DepthShapeNode,
    DepthGradientNode,
    NormalFromDepthNode,
    NormalShapeNode,
    PositionMapNode,
    CameraDepthNode,
    HeightMapNode,
    DisplacementMapNode,
    UVGridNode,
    UVSphereNode,
    VolumeNoiseNode,
    VolumeSliceNode,
    # Routing / keying utilities
    FrameSwitchNode,
    ChannelMaskNode,
    InvertMaskNode,
    ChromaKeyNode,
    SpillSuppressNode,
    MatteEdgeNode,
    CombineMasksNode,
    PremultNode,
    CleanPlateNode,
    DespillProNode,

    # Roto
    RotoNode,
    # Tracking
    TrackerNode,
    PlanarTrackerNode,
    # SurfaceTrackerNode,
    # PlanarHomographyTrackerNode,

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
