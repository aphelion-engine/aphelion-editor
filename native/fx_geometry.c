#include "aphelion_fx.h"
#include <math.h>
#include <stdint.h>
#include <limits.h>

#define AP_FAIL(c, m) ((AP_Result){(c), (m)})
#define AP_OK ((AP_Result){0, "ok"})
#define AP_PI 3.14159265358979323846f

static float clampf(float value, float low, float high)
{
    return value < low ? low : value > high ? high : value;
}

static AP_Result validate_view(const AP_FrameView *view)
{
    size_t row_bytes;
    if (!view || !view->data) return AP_FAIL(1, "null frame view or data pointer");
    if (view->format != AP_PIXEL_RGB_F32) return AP_FAIL(2, "unsupported pixel format (expected RGB_F32)");
    if (view->width <= 0 || view->height <= 0 || view->width > INT_MAX / 3 || view->height > INT_MAX / 2)
        return AP_FAIL(3, "invalid frame dimensions");
    row_bytes = (size_t)view->width * 3 * sizeof(float);
    if (view->stride_bytes < row_bytes || view->stride_bytes % sizeof(float) != 0 ||
        (uintptr_t)view->data % sizeof(float) != 0)
        return AP_FAIL(4, "invalid frame stride or alignment");
    if ((size_t)(view->height - 1) > (SIZE_MAX - row_bytes) / view->stride_bytes ||
        view->data_bytes < view->stride_bytes * (size_t)(view->height - 1) + row_bytes)
        return AP_FAIL(4, "frame storage is smaller than declared geometry");
    return AP_OK;
}

static int reflect101(int value, int size)
{
    int period, folded;
    if (size <= 1) return 0;
    period = 2 * size - 2;
    folded = value % period;
    if (folded < 0) folded += period;
    return folded < size ? folded : period - folded;
}

static float reflect_coord(float value, int size)
{
    float period, folded;
    if (size <= 1) return 0.0f;
    if (!isfinite(value)) return 0.0f;
    period = 2.0f * (float)(size - 1);
    folded = fmodf(value, period);
    if (folded < 0.0f) folded += period;
    return folded < (float)size ? folded : period - folded;
}

static void sample_constant(const AP_FrameView *src, float x, float y, float out[3])
{
    if (!isfinite(x) || !isfinite(y) || x <= -1.0f || y <= -1.0f ||
        x >= (float)src->width || y >= (float)src->height) {
        out[0] = out[1] = out[2] = 0.0f;
        return;
    }
    int x0=(int)floorf(x),y0=(int)floorf(y),c,ox,oy;float fx=x-x0,fy=y-y0;
    for(c=0;c<3;++c){float sum=0.0f;for(oy=0;oy<2;++oy)for(ox=0;ox<2;++ox){int px=x0+ox,py=y0+oy;
        if(px>=0&&px<src->width&&py>=0&&py<src->height){const float *row=(const float *)((const char *)src->data+(size_t)py*src->stride_bytes);float wx=ox?fx:1.0f-fx,wy=oy?fy:1.0f-fy;sum+=row[px*3+c]*wx*wy;}}
        out[c]=sum;}
}

static void sample_replicate(const AP_FrameView *src, float x, float y, float out[3])
{
    x = isfinite(x) ? clampf(x, 0.0f, (float)(src->width - 1)) : 0.0f;
    y = isfinite(y) ? clampf(y, 0.0f, (float)(src->height - 1)) : 0.0f;
    int x0=(int)floorf(x),y0=(int)floorf(y),x1=x0+1,y1=y0+1,c;float fx=x-x0,fy=y-y0;
    x0=x0<0?0:x0>=src->width?src->width-1:x0;x1=x1<0?0:x1>=src->width?src->width-1:x1;
    y0=y0<0?0:y0>=src->height?src->height-1:y0;y1=y1<0?0:y1>=src->height?src->height-1:y1;
    const float *r0=(const float *)((const char *)src->data+(size_t)y0*src->stride_bytes);
    const float *r1=(const float *)((const char *)src->data+(size_t)y1*src->stride_bytes);
    for(c=0;c<3;++c){float top=r0[3*x0+c]+(r0[3*x1+c]-r0[3*x0+c])*fx;float bottom=r1[3*x0+c]+(r1[3*x1+c]-r1[3*x0+c])*fx;out[c]=top+(bottom-top)*fy;}
}

