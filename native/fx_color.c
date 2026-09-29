#include "aphelion_fx.h"
#include <math.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>

#define AP_OK ((AP_Result){0, "ok"})
#define AP_FAIL(c, m) ((AP_Result){(c), (m)})

static AP_Result validate(const AP_FrameView *src, const AP_FrameView *dst,
                          int allow_exact_inplace)
{
    size_t row_bytes;
    uintptr_t s0, d0, s1, d1;
    if (!src || !dst || !src->data || !dst->data)
        return AP_FAIL(1, "null frame view or data pointer");
    if (src->format != AP_PIXEL_RGB_F32 || dst->format != AP_PIXEL_RGB_F32)
        return AP_FAIL(2, "unsupported pixel format (expected RGB_F32)");
    if (src->width <= 0 || src->height <= 0 || src->width > INT_MAX / 3 || src->width != dst->width ||
        src->height != dst->height)
        return AP_FAIL(3, "invalid or mismatched frame dimensions");
    if ((size_t)src->width > SIZE_MAX / (3 * sizeof(float)))
        return AP_FAIL(3, "frame row size overflows");
    row_bytes = (size_t)src->width * 3 * sizeof(float);
    if (src->stride_bytes < row_bytes || dst->stride_bytes < row_bytes ||
        src->stride_bytes % sizeof(float) != 0 || dst->stride_bytes % sizeof(float) != 0 ||
        (uintptr_t)src->data % sizeof(float) != 0 || (uintptr_t)dst->data % sizeof(float) != 0)
        return AP_FAIL(4, "frame stride or alignment is invalid");
    if ((size_t)(src->height - 1) > (SIZE_MAX - row_bytes) / src->stride_bytes ||
        (size_t)(dst->height - 1) > (SIZE_MAX - row_bytes) / dst->stride_bytes)
        return AP_FAIL(3, "frame buffer size overflows");
    if (src->data_bytes < src->stride_bytes * (size_t)(src->height - 1) + row_bytes ||
        dst->data_bytes < dst->stride_bytes * (size_t)(dst->height - 1) + row_bytes)
        return AP_FAIL(4, "frame buffer is smaller than declared geometry");
    s0 = (uintptr_t)src->data; d0 = (uintptr_t)dst->data;
    if (src->data_bytes > UINTPTR_MAX - s0 || dst->data_bytes > UINTPTR_MAX - d0)
        return AP_FAIL(4, "frame address range overflows");
    s1 = s0 + src->data_bytes; d1 = d0 + dst->data_bytes;
    if (s0 < d1 && d0 < s1 && !(allow_exact_inplace && s0 == d0 &&
        src->stride_bytes == dst->stride_bytes))
        return AP_FAIL(5, "source and destination buffers overlap");
    return AP_OK;
}

static AP_Result validate_params(const float *values, size_t count)
{
    size_t i;
    if (count && !values) return AP_FAIL(6, "null effect parameters");
    for (i = 0; i < count; ++i)
        if (!isfinite(values[i])) return AP_FAIL(6, "effect parameter must be finite");
    return AP_OK;
}

AP_Result aphelion_fx_validate(const AP_FrameView *src, const AP_FrameView *dst)
{
    return validate(src, dst, 0);
}

static float clamp01(float value)
{
    return value < 0.0f ? 0.0f : value > 1.0f ? 1.0f : value;
}

static float luma(const float *rgb)
{
    return rgb[0] * 0.2126f + rgb[1] * 0.7152f + rgb[2] * 0.0722f;
}

