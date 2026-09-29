/* Fused multi-input effects. Scratch for sorting is one scanline, never a frame. */
#include "aphelion_fx.h"
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define FAIL(c,m) ((AP_Result){c,m})
#define OK ((AP_Result){0,"ok"})
static float clip(float v) { return v<0?0:v>1?1:v; }
static const float *row(const AP_FrameView *v,int y) { return (const float *)((const char *)v->data+(size_t)y*v->stride_bytes); }
static float gray(const AP_FrameView *v,int x,int y) {
    const float *r=row(v,y);
    return v->format==AP_PIXEL_GRAY_F32?r[x]:r[3*x]*.299f+r[3*x+1]*.587f+r[3*x+2]*.114f;
}
static AP_Result check_aux(const AP_FrameView *v,const AP_FrameView *dst) {
    size_t channels, bytes;
    uintptr_t a,b;
    if(!v || !v->data)return FAIL(1,"missing auxiliary image");
    if(v->format!=AP_PIXEL_RGB_F32 && v->format!=AP_PIXEL_GRAY_F32)return FAIL(2,"invalid auxiliary format");
    channels=v->format==AP_PIXEL_RGB_F32?3:1;
    bytes=(size_t)dst->width*channels*sizeof(float);
    if(v->width!=dst->width || v->height!=dst->height || v->stride_bytes!=bytes ||
       v->data_bytes<bytes*(size_t)dst->height || (uintptr_t)v->data%sizeof(float))return FAIL(3,"invalid auxiliary layout");
    a=(uintptr_t)v->data;b=(uintptr_t)dst->data;
    if(v->data_bytes>UINTPTR_MAX-a || dst->data_bytes>UINTPTR_MAX-b)return FAIL(3,"invalid auxiliary address");
    if(a<b+dst->data_bytes && b<a+v->data_bytes)return FAIL(5,"auxiliary image overlaps destination");
    return OK;
}
AP_Result aphelion_fx_cube(const AP_FrameView *src, AP_FrameView *dst,
                          const float *table, size_t bytes, int size, float strength)
{
    AP_Result check=aphelion_fx_validate(src,dst);
    size_t entries;
    uintptr_t a=(uintptr_t)table,b=(uintptr_t)dst->data;
    int x,y,c;
    if(check.code)return check;
    if(!table || size<2 || size>256 || !isfinite(strength) || a%sizeof(float))return FAIL(6,"invalid LUT parameters");
    entries=(size_t)size*size*size*3;
    if(bytes!=entries*sizeof(float) || bytes>UINTPTR_MAX-a || dst->data_bytes>UINTPTR_MAX-b)return FAIL(4,"invalid LUT storage");
    if(a<b+dst->data_bytes && b<a+bytes)return FAIL(5,"LUT overlaps destination");
    strength=clip(strength);
    for(y=0;y<src->height;++y){
        const float *s=row(src,y);float *d=(float *)row(dst,y);
        for(x=0;x<src->width;++x){
            int lo[3],hi[3],nonfinite=0;float rgb[3],w[3];
            for(c=0;c<3;++c){float p;rgb[c]=clip(s[3*x+c]);if(!isfinite(rgb[c])){nonfinite=1;break;}
                p=rgb[c]*(size-1);lo[c]=(int)floorf(p);hi[c]=lo[c]+1<size?lo[c]+1:lo[c];w[c]=p-lo[c];}
            if(nonfinite){for(c=0;c<3;++c)d[3*x+c]=NAN;continue;}
            for(c=0;c<3;++c){
                double planes[2];int r,g;
                for(r=0;r<2;++r){double lines[2];int ri=r?hi[0]:lo[0];
                    for(g=0;g<2;++g){int gi=g?hi[1]:lo[1];size_t base=((size_t)ri*size+gi)*size*3+c;
                        lines[g]=(double)table[base+lo[2]*3]*(1.0-w[2])+(double)table[base+hi[2]*3]*w[2];}
                    planes[r]=lines[0]*(1.0-w[1])+lines[1]*w[1];}
                double transformed=planes[0]*(1.0-w[0])+planes[1]*w[0];
                d[3*x+c]=(float)(rgb[c]+(transformed-rgb[c])*strength);
            }
        }
    }
    return OK;
}

typedef struct { float key; int index; } SortPixel;
static int compare_pixel(const void *a,const void *b) {
    const SortPixel *x=a,*y=b;
    if(x->key<y->key)return -1;if(x->key>y->key)return 1;
    return (x->index>y->index)-(x->index<y->index);
}
static float horizontal(const AP_FrameView *src,float x,int y,int c) {
    int a,b;float f;const float *s=row(src,y);
    if(!isfinite(x))x=0;
    x=fmaxf(0,fminf((float)(src->width-1),x));
    a=(int)floorf(x); b=a+1; if(b>=src->width)b=src->width-1; f=x-a;
    return s[3*a+c]*(1.0f-f)+s[3*b+c]*f;
}

