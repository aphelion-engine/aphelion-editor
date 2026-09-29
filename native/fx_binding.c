#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <math.h>
#include <string.h>
#include "aphelion_fx.h"
#include "fx_binding.h"

AP_Result aphelion_fx_geometry(const AP_FrameView *, AP_FrameView *,
                               AP_FxEffect, const float *, size_t);

typedef struct {
    Py_buffer src;
    Py_buffer dst;
    AP_FrameView source;
    AP_FrameView destination;
} BufferPair;

static int acquire_aux(PyObject *object, int width, int height, Py_buffer *buffer, AP_FrameView *view)
{
    size_t pixels=(size_t)width*(size_t)height;
    if(PyObject_GetBuffer(object,buffer,PyBUF_FORMAT)!=0)return 0;
    if(!PyBuffer_IsContiguous(buffer,'C') || buffer->itemsize!=sizeof(float) ||
       !buffer->format || strcmp(buffer->format,"f") || (uintptr_t)buffer->buf%sizeof(float) ||
       ((size_t)buffer->len!=pixels*sizeof(float) && (size_t)buffer->len!=pixels*3*sizeof(float))) {
        PyBuffer_Release(buffer);memset(buffer,0,sizeof(*buffer));
        PyErr_SetString(PyExc_ValueError,"auxiliary image must be contiguous aligned float32 gray or RGB matching the frame");return 0;
    }
    view->data=buffer->buf;view->data_bytes=(size_t)buffer->len;
    view->width=width;view->height=height;
    view->format=(size_t)buffer->len==pixels*sizeof(float)?AP_PIXEL_GRAY_F32:AP_PIXEL_RGB_F32;
    view->stride_bytes=(size_t)width*sizeof(float)*(view->format==AP_PIXEL_RGB_F32?3:1);
    return 1;
}

static int
acquire_pair(PyObject *src_obj, PyObject *dst_obj, int width, int height,
             BufferPair *pair)
{
    size_t row_bytes;
    memset(pair, 0, sizeof(*pair));
    if (width <= 0 || height <= 0 ||
        (size_t)width > SIZE_MAX / (3 * sizeof(float)) ||
        (size_t)height > SIZE_MAX / ((size_t)width * 3 * sizeof(float))) {
        PyErr_SetString(PyExc_ValueError, "native effect: invalid frame dimensions");
        return 0;
    }
    row_bytes = (size_t)width * 3 * sizeof(float);
    if (PyObject_GetBuffer(src_obj, &pair->src, PyBUF_FORMAT) != 0) return 0;
    if (PyObject_GetBuffer(dst_obj, &pair->dst, PyBUF_WRITABLE | PyBUF_FORMAT) != 0) {
        PyBuffer_Release(&pair->src);
        return 0;
    }
    if (!PyBuffer_IsContiguous(&pair->src, 'C') ||
        !PyBuffer_IsContiguous(&pair->dst, 'C') ||
        pair->src.itemsize != (Py_ssize_t)sizeof(float) ||
        pair->dst.itemsize != (Py_ssize_t)sizeof(float) ||
        pair->src.format == NULL || pair->dst.format == NULL ||
        pair->src.format[0] != 'f' || pair->dst.format[0] != 'f' ||
        (uintptr_t)pair->src.buf % sizeof(float) != 0 ||
        (uintptr_t)pair->dst.buf % sizeof(float) != 0 ||
        (size_t)pair->src.len < row_bytes * (size_t)height ||
        (size_t)pair->dst.len < row_bytes * (size_t)height) {
        PyBuffer_Release(&pair->src);
        PyBuffer_Release(&pair->dst);
        PyErr_SetString(PyExc_ValueError,
                        "native effects expect aligned, contiguous float32 RGB buffers of sufficient size");
        return 0;
    }
    pair->source.data = pair->src.buf;
    pair->source.data_bytes = (size_t)pair->src.len;
    pair->source.width = width;
    pair->source.height = height;
    pair->source.stride_bytes = row_bytes;
    pair->source.format = AP_PIXEL_RGB_F32;
    pair->destination.data = pair->dst.buf;
    pair->destination.data_bytes = (size_t)pair->dst.len;
    pair->destination.width = width;
    pair->destination.height = height;
    pair->destination.stride_bytes = row_bytes;
    pair->destination.format = AP_PIXEL_RGB_F32;
    return 1;
}