static AP_Result pointwise(const AP_FrameView *src, AP_FrameView *dst,
                           AP_FxEffect effect, const float *p)
{
    int y, x, c;
    const float epsilon = 1e-6f;
    for (y = 0; y < src->height; ++y) {
        const float *in = (const float *)((const char *)src->data + (size_t)y * src->stride_bytes);
        float *out = (float *)((char *)dst->data + (size_t)y * dst->stride_bytes);
        for (x = 0; x < src->width; ++x) {
            const float *s = in + 3 * x;
            float *d = out + 3 * x;
            float v[3] = {s[0], s[1], s[2]};
            float lum, value, scale;
            switch (effect) {
            case AP_FX_EXPOSURE_CONTRAST:
                for (c = 0; c < 3; ++c) v[c] = s[c] * p[0] + p[1];
                break;
            case AP_FX_INVERT:
                for (c = 0; c < 3; ++c) v[c] = 1.0f - s[c];
                break;
            case AP_FX_POSTERIZE:
                value = p[0] - 1.0f;
                for (c = 0; c < 3; ++c) v[c] = nearbyintf(s[c] * value) / value;
                break;
            case AP_FX_MONOCHROME:
                value = s[0] * p[0] + s[1] * p[1] + s[2] * p[2];
                v[0] = v[1] = v[2] = value;
                break;
            case AP_FX_THRESHOLD:
                value = s[0] * 0.299f + s[1] * 0.587f + s[2] * 0.114f;
                for (c = 0; c < 3; ++c) v[c] = p[value >= p[0] ? 4 + c : 1 + c];
                break;
            case AP_FX_LEVELS:
                for (c = 0; c < 3; ++c) {
                    value = clamp01((s[c] - p[0]) / p[1]);
                    v[c] = p[3] + powf(value, p[2]) * p[4];
                }
                break;
            case AP_FX_SHADOWS_HIGHLIGHTS:
                lum = s[0] * 0.2126f + s[1] * 0.7152f + s[2] * 0.0722f;
                value = clamp01(1.0f - lum / p[2]);
                scale = clamp01((lum - p[2]) / (1.0f - p[2]));
                for (c = 0; c < 3; ++c) v[c] = clamp01(s[c] + p[0] * value - p[1] * scale);
                break;
            case AP_FX_COLOR_BALANCE:
                lum = s[0] * 0.2126f + s[1] * 0.7152f + s[2] * 0.0722f;
                for (c = 0; c < 3; ++c) v[c] = s[c] + p[c];
                value = v[0] * 0.2126f + v[1] * 0.7152f + v[2] * 0.0722f;
                scale = p[3] != 0.0f && value > 1.0f / 255.0f ? lum / value : 1.0f;
                for (c = 0; c < 3; ++c) v[c] = clamp01(v[c] * scale);
                break;
            case AP_FX_COLOR_GRADE:
                for (c = 0; c < 3; ++c)
                    v[c] = (s[c] * p[0] + p[1]) + p[3 + c];
                lum = luma(v);
                if (p[16] != 0.0f) {
                    value = 1.0f - fabsf(lum - 0.5f) * 2.0f;
                    for (c = 0; c < 3; ++c) {
                        v[c] += p[6 + c] * (1.0f - lum);
                        v[c] *= 1.0f + p[12 + c] * lum;
                        v[c] += p[9 + c] * value * v[c] * 0.35f;
                    }
                    lum = luma(v);
                }
                if (fabsf(p[2] - 1.0f) > epsilon) {
                    for (c = 0; c < 3; ++c) v[c] = (v[c] - lum) * p[2] + lum;
                }
                for (c = 0; c < 3; ++c) {
                    v[c] = clamp01(v[c]);
                    if (p[15] < 1.0f - epsilon) v[c] = v[c] * p[15] + s[c] * (1.0f - p[15]);
                }
                break;
            case AP_FX_CHANNEL_MIXER:
                for (c = 0; c < 3; ++c)
                    v[c] = s[0] * p[c * 3] + s[1] * p[c * 3 + 1] + s[2] * p[c * 3 + 2];
                break;
            case AP_FX_DUOTONE:
                value = s[0] * 0.299f + s[1] * 0.587f + s[2] * 0.114f;
                for (c = 0; c < 3; ++c) v[c] = p[c] + (p[3 + c] - p[c]) * value;
                break;
            case AP_FX_CHROMA_KEY:
                value = sqrtf((s[0]-p[0])*(s[0]-p[0]) + (s[1]-p[1])*(s[1]-p[1]) +
                              (s[2]-p[2])*(s[2]-p[2])) / 1.7320508075688772f;
                value = clamp01((value - p[3]) / p[4]);
                v[0] = v[1] = v[2] = value;
                break;
            case AP_FX_SUPPRESS_SPILL: {
                int dominant = (int)p[0], first = (dominant + 1) % 3, second = (dominant + 2) % 3;
                float other = s[first] > s[second] ? s[first] : s[second];
                v[dominant] = s[dominant] - fmaxf(0.0f, s[dominant] - other) * p[1];
                break;
            }
            case AP_FX_VIGNETTE: {
                float nx = src->width <= 1 ? 0.0f : 2.0f*(float)x/(float)(src->width-1)-1.0f;
                float ny = src->height <= 1 ? 0.0f : 2.0f*(float)y/(float)(src->height-1)-1.0f;
                float dx=nx-(2.0f*p[3]-1.0f),dy=ny-(2.0f*p[4]-1.0f);
                float squash=1.0f+p[2],radius=sqrtf(dx*dx+(dy*squash)*(dy*squash));
                float start=1.0f-p[1],alpha=clamp01((radius-start)/fmaxf(1e-6f,1.0f-start))*p[0];
                for(c=0;c<3;++c)v[c]=s[c]*(1.0f-alpha)+p[5+c]*alpha;
                break;
            }
            case AP_FX_SCANLINES: {
                int step=(int)p[0],band=(int)p[1];
                float phase=fmodf((float)y-p[2],(float)step);
                if(phase<0.0f)phase+=(float)step;
                value=phase<(float)band?clamp01(p[4]):1.0f;
                for(c=0;c<3;++c)v[c]=clamp01(s[c]*value);
                break;
            }
            case AP_FX_HSV_ADJUST:
                v[0] = fmodf(s[0] + p[0], 360.0f);
                if (v[0] < 0.0f) v[0] += 360.0f;
                v[1] = clamp01(s[1] * p[1]);
                break;
            case AP_FX_VIBRANCE:
                value = p[0] * (1.0f - s[1]);
                if (p[1] != 0.0f && s[0] >= 0.0f && s[0] <= 25.0f) value *= .35f;
                v[1] = clamp01(s[1] * (1.0f + value));
                break;
            case AP_FX_CHANNEL_MASK:
                value = p[0] < 0.0f ? s[0]*.299f+s[1]*.587f+s[2]*.114f : s[(int)p[0]];
                value = clamp01((value-p[1])*p[2]);
                if (p[3] != 0.0f) value = 1.0f-value;
                v[0]=v[1]=v[2]=value;
                break;
            case AP_FX_DEPTH_SLICE:
                value = s[0]*.299f+s[1]*.587f+s[2]*.114f;
                value = clamp01((value-p[0])/p[2]) * clamp01((p[1]-value)/p[2]);
                if(p[3]!=0.0f)value=1.0f-value;
                v[0]=v[1]=v[2]=value;
                break;
            case AP_FX_HIGHLIGHTS:
                value = clamp01((s[0]*.299f+s[1]*.587f+s[2]*.114f-p[0])/p[1]);
                v[0]=v[1]=v[2]=value;
                break;
            case AP_FX_INPUT_COLOR:
                for(c=0;c<3;++c) {
                    value=s[c];
                    if(p[0]==1.0f)value=value<=.04045f?value/12.92f:powf((value+.055f)/1.055f,2.4f);
                    else if(p[0]==2.0f)value=fmaxf(0.0f,powf(10.0f,(value-.0928f)/.2472f)-.01f);
                    v[c]=value;
                }
                break;
            case AP_FX_CLIP_AFFINE:
                for(c=0;c<3;++c)v[c]=clamp01(s[c]*p[0]+p[1]);
                break;
            default:
                return AP_FAIL(2, "unsupported effect");
            }
            d[0] = v[0]; d[1] = v[1]; d[2] = v[2];
        }
    }
    return AP_OK;
}

