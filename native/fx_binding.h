#ifndef APHELION_FX_BINDING_H
#define APHELION_FX_BINDING_H
#define PY_SSIZE_T_CLEAN
#include <Python.h>
PyObject *aphelion_fx_blend_binding(PyObject *, PyObject *);
PyObject *aphelion_fx_extended_binding(PyObject *, PyObject *);
PyObject *aphelion_fx_cube_binding(PyObject *, PyObject *);
PyObject *aphelion_fx_apply_binding(PyObject *, PyObject *);
PyObject *aphelion_fx_geometry_binding(PyObject *, PyObject *);
PyObject *aphelion_fx_exposure_contrast(PyObject *, PyObject *);
PyObject *aphelion_fx_invert(PyObject *, PyObject *);
PyObject *aphelion_fx_posterize(PyObject *, PyObject *);
PyObject *aphelion_fx_monochrome(PyObject *, PyObject *);
PyObject *aphelion_fx_threshold(PyObject *, PyObject *);
#endif
