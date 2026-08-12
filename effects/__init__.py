"""Optimized frame effects used by built-in nodes."""

from effects.advanced_color import clarity, color_balance, levels, shadows_highlights, vibrance
from effects.color_adjustments import (
    channel_mixer,
    exposure_contrast,
    hue_saturation,
    invert,
    monochrome,
    posterize,
    threshold,
    white_balance,
)
from effects.color_grading import apply_color_grade
from effects.compositing import blend_frames, dissolve_frames
from effects.creative import (
    chromatic_aberration,
    glitch,
    kaleidoscope,
    lens_distortion,
    mirror,
    rgb_split,
    ripple,
    transform_3d,
)
from effects.distort import bulge, tile, twirl, wave_warp
from effects.filters import (
    bilateral_denoise,
    edge_detect,
    gaussian_blur,
    pixelate,
    unsharp_mask,
    vignette,
)
from effects.frame_ops import color01, ensure_rgb_f32, from_source_u8, mix_frames, resize_like, to_display_u8
from effects.generators import checkerboard, color_bars, gradient, solid_color
from effects.masks import channel_mask, invert_mask
from effects.stylize import bloom, film_grain, radial_blur, scanlines
from effects.timing import film_flicker, pulse_exposure, strobe
from effects.transform import crop, transform_2d

__all__ = [
    "apply_color_grade",
    "bilateral_denoise",
    "blend_frames",
    "bloom",
    "bulge",
    "channel_mask",
    "channel_mixer",
    "checkerboard",
    "chromatic_aberration",
    "clarity",
    "color01",
    "color_balance",
    "color_bars",
    "crop",
    "dissolve_frames",
    "edge_detect",
    "ensure_rgb_f32",
    "exposure_contrast",
    "film_flicker",
    "film_grain",
    "from_source_u8",
    "gaussian_blur",
    "glitch",
    "gradient",
    "hue_saturation",
    "invert",
    "invert_mask",
    "kaleidoscope",
    "lens_distortion",
    "levels",
    "mix_frames",
    "mirror",
    "monochrome",
    "pixelate",
    "posterize",
    "pulse_exposure",
    "radial_blur",
    "resize_like",
    "rgb_split",
    "ripple",
    "scanlines",
    "shadows_highlights",
    "solid_color",
    "strobe",
    "threshold",
    "tile",
    "to_display_u8",
    "transform_2d",
    "transform_3d",
    "twirl",
    "unsharp_mask",
    "vibrance",
    "vignette",
    "wave_warp",
    "white_balance",
]