AP_Result aphelion_fx_apply(const AP_FrameView *src, AP_FrameView *dst,
                            AP_FxEffect effect, const float *parameters,
                            size_t parameter_count)
{
    static const size_t counts[] = {0, 2, 0, 1, 3, 7, 5, 3, 4, 17, 9, 6, 5, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 8, 5, 0, 2, 2, 4, 4, 2, 1, 2};
    AP_Result result;
    size_t expected;
    if (effect < AP_FX_EXPOSURE_CONTRAST ||
        (effect > AP_FX_SUPPRESS_SPILL && effect < AP_FX_VIGNETTE) ||
        effect == AP_FX_TILE || effect > AP_FX_CLIP_AFFINE)
        return AP_FAIL(2, "unknown pointwise effect");
    expected = counts[effect];
    if (parameter_count != expected || (expected && !parameters))
        return AP_FAIL(6, "invalid effect parameter count");
    result = validate_params(parameters, parameter_count);
    if (result.code) return result;
    result = validate(src, dst, 1);
    if (result.code) return result;
    if ((effect == AP_FX_CHANNEL_MASK && (parameters[0] < -1.0f || parameters[0] > 2.0f || parameters[0] != (float)(int)parameters[0])) ||
        (effect == AP_FX_DEPTH_SLICE && parameters[2] <= 0.0f) ||
        (effect == AP_FX_HIGHLIGHTS && parameters[1] <= 0.0f) ||
        (effect == AP_FX_POSTERIZE && (parameters[0] < 2.0f || parameters[0] > 32.0f)) ||
        (effect == AP_FX_LEVELS && (parameters[1] <= 0.0f || parameters[2] <= 0.0f)) ||
        (effect == AP_FX_SHADOWS_HIGHLIGHTS && (parameters[2] <= 0.0f || parameters[2] >= 1.0f)) ||
        (effect == AP_FX_CHROMA_KEY && parameters[4] <= 0.0f) ||
        (effect == AP_FX_SUPPRESS_SPILL && (parameters[0] < 0.0f || parameters[0] > 2.0f ||
                                            parameters[0] != (float)(int)parameters[0])) ||
        (effect == AP_FX_COLOR_BALANCE && parameters[3] != 0.0f && parameters[3] != 1.0f) ||
        (effect == AP_FX_COLOR_GRADE && (parameters[15] < 0.0f || parameters[15] > 1.0f ||
                                         (parameters[16] != 0.0f && parameters[16] != 1.0f))) ||
        (effect == AP_FX_VIGNETTE && (parameters[0] < 0.0f || parameters[0] > 1.0f ||
                                      parameters[1] < 0.0f || parameters[1] > 1.0f ||
                                      parameters[2] < -0.95f || parameters[2] > 1.0f ||
                                      parameters[3] < 0.0f || parameters[3] > 1.0f ||
                                      parameters[4] < 0.0f || parameters[4] > 1.0f)) ||
        (effect == AP_FX_SCANLINES && (parameters[0] < 2.0f || parameters[0] > 100000.0f ||
                                       parameters[1] < 1.0f || parameters[1] >= parameters[0])))
        return AP_FAIL(6, "effect parameter outside supported range");
    return pointwise(src, dst, effect, parameters);
}

