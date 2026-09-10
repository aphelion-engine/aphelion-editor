"""Optimized frame effects used by built-in nodes."""

from effects.advanced_color import (clarity, color_balance, levels,
                                    shadows_highlights, vibrance)
from effects.color_adjustments import (channel_mixer, exposure_contrast,
                                       hue_saturation, invert, monochrome,
                                       posterize, threshold, white_balance)
from effects.color_grading import apply_color_grade
from effects.compositing import blend_frames, dissolve_frames
from effects.creative import (chromatic_aberration, duotone, glitch,
                              kaleidoscope, lens_distortion, mirror, neon_glow,
                              pixel_sort, rgb_split, ripple, shockwave,
                              transform_3d)
from effects.depth import (anaglyph, depth_haze, depth_of_field, depth_relight,
                           depth_slice)
from effects.distort import (bend, bulge, bump_map, offset, tile, twirl,
                             wave_warp)
from effects.filters import (bilateral_denoise, edge_detect, gaussian_blur,
                             pixelate, unsharp_mask, vignette)
from effects.frame_ops import (color01, ensure_rgb_f32, from_source_u8,
                               mix_frames, resize_like, to_display_u8)
from effects.generators import checkerboard, color_bars, gradient, solid_color
from effects.masks import channel_mask, invert_mask
from effects.smart_color import auto_levels, auto_white_balance, shot_match
from effects.stylize import bloom, film_grain, radial_blur, scanlines
from effects.timing import film_flicker, pulse_exposure, strobe
from effects.transform import crop, transform_2d

__all__ = [
    "anaglyph",
    "apply_color_grade",
    "auto_levels",
    "auto_white_balance",
    "bend",
    "bilateral_denoise",
    "blend_frames",
    "bloom",
    "bulge",
    "bump_map",
    "channel_mask",
    "channel_mixer",
    "checkerboard",
    "chromatic_aberration",
    "clarity",
    "color01",
    "color_balance",
    "color_bars",
    "crop",
    "depth_haze",
    "depth_of_field",
    "depth_relight",
    "depth_slice",
    "dissolve_frames",
    "duotone",
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
    "neon_glow",
    "offset",
    "pixel_sort",
    "pixelate",
    "posterize",
    "pulse_exposure",
    "radial_blur",
    "resize_like",
    "rgb_split",
    "ripple",
    "scanlines",
    "shadows_highlights",
    "shockwave",
    "shot_match",
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