static PyObject *
finish_pair(BufferPair *pair, AP_Result result)
{
    PyBuffer_Release(&pair->src);
    PyBuffer_Release(&pair->dst);
    if (result.code != 0) {
        PyErr_Format(result.code == 7 ? PyExc_MemoryError : PyExc_RuntimeError, "native effect error %d: %s",
                     result.code, result.message ? result.message : "unknown error");
        return NULL;
    }
    Py_RETURN_NONE;
}

PyObject *aphelion_fx_cube_binding(PyObject *self, PyObject *args)
{
    PyObject *src, *dst, *table;
    int width, height, size;
    float strength;
    BufferPair pair;
    Py_buffer lut;
    AP_Result result;
    if(!PyArg_ParseTuple(args,"OOOiiif", &src,&dst,&table,&width,&height,&size,&strength))return NULL;
    if(!acquire_pair(src,dst,width,height,&pair))return NULL;
    if(PyObject_GetBuffer(table,&lut,PyBUF_FORMAT)!=0){PyBuffer_Release(&pair.src);PyBuffer_Release(&pair.dst);return NULL;}
    if(!PyBuffer_IsContiguous(&lut,'C') || lut.itemsize!=sizeof(float) || !lut.format || strcmp(lut.format,"f")) {
        PyBuffer_Release(&lut);PyBuffer_Release(&pair.src);PyBuffer_Release(&pair.dst);
        PyErr_SetString(PyExc_ValueError,"LUT must be contiguous float32");return NULL;
    }
    Py_BEGIN_ALLOW_THREADS
    result=aphelion_fx_cube(&pair.source,&pair.destination,lut.buf,(size_t)lut.len,size,strength);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&lut);
    return finish_pair(&pair,result);
}

PyObject *aphelion_fx_blend_binding(PyObject *self, PyObject *args)
{
    PyObject *bg, *fg, *mask, *dst;
    BufferPair background, foreground, matte;
    int width, height, mode;
    float opacity;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOOOiiif:fx_blend", &bg, &fg, &mask, &dst,
                          &width, &height, &mode, &opacity)) return NULL;
    if (!acquire_pair(bg, dst, width, height, &background)) return NULL;
    if (!acquire_pair(fg, dst, width, height, &foreground)) {
        PyBuffer_Release(&background.src); PyBuffer_Release(&background.dst); return NULL;
    }
    if (mask != Py_None && !acquire_pair(mask, dst, width, height, &matte)) {
        PyBuffer_Release(&background.src); PyBuffer_Release(&background.dst);
        PyBuffer_Release(&foreground.src); PyBuffer_Release(&foreground.dst); return NULL;
    }
    Py_BEGIN_ALLOW_THREADS
    result = aphelion_fx_blend(&background.source, &foreground.source,
                              mask == Py_None ? NULL : &matte.source,
                              &background.destination, mode, opacity);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&foreground.src); PyBuffer_Release(&foreground.dst);
    if (mask != Py_None) { PyBuffer_Release(&matte.src); PyBuffer_Release(&matte.dst); }
    return finish_pair(&background, result);
}

PyObject *aphelion_fx_extended_binding(PyObject *self, PyObject *args)
{
    PyObject *source,*aux,*aux2,*destination,*parameters,*sequence;
    BufferPair pair;Py_buffer a={0},b={0};AP_FrameView av={0},bv={0};
    int width,height,operation;Py_ssize_t count,i;float p[32];AP_Result result;
    (void)self;
    if(!PyArg_ParseTuple(args,"OOOOiiiO:fx_extended",&source,&aux,&aux2,&destination,
                         &width,&height,&operation,&parameters))return NULL;
    sequence=PySequence_Fast(parameters,"parameters must be a sequence");if(!sequence)return NULL;
    count=PySequence_Fast_GET_SIZE(sequence);
    if(count>32){Py_DECREF(sequence);PyErr_SetString(PyExc_ValueError,"too many effect parameters");return NULL;}
    for(i=0;i<count;++i){p[i]=(float)PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence,i));
        if(PyErr_Occurred() || !isfinite(p[i])){Py_DECREF(sequence);if(!PyErr_Occurred())PyErr_SetString(PyExc_ValueError,"effect parameters must be finite");return NULL;}}
    Py_DECREF(sequence);
    if(!acquire_pair(source,destination,width,height,&pair))return NULL;
    if(!acquire_aux(aux,width,height,&a,&av))goto error;
    if(aux2!=Py_None && !acquire_aux(aux2,width,height,&b,&bv))goto error;
    Py_BEGIN_ALLOW_THREADS
    result=aphelion_fx_extended(&pair.source,&av,aux2==Py_None?NULL:&bv,&pair.destination,operation,p,(size_t)count);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&a);if(b.obj)PyBuffer_Release(&b);
    return finish_pair(&pair,result);