AP_Result ap_fx_exposure_contrast(const AP_FrameView *src, AP_FrameView *dst,
                                  float gain, float offset)
{
    const float params[2] = {gain, offset};
    return aphelion_fx_apply(src, dst, AP_FX_EXPOSURE_CONTRAST, params, 2);
}

AP_Result ap_fx_invert(const AP_FrameView *src, AP_FrameView *dst)
{
    return aphelion_fx_apply(src, dst, AP_FX_INVERT, NULL, 0);
}

AP_Result ap_fx_posterize(const AP_FrameView *src, AP_FrameView *dst, int levels)
{
    const float params[1] = {(float)levels};
    return aphelion_fx_apply(src, dst, AP_FX_POSTERIZE, params, 1);
}

AP_Result ap_fx_monochrome(const AP_FrameView *src, AP_FrameView *dst,
                           float red_weight, float green_weight, float blue_weight)
{
    float params[3] = {red_weight, green_weight, blue_weight};
    float total = red_weight + green_weight + blue_weight;
    if (total <= 1e-6f) {
        params[0] = 0.2126f; params[1] = 0.7152f; params[2] = 0.0722f;
    } else {
        params[0] /= total; params[1] /= total; params[2] /= total;
    }
    return aphelion_fx_apply(src, dst, AP_FX_MONOCHROME, params, 3);
}

