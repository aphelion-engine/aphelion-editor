#ifndef APHELION_FX_H
#define APHELION_FX_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum AP_PixelFormat {
    AP_PIXEL_RGB_F32 = 1,
    AP_PIXEL_GRAY_F32 = 2
} AP_PixelFormat;

typedef struct AP_FrameView {
    void *data;
    size_t data_bytes;
    int width;
    int height;
    size_t stride_bytes;
    AP_PixelFormat format;
} AP_FrameView;

typedef struct AP_Result {
    int code;
    const char *message;
} AP_Result;

typedef enum AP_FxEffect {
    AP_FX_EXPOSURE_CONTRAST = 1,
    AP_FX_INVERT,
    AP_FX_POSTERIZE,
    AP_FX_MONOCHROME,
    AP_FX_THRESHOLD,
    AP_FX_LEVELS,
    AP_FX_SHADOWS_HIGHLIGHTS,
    AP_FX_COLOR_BALANCE,
    AP_FX_COLOR_GRADE,
    AP_FX_CHANNEL_MIXER,
    AP_FX_DUOTONE,
    AP_FX_CHROMA_KEY,
    AP_FX_SUPPRESS_SPILL,
    AP_FX_KALEIDOSCOPE,
    AP_FX_TWIRL,
    AP_FX_BULGE,
    AP_FX_RIPPLE,
    AP_FX_WAVE_WARP,
    AP_FX_OFFSET,
    AP_FX_MIRROR,
    AP_FX_SHOCKWAVE,
    AP_FX_BEND,
    AP_FX_RGB_SPLIT,
    AP_FX_CHROMATIC_ABERRATION,
    AP_FX_VIGNETTE,
    AP_FX_SCANLINES,
    AP_FX_TILE,
    AP_FX_HSV_ADJUST,
    AP_FX_VIBRANCE,
    AP_FX_CHANNEL_MASK,
    AP_FX_DEPTH_SLICE,
    AP_FX_HIGHLIGHTS,
    AP_FX_INPUT_COLOR,
    AP_FX_CLIP_AFFINE
} AP_FxEffect;

/* Stable ABI: caller-owned float32 RGB buffers, no native allocation. */
AP_Result aphelion_fx_validate(const AP_FrameView *src, const AP_FrameView *dst);
AP_Result aphelion_fx_cube(const AP_FrameView *src, AP_FrameView *dst,
                          const float *table, size_t table_bytes, int size, float strength);
AP_Result aphelion_fx_extended(const AP_FrameView *src, const AP_FrameView *aux,
                              const AP_FrameView *aux2, AP_FrameView *dst,
                              int operation, const float *parameters, size_t count);
AP_Result aphelion_fx_blend(const AP_FrameView *background, const AP_FrameView *foreground,
                           const AP_FrameView *mask, AP_FrameView *dst, int mode, float opacity);
AP_Result aphelion_fx_apply(const AP_FrameView *src, AP_FrameView *dst,
                            AP_FxEffect effect, const float *parameters,
                            size_t parameter_count);
AP_Result aphelion_fx_geometry(const AP_FrameView *src, AP_FrameView *dst,
                               AP_FxEffect effect, const float *parameters,
                               size_t parameter_count);
AP_Result ap_fx_exposure_contrast(const AP_FrameView *src, AP_FrameView *dst,
                                  float gain, float offset);
AP_Result ap_fx_invert(const AP_FrameView *src, AP_FrameView *dst);
AP_Result ap_fx_posterize(const AP_FrameView *src, AP_FrameView *dst,
                          int levels);
AP_Result ap_fx_monochrome(const AP_FrameView *src, AP_FrameView *dst,
                           float red_weight, float green_weight,
                           float blue_weight);
AP_Result ap_fx_threshold(const AP_FrameView *src, AP_FrameView *dst,
                          float level, const float low_rgb[3],
                          const float high_rgb[3]);

#ifdef __cplusplus
}
#endif
#endif