error:
    if(a.obj)PyBuffer_Release(&a);if(b.obj)PyBuffer_Release(&b);
    PyBuffer_Release(&pair.src);PyBuffer_Release(&pair.dst);return NULL;
}

PyObject *
aphelion_fx_geometry_binding(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj, *parameter_object, *sequence;
    int width, height, effect, index;
    float parameters[8] = {0};
    Py_ssize_t count;
    BufferPair pair;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOiiiO:fx_geometry", &src_obj, &dst_obj,
                          &width, &height, &effect, &parameter_object)) return NULL;
    sequence = PySequence_Fast(parameter_object, "parameters must be a finite sequence of numbers");
    if (!sequence) return NULL;
    count = PySequence_Fast_GET_SIZE(sequence);
    if (count > 8) {
        Py_DECREF(sequence);
        PyErr_SetString(PyExc_ValueError, "too many geometry effect parameters");
        return NULL;
    }
    for (index = 0; index < (int)count; ++index) {
        double value = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(sequence, index));
        if (PyErr_Occurred()) { Py_DECREF(sequence); return NULL; }
        parameters[index] = (float)value;
        if (!isfinite(parameters[index])) {
            Py_DECREF(sequence);
            PyErr_SetString(PyExc_ValueError, "geometry effect parameters must be finite");
            return NULL;
        }
    }
    Py_DECREF(sequence);
    if (!acquire_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    if (pair.src.buf == pair.dst.buf) {
        PyBuffer_Release(&pair.src);
        PyBuffer_Release(&pair.dst);
        PyErr_SetString(PyExc_ValueError, "geometry effects do not support in-place processing");
        return NULL;
    }
    /* Geometry kernels require equal dimensions; buffers remain caller-owned. */
    Py_BEGIN_ALLOW_THREADS
    result = aphelion_fx_geometry(&pair.source, &pair.destination,
                                  (AP_FxEffect)effect, parameters, (size_t)count);
    Py_END_ALLOW_THREADS
    return finish_pair(&pair, result);
}

PyObject *
aphelion_fx_apply_binding(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj, *parameter_object, *parameter_sequence;
    int width, height, effect, index;
    float parameters[17];
    Py_ssize_t count;
    BufferPair pair;
    AP_Result result;
    (void)self;

    if (!PyArg_ParseTuple(args, "OOiiiO:fx_apply", &src_obj, &dst_obj,
                          &width, &height, &effect, &parameter_object))
        return NULL;
    parameter_sequence = PySequence_Fast(parameter_object, "parameters must be a finite sequence of numbers");
    if (parameter_sequence == NULL) return NULL;
    count = PySequence_Fast_GET_SIZE(parameter_sequence);
    if (count > (Py_ssize_t)(sizeof(parameters) / sizeof(parameters[0]))) {
        Py_DECREF(parameter_sequence);
        PyErr_SetString(PyExc_ValueError, "too many native effect parameters");
        return NULL;
    }
    for (index = 0; index < (int)count; ++index) {
        double value = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(parameter_sequence, index));
        if (PyErr_Occurred()) {
            Py_DECREF(parameter_sequence);
            return NULL;
        }
        parameters[index] = (float)value;
        if (!isfinite(parameters[index])) {
            Py_DECREF(parameter_sequence);
            PyErr_SetString(PyExc_ValueError, "native effect parameters must be finite");
            return NULL;
        }
    }
    Py_DECREF(parameter_sequence);
    if (!acquire_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    if (pair.src.buf == pair.dst.buf) {
        int exact_supported = (effect >= AP_FX_EXPOSURE_CONTRAST && effect <= AP_FX_SUPPRESS_SPILL) ||
                              (effect >= AP_FX_VIGNETTE && effect <= AP_FX_CLIP_AFFINE && effect != AP_FX_TILE);
        if (!exact_supported) {
            PyBuffer_Release(&pair.src);
            PyBuffer_Release(&pair.dst);
            PyErr_SetString(PyExc_ValueError, "native effect does not support in-place processing");
            return NULL;
        }
    }
    Py_BEGIN_ALLOW_THREADS
    result = aphelion_fx_apply(&pair.source, &pair.destination,
                               (AP_FxEffect)effect, parameters,
                               (size_t)count);
    Py_END_ALLOW_THREADS
    return finish_pair(&pair, result);
}