AP_Result ap_fx_threshold(const AP_FrameView *src, AP_FrameView *dst,
                          float level, const float low_rgb[3], const float high_rgb[3])
{
    float params[7];
    int c;
    if (!low_rgb || !high_rgb) return AP_FAIL(1, "null threshold color");
    params[0] = level;
    for (c = 0; c < 3; ++c) { params[1+c] = low_rgb[c]; params[4+c] = high_rgb[c]; }
    return aphelion_fx_apply(src, dst, AP_FX_THRESHOLD, params, 7);
}

AP_Result aphelion_fx_blend(const AP_FrameView *bg, const AP_FrameView *fg,
                           const AP_FrameView *mask, AP_FrameView *dst, int mode, float opacity)
{
    AP_Result result = validate(bg, dst, 0);
    int y, x, channel;
    if (result.code) return result;
    result = validate(fg, dst, 0);
    if (result.code) return result;
    if (mask) { result = validate(mask, dst, 0); if (result.code) return result; }
    if (mode < 0 || mode > 8 || !isfinite(opacity) || opacity < 0.0f || opacity > 1.0f)
        return AP_FAIL(6, "invalid blend mode or opacity");
    for (y = 0; y < bg->height; ++y) {
        const float *b = (const float *)((const char *)bg->data + (size_t)y * bg->stride_bytes);
        const float *f = (const float *)((const char *)fg->data + (size_t)y * fg->stride_bytes);
        const float *m = mask ? (const float *)((const char *)mask->data + (size_t)y * mask->stride_bytes) : NULL;
        float *d = (float *)((char *)dst->data + (size_t)y * dst->stride_bytes);
        for (x = 0; x < bg->width; ++x) {
            float alpha = m ? (m[3*x]*0.299f + m[3*x+1]*0.587f + m[3*x+2]*0.114f)*opacity : opacity;
            for (channel = 0; channel < 3; ++channel) {
                int i = 3*x + channel;
                float value = f[i];
                switch (mode) {
                case 1: value = b[i] + f[i]; break;
                case 2: value = b[i] - f[i]; break;
                case 3: value = b[i] * f[i]; break;
                case 4: value = 1.0f - (1.0f-b[i])*(1.0f-f[i]); break;
                case 5: value = b[i] < .5f ? 2.0f*b[i]*f[i] : (1.0f-(1.0f-b[i])*(1.0f-f[i]))*2.0f-1.0f; break;
                case 6: value = fabsf(b[i] - f[i]); break;
                case 7: value = fminf(b[i], f[i]); break;
                case 8: value = fmaxf(b[i], f[i]); break;
                }
                if (mode) value = clamp01(value);
                d[i] = b[i]*(1.0f-alpha) + value*alpha;
            }
        }
    }
    return AP_OK;
}