AP_Result aphelion_fx_extended(const AP_FrameView *src,const AP_FrameView *aux,
                              const AP_FrameView *aux2,AP_FrameView *dst,
                              int op,const float *p,size_t count) {
    static const int counts[]={0,3,4,1,7,3,5,3,0,3};
    AP_Result check=aphelion_fx_validate(src,dst);
    int x,y,c;size_t i;
    if(check.code)return check;
    if(op<1 || op>9 || count!=(size_t)counts[op] || (count && !p))return FAIL(6,"invalid extended effect parameters");
    for(i=0;i<count;++i)if(!isfinite(p[i]))return FAIL(6,"nonfinite effect parameter");
    check=check_aux(aux,dst);if(check.code)return check;
    if(op==5 || op==6){check=check_aux(aux2,dst);if(check.code)return check;}
    if((op==1 || op==8) && aux->format!=AP_PIXEL_RGB_F32)return FAIL(2,"RGB auxiliary image required");
    if(op==5 && aux2->format!=AP_PIXEL_RGB_F32)return FAIL(2,"RGB blur image required");
    if((op==4 || op==5) && p[1]<=0)return FAIL(6,"depth range must be positive");
    if(op==7 && (p[1]<0 || p[1]>2))return FAIL(6,"invalid anaglyph mode");
    if(op==9 && (p[1]<2 || p[1]>2147483000.0f))return FAIL(6,"invalid sorting span");
    if(op==9) {
        SortPixel *scratch=malloc((size_t)src->width*sizeof(SortPixel));
        if(!scratch)return FAIL(7,"not enough memory for sorting scanline");
        for(y=0;y<src->height;++y) {
            const float *s=row(src,y);float *d=(float *)row(dst,y);int start,end,j,k,span=(int)p[1];
            memcpy(d,s,(size_t)src->width*3*sizeof(float));
            x=0;
            while(x<src->width) {
                if(!(gray(aux,x,y)>=p[0])){++x;continue;}
                start=x;while(x<src->width && gray(aux,x,y)>=p[0])++x;end=x;
                for(j=start;j<end;) {
                    int n=end-j; if(n>span)n=span;
                    for(k=0;k<n;++k){scratch[k].key=gray(aux,j+k,y)*(p[2]!=0?-1.0f:1.0f);scratch[k].index=j+k;}
                    qsort(scratch,(size_t)n,sizeof(SortPixel),compare_pixel);
                    for(k=0;k<n;++k)for(c=0;c<3;++c)d[3*(j+k)+c]=s[3*scratch[k].index+c];
                    j+=n;
                }
            }
        }
        free(scratch);return OK;
    }
    if(op==8) {
        double mean[3]={0},target[3]={0},variance[3]={0},tv[3]={0};
        double n=(double)src->width*src->height;
        for(y=0;y<src->height;++y){const float *s=row(src,y),*r=row(aux,y);for(x=0;x<src->width;++x)for(c=0;c<3;++c){mean[c]+=s[3*x+c];target[c]+=r[3*x+c];}}
        for(c=0;c<3;++c){mean[c]/=n;target[c]/=n;}
        for(y=0;y<src->height;++y){const float *s=row(src,y),*r=row(aux,y);for(x=0;x<src->width;++x)for(c=0;c<3;++c){double a=s[3*x+c]-mean[c],b=r[3*x+c]-target[c];variance[c]+=a*a;tv[c]+=b*b;}}
        for(c=0;c<3;++c){double a=sqrt(variance[c]/n),b=sqrt(tv[c]/n);variance[c]=(a<=1e-4 || b<=1e-4)?1.0:b/a;}
        for(y=0;y<src->height;++y){const float *s=row(src,y);float *d=(float *)row(dst,y);for(x=0;x<src->width;++x)for(c=0;c<3;++c)d[3*x+c]=(float)((s[3*x+c]-mean[c])*variance[c]+target[c]);}
        return OK;
    }
    for(y=0;y<src->height;++y) {
        const float *s=row(src,y),*a=row(aux,y),*b=aux2?row(aux2,y):NULL;
        float *d=(float *)row(dst,y);
        for(x=0;x<src->width;++x) {
            float value=0,alpha=0;
            if(op==1 && p[1]>0)value=fabsf(s[3*x]-a[3*x])*.299f+fabsf(s[3*x+1]-a[3*x+1])*.587f+fabsf(s[3*x+2]-a[3*x+2])*.114f;
            if(op==4 || op==5 || op==7){value=gray(aux,x,y);if(p[op==4?3:2]!=0)value=1.0f-value;}
            if(op==4)alpha=clip((value-p[0])/p[1])*p[2];
            if(op==5){alpha=clip(fabsf(value-p[0])/p[1]);alpha*=alpha;}
            if(op==6){float nx=-gray(aux,x,y)*p[0],ny=-gray(aux2,x,y)*p[0];float norm=sqrtf(nx*nx+ny*ny+1.0f)+1e-6f;
                value=1.0f+(clip((nx*p[1]+ny*p[2]+p[3])/norm)-p[3])*p[4];}
            for(c=0;c<3;++c) {
                float result=s[3*x+c];
                switch(op) {
                case 1: if(p[1]<=0 || value>=p[1])result=s[3*x+c]*(1+p[0])-a[3*x+c]*p[0];if(p[2]!=0)result=clip(result);break;
                case 2: result=clip(s[3*x+c]*p[0]+gray(aux,x,y)*p[c+1]);break;
                case 3: result=clip(s[3*x+c]+(aux->format==AP_PIXEL_RGB_F32?a[3*x+c]:a[x])*p[0]);break;
                case 4: result=s[3*x+c]*(1-alpha)+p[4+c]*alpha;break;
                case 5: result=s[3*x+c]*(1-alpha)+b[3*x+c]*alpha;break;
                case 6: result=s[3*x+c]*value;break;
                case 7: {float shift=(value-.5f)*p[0]*src->width;int left=p[1]==1?c==1:p[1]==2?c<2:c==0;result=horizontal(src,(float)x+(left?shift:-shift),y,c);break;}
                }
                d[3*x+c]=result;
            }
        }
    }
    return OK;
}