static int
acquire_legacy_pair(PyObject *src_obj, PyObject *dst_obj, int width, int height,
                    BufferPair *pair)
{
    return acquire_pair(src_obj, dst_obj, width, height, pair);
}

static PyObject *
legacy_finish(BufferPair *pair, AP_Result result)
{
    return finish_pair(pair, result);
}

PyObject *
aphelion_fx_exposure_contrast(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj;
    int width, height;
    float gain, offset;
    BufferPair pair;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOiiff:fx_exposure_contrast", &src_obj, &dst_obj,
                          &width, &height, &gain, &offset)) return NULL;
    if (!acquire_legacy_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    Py_BEGIN_ALLOW_THREADS
    result = ap_fx_exposure_contrast(&pair.source, &pair.destination, gain, offset);
    Py_END_ALLOW_THREADS
    return legacy_finish(&pair, result);
}

PyObject *
aphelion_fx_invert(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj;
    int width, height;
    BufferPair pair;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOii:fx_invert", &src_obj, &dst_obj, &width, &height)) return NULL;
    if (!acquire_legacy_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    Py_BEGIN_ALLOW_THREADS
    result = ap_fx_invert(&pair.source, &pair.destination);
    Py_END_ALLOW_THREADS
    return legacy_finish(&pair, result);
}

PyObject *
aphelion_fx_posterize(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj;
    int width, height, levels;
    BufferPair pair;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOiii:fx_posterize", &src_obj, &dst_obj,
                          &width, &height, &levels)) return NULL;
    if (!acquire_legacy_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    Py_BEGIN_ALLOW_THREADS
    result = ap_fx_posterize(&pair.source, &pair.destination, levels);
    Py_END_ALLOW_THREADS
    return legacy_finish(&pair, result);
}

PyObject *
aphelion_fx_monochrome(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj;
    int width, height;
    float red, green, blue;
    BufferPair pair;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOiifff:fx_monochrome", &src_obj, &dst_obj,
                          &width, &height, &red, &green, &blue)) return NULL;
    if (!acquire_legacy_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    Py_BEGIN_ALLOW_THREADS
    result = ap_fx_monochrome(&pair.source, &pair.destination, red, green, blue);
    Py_END_ALLOW_THREADS
    return legacy_finish(&pair, result);
}

PyObject *
aphelion_fx_threshold(PyObject *self, PyObject *args)
{
    PyObject *src_obj, *dst_obj, *low_obj, *high_obj;
    int width, height, index;
    float level, low[3], high[3];
    BufferPair pair;
    AP_Result result;
    (void)self;
    if (!PyArg_ParseTuple(args, "OOiifOO:fx_threshold", &src_obj, &dst_obj,
                          &width, &height, &level, &low_obj, &high_obj)) return NULL;
    if (!PySequence_Check(low_obj) || !PySequence_Check(high_obj) ||
        PySequence_Size(low_obj) != 3 || PySequence_Size(high_obj) != 3) {
        PyErr_SetString(PyExc_ValueError, "threshold colors must each have three channels");
        return NULL;
    }
    for (index = 0; index < 3; ++index) {
        PyObject *lo_item = PySequence_GetItem(low_obj, index);
        PyObject *hi_item = PySequence_GetItem(high_obj, index);
        if (!lo_item || !hi_item) { Py_XDECREF(lo_item); Py_XDECREF(hi_item); return NULL; }
        low[index] = (float)PyFloat_AsDouble(lo_item);
        high[index] = (float)PyFloat_AsDouble(hi_item);
        Py_DECREF(lo_item); Py_DECREF(hi_item);
        if (PyErr_Occurred()) return NULL;
    }
    if (!acquire_legacy_pair(src_obj, dst_obj, width, height, &pair)) return NULL;
    Py_BEGIN_ALLOW_THREADS
    result = ap_fx_threshold(&pair.source, &pair.destination, level, low, high);
    Py_END_ALLOW_THREADS
    return legacy_finish(&pair, result);
}