static void sample_linear(const AP_FrameView *src, float x, float y, float out[3])
{
    x = reflect_coord(x, src->width);
    y = reflect_coord(y, src->height);
    int x0 = (int)floorf(x), y0 = (int)floorf(y);
    float fx = x - x0, fy = y - y0;
    int ax = reflect101(x0, src->width), bx = reflect101(x0 + 1, src->width);
    int ay = reflect101(y0, src->height), by = reflect101(y0 + 1, src->height);
    const float *r0 = (const float *)((const char *)src->data + (size_t)ay * src->stride_bytes);
    const float *r1 = (const float *)((const char *)src->data + (size_t)by * src->stride_bytes);
    int c;
    for (c = 0; c < 3; ++c) {
        float top = r0[3*ax+c] + (r0[3*bx+c] - r0[3*ax+c]) * fx;
        float bottom = r1[3*ax+c] + (r1[3*bx+c] - r1[3*ax+c]) * fx;
        out[c] = top + (bottom - top) * fy;
    }
}

static void map_coordinate(AP_FxEffect effect, const float *p, int x, int y,
                           int width, int height, float *sx, float *sy)
{
    float fx=(float)x, fy=(float)y, cx, cy, dx, dy, distance, radius, value;
    switch (effect) {
    case AP_FX_KALEIDOSCOPE: {
        float count=p[0], wedge=2.0f*AP_PI/count;
        cx=p[2]*width; cy=p[3]*height; dx=fx-cx; dy=fy-cy;
        distance=sqrtf(dx*dx+dy*dy);
        value=atan2f(dy,dx)+p[1]*AP_PI/180.0f;
        value=fmodf(value+wedge*.5f,wedge);
        if(value<0.0f)value+=wedge;
        value=fabsf(value-wedge*.5f);
        *sx=cx+distance*cosf(value); *sy=cy+distance*sinf(value); return;
    }
    case AP_FX_TWIRL:
        cx=p[3]*width; cy=p[4]*height; dx=fx-cx; dy=fy-cy;
        radius=fmaxf(8.0f,p[1]*fminf(width,height)*.5f); distance=sqrtf(dx*dx+dy*dy);
        value=clampf(1.0f-distance/radius,0.0f,1.0f)*p[2]*p[0]*AP_PI/180.0f;
        *sx=cx+dx*cosf(value)-dy*sinf(value); *sy=cy+dx*sinf(value)+dy*cosf(value); return;
    case AP_FX_BULGE:
        cx=p[2]*width; cy=p[3]*height; dx=fx-cx; dy=fy-cy;
        radius=fmaxf(8.0f,p[1]*fminf(width,height)*.5f); distance=sqrtf(dx*dx+dy*dy);
        value=1.0f+p[0]*(1.0f-clampf(distance/radius,0.0f,1.0f)*clampf(distance/radius,0.0f,1.0f));
        *sx=cx+dx/(distance>1e-3f?value:1.0f); *sy=cy+dy/(distance>1e-3f?value:1.0f); return;
    case AP_FX_RIPPLE: {
        float wave=sinf((fy/fmaxf(1.0f,(float)height))*p[1]*2.0f*AP_PI+p[2]+p[3]*.15f);
        *sx=fx+wave*p[0]*width*.04f; *sy=fy+wave*p[0]*height*.02f; return;
    }
    case AP_FX_WAVE_WARP: {
        float angle=p[3]*AP_PI/180.0f, ax=cosf(angle), ay=sinf(angle);
        float projection=fx*ax+fy*ay;
        float wave=sinf(projection/fmaxf(1.0f,(float)(width<height?width:height))*p[1]*2.0f*AP_PI+p[2]*AP_PI/180.0f+p[4]*.12f);
        float offset=wave*p[0]*(width<height?width:height)*.04f;
        *sx=fx-offset*ay; *sy=fy+offset*ax; return;
    }
    case AP_FX_OFFSET:
        *sx=fx-nearbyintf(p[0]*width); *sy=fy-nearbyintf(p[1]*height); return;
    case AP_FX_MIRROR: {
        int axis=(int)p[0];
        if(axis==0){int split=(int)floorf(width*clampf(p[1],0,1)+.5f);if(split<1)split=1;if(split>=width)split=width-1;
            if(x>=split)*sx=(float)(2*split-x-1);else *sx=fx;*sy=fy;return;}
        else {int split=(int)floorf(height*clampf(p[1],0,1)+.5f);if(split<1)split=1;if(split>=height)split=height-1;
            *sx=fx;if(y>=split)*sy=(float)(2*split-y-1);else *sy=fy;return;}
    }
    case AP_FX_RGB_SPLIT:
        *sx=fx;*sy=fy;return;
    case AP_FX_CHROMATIC_ABERRATION:
        *sx=fx;*sy=fy;return;
    case AP_FX_SHOCKWAVE: {
        cx=clampf(p[3],0,1)*width;cy=clampf(p[4],0,1)*height;dx=fx-cx;dy=fy-cy;
        distance=sqrtf(dx*dx+dy*dy);radius=fmaxf(1.0f,.5f*hypotf((float)width,(float)height));
        value=clampf(p[0],0,1)*radius;{float band=fmaxf(1.0f,p[2]*radius*.25f);float z=(distance-value)/band;
            float disp=expf(-.5f*z*z)*clampf(1.0f-distance/radius,0,1)*p[1]*(width<height?width:height)*.25f;
            float safe=distance>1e-3f?distance:1.0f;*sx=fx-dx/safe*disp;*sy=fy-dy/safe*disp;return;}
    }
    case AP_FX_BEND: {
        int axis=(int)p[1];float normalized,curve;
        if(axis==0){normalized=height<=1?0.0f:(2.0f*fy/(height-1)-1.0f);curve=1.0f-normalized*normalized;*sx=fx-curve*p[0]*width;*sy=fy;}
        else {normalized=width<=1?0.0f:(2.0f*fx/(width-1)-1.0f);curve=1.0f-normalized*normalized;*sx=fx;*sy=fy-curve*p[0]*height;}
        return;
    }
    default: *sx=fx;*sy=fy;return;
    }
}

