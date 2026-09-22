#ifndef APHELION_FRAME_RENDER_H
#define APHELION_FRAME_RENDER_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>

PyObject *aphelion_render_rgb_u8(PyObject *self, PyObject *args);
PyObject *aphelion_quantize_f32_u8(PyObject *self, PyObject *args);

#endif
