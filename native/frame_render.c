/* Native presentation/export kernels. No NumPy or OpenCV dependency. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stddef.h>

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
    Py_ssize_t width, height, count, index;
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
    if (PyObject_GetBuffer(dst_object, &dst, PyBUF_SIMPLE) != 0) {
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

    count = width * height;
    for (index = 0; index < count; ++index) {
        Py_ssize_t source_index = index;
        Py_ssize_t row = index / width;
        Py_ssize_t column = index % width;
        unsigned char *out = (unsigned char *)dst.buf + index * 3;
        const unsigned char *in;
        if (flip_horizontal) column = width - 1 - column;
        if (flip_vertical) row = height - 1 - row;
        source_index = row * width + column;
        in = (const unsigned char *)src.buf + source_index * 3;
        out[0] = (unsigned char)fmin(255.0, floor(in[0] * exposure + 0.5));
        out[1] = (unsigned char)fmin(255.0, floor(in[1] * exposure + 0.5));
        out[2] = (unsigned char)fmin(255.0, floor(in[2] * exposure + 0.5));
    }
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
    if (PyObject_GetBuffer(dst_object, &dst, PyBUF_SIMPLE) != 0) {
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
    for (index = 0; index < count; ++index) {
        double value = input[index];
        if (!(value > 0.0)) value = 0.0;
        if (value >= 1.0) value = 1.0;
        output[index] = (unsigned char)floor(value * 255.0 + 0.5);
    }
    PyBuffer_Release(&src); PyBuffer_Release(&dst);
    Py_RETURN_NONE;
}