AP_Result aphelion_fx_geometry(const AP_FrameView *src, AP_FrameView *dst,
                               AP_FxEffect effect, const float *p, size_t count)
{
    AP_Result result=validate_view(src);int y,x,c;uintptr_t s0,d0;
    size_t expected=0;int wrap=0;
    if(result.code)return result;
    result=validate_view(dst);if(result.code)return result;
    if(src->width!=dst->width || src->height!=dst->height || src->stride_bytes!=dst->stride_bytes)
        return AP_FAIL(3,"geometry effect frame layouts differ");
    if(src->data_bytes > UINTPTR_MAX-(uintptr_t)src->data || dst->data_bytes > UINTPTR_MAX-(uintptr_t)dst->data)
        return AP_FAIL(4,"frame address range overflows");
    if(src->data==dst->data)return AP_FAIL(5,"geometry effect does not support in-place buffers");
    if(src->width > INT_MAX/3)return AP_FAIL(3,"frame dimensions too large");
    s0=(uintptr_t)src->data;d0=(uintptr_t)dst->data;
    if(s0!=d0 && s0<d0+dst->data_bytes && d0<s0+src->data_bytes)
        return AP_FAIL(5,"geometry effect buffers overlap");
    switch(effect){
        case AP_FX_KALEIDOSCOPE: expected=4;break;
        case AP_FX_TWIRL: expected=5;break;
        case AP_FX_BULGE: expected=4;break;
        case AP_FX_RIPPLE: expected=4;break;
        case AP_FX_WAVE_WARP: expected=5;break;
        case AP_FX_OFFSET: expected=3;break;
        case AP_FX_MIRROR: expected=2;break;
        case AP_FX_SHOCKWAVE: expected=5;break;
        case AP_FX_BEND: expected=2;break;
        case AP_FX_RGB_SPLIT: expected=6;break;
        case AP_FX_CHROMATIC_ABERRATION: expected=4;break;
        case AP_FX_TILE: expected=3;break;
        default:return AP_FAIL(2,"unsupported geometry effect");
    }
    if(count!=expected || !p)return AP_FAIL(6,"invalid geometry effect parameters");
    for(c=0;c<(int)expected;++c)if(!isfinite(p[c]))return AP_FAIL(6,"effect parameter must be finite");
    if((effect==AP_FX_KALEIDOSCOPE && (p[0]<1.0f || p[0]>64.0f)) ||
       ((effect==AP_FX_TWIRL || effect==AP_FX_BULGE) && (p[1]<0.0f || p[1]>1.0f)) ||
       (effect==AP_FX_MIRROR && (p[0]<0.0f || p[0]>1.0f)) ||
       (effect==AP_FX_BEND && (p[1]<0.0f || p[1]>1.0f)) ||
       (effect==AP_FX_OFFSET && (p[2]<0.0f || p[2]>1.0f)))return AP_FAIL(6,"geometry parameter outside supported range");
    if(effect==AP_FX_OFFSET){
        wrap=(int)p[2];
        if(p[2]!=(float)wrap || (wrap!=0 && wrap!=1))return AP_FAIL(6,"wrap flag must be zero or one");
    }
    if(effect==AP_FX_MIRROR && (p[0]!=(float)(int)p[0] || p[0]<0 || p[0]>1))return AP_FAIL(6,"mirror axis must be zero or one");
    if(effect==AP_FX_CHROMATIC_ABERRATION && p[3]!=0.0f)return AP_FAIL(6,"unsupported aberration layout");
    if(effect==AP_FX_TILE && (p[0]<1 || p[0]>64 || p[1]<1 || p[1]>64 || p[2]<0 || p[2]>1))return AP_FAIL(6,"tile parameters outside supported range");
    if(effect==AP_FX_TWIRL && p[2]<0.0f)return AP_FAIL(6,"twirl strength must not be negative");
    if(effect==AP_FX_BEND && (p[1]!=(float)(int)p[1] || p[1]<0 || p[1]>1))return AP_FAIL(6,"bend axis must be zero or one");
    for(y=0;y<src->height;++y){
        float *out=(float *)((char *)dst->data+(size_t)y*dst->stride_bytes);
        for(x=0;x<src->width;++x){float sx,sy,v[3];
            if(effect==AP_FX_TILE){
                int cols=(int)p[0],rows=(int)p[1];float tx=(float)x/src->width*cols,ty=(float)y/src->height*rows;
                int col=(int)floorf(tx),row_index=(int)floorf(ty);float ux=tx-col,uy=ty-row_index;
                if(p[2]>=.5f && ((col+row_index)&1))ux=1.0f-ux;
                sx=ux*src->width;sy=uy*src->height;
                sample_linear(src,sx,sy,v);
                for(c=0;c<3;++c)out[x*3+c]=v[c];
                continue;
            } else if(effect==AP_FX_RGB_SPLIT){
                float offsets[6]={p[0],p[1],p[2],p[3],p[4],p[5]};int ch;
                for(ch=0;ch<3;++ch){float ax=x-offsets[ch*2]*src->width*.02f,ay=y-offsets[ch*2+1]*src->height*.02f,sample[3];
                    sample_constant(src,ax,ay,sample);v[ch]=sample[ch];}
                for(c=0;c<3;++c)out[x*3+c]=v[c];continue;
            } else if(effect==AP_FX_CHROMATIC_ABERRATION){
                float angle=p[1]*AP_PI/180.0f,dx=cosf(angle)*p[0]*src->width*.02f,dy=sinf(angle)*p[0]*src->height*.02f;
                float red[3],green[3],blue[3],sxr=(float)x-dx,syr=(float)y-dy,sxb=(float)x+dx,syb=(float)y+dy;
                if(fabsf(p[2])>1e-6f){float cx=src->width*.5f,cy=src->height*.5f,spread=1.0f+p[2]*.02f;
                    float rx=cx+(sxr-cx)/spread,ry=cy+(syr-cy)/spread;
                    float bx=cx+(sxb-cx)*spread,by=cy+(syb-cy)*spread;
                    sample_replicate(src,rx,ry,red);sample_replicate(src,bx,by,blue);
                }else{sample_constant(src,sxr,syr,red);sample_constant(src,sxb,syb,blue);}
                sample_linear(src,(float)x,(float)y,green);
                out[x*3]=red[0];out[x*3+1]=green[1];out[x*3+2]=blue[2];continue;
            } else map_coordinate(effect,p,x,y,src->width,src->height,&sx,&sy);
            if(effect==AP_FX_OFFSET && wrap){
                int ix=isfinite(sx)?(int)fmodf(sx,(float)src->width):0;
                int iy=isfinite(sy)?(int)fmodf(sy,(float)src->height):0;
                ix=((ix%src->width)+src->width)%src->width;iy=((iy%src->height)+src->height)%src->height;
                const float *row=(const float *)((const char *)src->data+(size_t)iy*src->stride_bytes);
                for(c=0;c<3;++c)v[c]=row[ix*3+c];
            }else if(effect==AP_FX_OFFSET){
                sample_constant(src,sx,sy,v);
            }else sample_linear(src,sx,sy,v);
            for(c=0;c<3;++c)out[x*3+c]=v[c];
        }
    }
    return AP_OK;
}
