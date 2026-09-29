/* Native presentation/export kernels. No NumPy or OpenCV dependency. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stddef.h>
#include <string.h>
#include <stdint.h>

#include "frame_render.h"

static int
check_frame(Py_ssize_t length, Py_ssize_t width, Py_ssize_t height,
            Py_ssize_t bytes_per_pixel, const char *name)
{
    if (width <= 0 || height <= 0 ||
        width > PY_SSIZE_T_MAX / bytes_per_pixel ||
        height > PY_SSIZE_T_MAX / (width * bytes_per_pixel)) {
        PyErr_Format(PyExc_ValueError, "%s: invalid frame geometry", name);
        return 0;
    }
    if (length < width * height * bytes_per_pixel) {
        PyErr_Format(PyExc_ValueError, "%s: frame buffer is too small", name);
        return 0;
    }
    return 1;
}

PyObject *
aphelion_render_rgb_u8(PyObject *self, PyObject *args)
{
    PyObject *src_object = NULL, *dst_object = NULL;
    Py_buffer src, dst;
    Py_ssize_t width, height, index;
    unsigned char lut[256];
    int flip_horizontal, flip_vertical;
    double exposure;

    (void)self;
    if (!PyArg_ParseTuple(args, "OOnndii:render_rgb_u8", &src_object,
                          &dst_object, &width, &height, &exposure,
                          &flip_horizontal, &flip_vertical)) {
        return NULL;
    }
    if (!Py_IS_FINITE(exposure) || exposure < 0.0) {
        PyErr_SetString(PyExc_ValueError, "render_rgb_u8: exposure must be finite");
        return NULL;
    }
    if (PyObject_GetBuffer(src_object, &src, PyBUF_SIMPLE) != 0) return NULL;
    if (PyObject_GetBuffer(dst_object, &dst, PyBUF_WRITABLE) != 0) {
        PyBuffer_Release(&src);
        return NULL;
    }
    if (!PyBuffer_IsContiguous(&src, 'C') ||
        !PyBuffer_IsContiguous(&dst, 'C') ||
        !check_frame(src.len, width, height, 3, "render_rgb_u8") ||
        !check_frame(dst.len, width, height, 3, "render_rgb_u8")) {
        PyBuffer_Release(&src); PyBuffer_Release(&dst);
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "render_rgb_u8: invalid buffer");
        return NULL;
    }

    /* Flips cannot safely overwrite their own input. */
    if ((uintptr_t)src.buf < (uintptr_t)dst.buf + dst.len &&
        (uintptr_t)dst.buf < (uintptr_t)src.buf + src.len) {
        PyBuffer_Release(&src); PyBuffer_Release(&dst);
        PyErr_SetString(PyExc_ValueError, "render_rgb_u8: buffers must not overlap");
        return NULL;
    }
    /* The input has only 256 possible values. Preserve the exact rounding
       contract while moving floating point work out of the pixel loop. */
    for (index = 0; index < 256; ++index)
        lut[index] = (unsigned char)fmin(255.0, floor(index * exposure + 0.5));
    Py_BEGIN_ALLOW_THREADS
    for (index = 0; index < height; ++index) {
        Py_ssize_t column;
        const unsigned char *in = (const unsigned char *)src.buf +
            (flip_vertical ? height - 1 - index : index) * width * 3;
        unsigned char *out = (unsigned char *)dst.buf + index * width * 3;
        if (!flip_horizontal) {
            if (exposure == 1.0) memcpy(out, in, width * 3);
            else for (column = 0; column < width * 3; ++column)
                out[column] = lut[in[column]];
        } else {
            for (column = 0; column < width; ++column) {
                Py_ssize_t offset = (width - 1 - column) * 3;
                out[column * 3] = lut[in[offset]];
                out[column * 3 + 1] = lut[in[offset + 1]];
                out[column * 3 + 2] = lut[in[offset + 2]];
            }
        }
    }
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&src); PyBuffer_Release(&dst);
    Py_RETURN_NONE;
}

PyObject *
aphelion_quantize_f32_u8(PyObject *self, PyObject *args)
{
    PyObject *src_object = NULL, *dst_object = NULL;
    Py_buffer src, dst;
    Py_ssize_t width, height, count, index;
    const float *input;
    unsigned char *output;

    (void)self;
    if (!PyArg_ParseTuple(args, "OOnn:quantize_f32_u8", &src_object,
                          &dst_object, &width, &height)) return NULL;
    if (PyObject_GetBuffer(src_object, &src, PyBUF_SIMPLE) != 0) return NULL;
    if (PyObject_GetBuffer(dst_object, &dst, PyBUF_WRITABLE) != 0) {
        PyBuffer_Release(&src); return NULL;
    }
    if (!PyBuffer_IsContiguous(&src, 'C') || !PyBuffer_IsContiguous(&dst, 'C') ||
        !check_frame(src.len, width, height, 3 * (Py_ssize_t)sizeof(float), "quantize_f32_u8") ||
        !check_frame(dst.len, width, height, 3, "quantize_f32_u8")) {
        PyBuffer_Release(&src); PyBuffer_Release(&dst);
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "quantize_f32_u8: invalid buffer");
        return NULL;
    }
    input = (const float *)src.buf; output = (unsigned char *)dst.buf;
    count = width * height * 3;
    Py_BEGIN_ALLOW_THREADS
    for (index = 0; index < count; ++index) {
        double value = input[index];
        if (!(value > 0.0)) value = 0.0;
        if (value >= 1.0) value = 1.0;
        output[index] = (unsigned char)floor(value * 255.0 + 0.5);
    }
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&src); PyBuffer_Release(&dst);
    Py_RETURN_NONE;
}
