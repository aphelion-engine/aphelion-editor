/*
 * aphelion_native — frame kernels and buffer pooling for the media engine.
 *
 * Why this file exists
 * --------------------
 * The interactive pipeline hands a decoded frame through two operations that
 * are pure memory traffic:
 *
 *   1. BGR -> RGB channel swap (OpenCV returns BGR; the pipeline is RGB)
 *   2. optional downscale to the preview/proxy width
 *
 * Done with library calls that is *two* full-frame passes over w*h*3 bytes
 * and *two* freshly allocated buffers per frame. Both are avoidable:
 *
 *   * the channel swap can happen **in place** in the buffer the decoder
 *     already owns, costing O(1) extra memory and zero allocations;
 *   * the swap and the downscale can be **fused** into a single pass that
 *     writes into a pooled destination, so a proxied frame costs one pass
 *     and no allocation at all.
 *
 * Those are the two kernels here. Everything else the pipeline does to a
 * frame is either already vectorised by NumPy, or is float work where NumPy
 * is the right tool — so nothing else is duplicated natively.
 *
 * Design constraints
 * ------------------
 * * **Optional.** The Python package works exactly as before when this
 *   module is not built. ``core.native`` reports availability and every call
 *   site has a verified fallback.
 * * **No third-party headers.** Only the CPython C API and the C standard
 *   library, so the module builds with MSVC, GCC, or Clang without any SDK
 *   beyond the Python headers.
 * * **Buffer-protocol only.** Kernels accept any object supporting the
 *   buffer protocol, so NumPy arrays pass in without importing NumPy from C.
 * * **Bounds checked.** Every kernel validates that the buffer is large
 *   enough for the declared geometry and raises ValueError rather than
 *   reading out of bounds.
 * * **No SIMD intrinsics.** The loops are written so a compiler at -O2/-O3
 *   auto-vectorises them; hand intrinsics would add a portability burden for
 *   a memory-bound kernel that is already at the bandwidth limit.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stddef.h>
#include <string.h>

/* ---------------------------------------------------------------------- */
/* Geometry helpers                                                        */
/* ---------------------------------------------------------------------- */

#define APHELION_CHANNELS 3

/*
 * Validate that `length` is at least width*height*channels, guarding the
 * multiplication against overflow on 32-bit Py_ssize_t.
 */
static int
aphelion_check_geometry(Py_ssize_t length,
                        Py_ssize_t width,
                        Py_ssize_t height,
                        const char *what)
{
    Py_ssize_t pixels;

    if (width <= 0 || height <= 0) {
        PyErr_Format(PyExc_ValueError,
                     "%s: width and height must be positive (got %zd x %zd)",
                     what, width, height);
        return 0;
    }

    if (width > PY_SSIZE_T_MAX / APHELION_CHANNELS) {
        PyErr_Format(PyExc_ValueError, "%s: width too large (%zd)", what, width);
        return 0;
    }
    pixels = width * APHELION_CHANNELS;

    if (height > PY_SSIZE_T_MAX / pixels) {
        PyErr_Format(PyExc_ValueError, "%s: dimensions too large", what);
        return 0;
    }
    pixels *= height;

    if (length < pixels) {
        PyErr_Format(PyExc_ValueError,
                     "%s: buffer holds %zd bytes, need %zd for %zdx%zd RGB",
                     what, length, pixels, width, height);
        return 0;
    }
    return 1;
}

/* ---------------------------------------------------------------------- */
/* Kernel: in-place BGR <-> RGB channel swap                               */
/* ---------------------------------------------------------------------- */

PyDoc_STRVAR(swap_bgr_rgb_inplace_doc,
"swap_bgr_rgb_inplace(buffer, width, height) -> None\n"
"\n"
"Swap the red and blue channels of a C-contiguous ``width*height*3`` byte\n"
"buffer, in place, in a single pass.\n"
"\n"
"Replaces ``cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)`` on the decode path.\n"
"The OpenCV call allocates a fresh output buffer and copies the whole frame\n"
"through it; this mutates the buffer the decoder already handed over, so the\n"
"op costs O(1) extra memory and no allocation.\n"
"\n"
"Raises:\n"
"    ValueError: buffer is not C-contiguous, or too small for the geometry.\n"
"    BufferError: buffer is not writable.\n");

static PyObject *
aphelion_swap_bgr_rgb_inplace(PyObject *self, PyObject *args)
{
    PyObject *target = NULL;
    Py_ssize_t width = 0, height = 0;
    Py_buffer view;
    unsigned char *pixels;
    Py_ssize_t count, index;

    (void)self;

    if (!PyArg_ParseTuple(args, "Onn:swap_bgr_rgb_inplace",
                          &target, &width, &height)) {
        return NULL;
    }

    if (PyObject_GetBuffer(target, &view, PyBUF_SIMPLE) != 0) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError,
                        "swap_bgr_rgb_inplace: buffer must be C-contiguous");
        return NULL;
    }
    if (view.readonly) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_BufferError,
                        "swap_bgr_rgb_inplace: buffer is read-only");
        return NULL;
    }
    if (!aphelion_check_geometry(view.len, width, height,
                                 "swap_bgr_rgb_inplace")) {
        PyBuffer_Release(&view);
        return NULL;
    }

    pixels = (unsigned char *)view.buf;
    count = width * height;

    /*
     * Stride the pointer rather than indexing, so the compiler emits a load,
     * two stores and an advance per pixel with no index arithmetic.
     */
    for (index = 0; index < count; ++index) {
        unsigned char blue = pixels[0];
        pixels[0] = pixels[2];
        pixels[2] = blue;
        pixels += APHELION_CHANNELS;
    }

    PyBuffer_Release(&view);
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Kernel: fused BGR -> RGB with box downscale                             */
/* ---------------------------------------------------------------------- */

PyDoc_STRVAR(resize_bgr_to_rgb_doc,
"resize_bgr_to_rgb(src, dst, src_width, src_height, out_width, out_height) -> None\n"
"\n"
"Box-downsample a BGR ``src`` into an RGB ``dst`` in a single fused pass.\n"
"\n"
"Replaces the ``cvtColor`` + ``cv2.resize`` pair on the proxy/decode path.\n"
"That pair performs two full-frame passes and allocates an intermediate\n"
"frame; this performs one pass and writes straight into ``dst``, which is\n"
"normally a buffer from :class:`Pool`.\n"
"\n"
"The box bounds are computed with integer arithmetic (``i * src / out``)\n"
"rather than floating point, so the mapping is exact, monotonic, and free of\n"
"accumulated rounding drift across the frame.\n"
"\n"
"Raises:\n"
"    ValueError: either buffer is too small, or the geometry is invalid.\n");

static PyObject *
aphelion_resize_bgr_to_rgb(PyObject *self, PyObject *args)
{
    PyObject *src_object = NULL;
    PyObject *dst_object = NULL;
    Py_ssize_t src_width = 0, src_height = 0;
    Py_ssize_t out_width = 0, out_height = 0;
    Py_buffer src_view;
    Py_buffer dst_view;
    const unsigned char *src;
    unsigned char *dst;
    Py_ssize_t dy, dx;

    (void)self;

    if (!PyArg_ParseTuple(args, "OOnnnn:resize_bgr_to_rgb",
                          &src_object, &dst_object,
                          &src_width, &src_height,
                          &out_width, &out_height)) {
        return NULL;
    }

    if (PyObject_GetBuffer(src_object, &src_view, PyBUF_SIMPLE) != 0) {
        return NULL;
    }
    if (!PyBuffer_IsContiguous(&src_view, 'C')) {
        PyBuffer_Release(&src_view);
        PyErr_SetString(PyExc_ValueError,
                        "resize_bgr_to_rgb: src must be C-contiguous");
        return NULL;
    }
    if (!aphelion_check_geometry(src_view.len, src_width, src_height,
                                 "resize_bgr_to_rgb src")) {
        PyBuffer_Release(&src_view);
        return NULL;
    }

    if (PyObject_GetBuffer(dst_object, &dst_view, PyBUF_SIMPLE) != 0) {
        PyBuffer_Release(&src_view);
        return NULL;
    }
    if (!PyBuffer_IsContiguous(&dst_view, 'C')) {
        PyBuffer_Release(&src_view);
        PyBuffer_Release(&dst_view);
        PyErr_SetString(PyExc_ValueError,
                        "resize_bgr_to_rgb: dst must be C-contiguous");
        return NULL;
    }
    if (dst_view.readonly) {
        PyBuffer_Release(&src_view);
        PyBuffer_Release(&dst_view);
        PyErr_SetString(PyExc_BufferError,
                        "resize_bgr_to_rgb: dst is read-only");
        return NULL;
    }
    if (!aphelion_check_geometry(dst_view.len, out_width, out_height,
                                 "resize_bgr_to_rgb dst")) {
        PyBuffer_Release(&src_view);
        PyBuffer_Release(&dst_view);
        return NULL;
    }

    src = (const unsigned char *)src_view.buf;
    dst = (unsigned char *)dst_view.buf;

    for (dy = 0; dy < out_height; ++dy) {
        Py_ssize_t y0 = (dy * src_height) / out_height;
        Py_ssize_t y1 = ((dy + 1) * src_height) / out_height;
        Py_ssize_t y;

        if (y1 <= y0) {
            y1 = y0 + 1;
        }
        if (y1 > src_height) {
            y1 = src_height;
        }

        for (dx = 0; dx < out_width; ++dx) {
            Py_ssize_t x0 = (dx * src_width) / out_width;
            Py_ssize_t x1 = ((dx + 1) * src_width) / out_width;
            Py_ssize_t x;
            unsigned long sum_r = 0, sum_g = 0, sum_b = 0, samples = 0;
            unsigned char *out = dst + (dy * out_width + dx) * APHELION_CHANNELS;

            if (x1 <= x0) {
                x1 = x0 + 1;
            }
            if (x1 > src_width) {
                x1 = src_width;
            }

            for (y = y0; y < y1; ++y) {
                const unsigned char *row =
                    src + (y * src_width + x0) * APHELION_CHANNELS;
                for (x = x0; x < x1; ++x) {
                    /* Source is BGR, destination is RGB: channels swapped. */
                    sum_b += row[0];
                    sum_g += row[1];
                    sum_r += row[2];
                    row += APHELION_CHANNELS;
                }
                samples += (unsigned long)(x1 - x0);
            }

            if (samples == 0) {
                samples = 1;
            }
            /* + samples/2 rounds to nearest rather than truncating. */
            out[0] = (unsigned char)((sum_r + samples / 2) / samples);
            out[1] = (unsigned char)((sum_g + samples / 2) / samples);
            out[2] = (unsigned char)((sum_b + samples / 2) / samples);
        }
    }

    PyBuffer_Release(&src_view);
    PyBuffer_Release(&dst_view);
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Kernel: RGB -> luma                                                     */
/* ---------------------------------------------------------------------- */

/* BT.601 limited-range coefficients in the same 14-bit fixed point form
 * OpenCV uses for COLOR_RGB2GRAY, so tracking and histogram code sees the
 * identical plane it got from cv2.cvtColor. */
#define APHELION_LUMA_R 4899
#define APHELION_LUMA_G 9617
#define APHELION_LUMA_B 1868
#define APHELION_LUMA_SHIFT 14
#define APHELION_LUMA_ROUND (1 << (APHELION_LUMA_SHIFT - 1))

PyDoc_STRVAR(rgb_to_luma_doc,
"rgb_to_luma(src, dst, width, height) -> None\n"
"\n"
"Convert an RGB ``width*height*3`` byte buffer into a ``width*height`` byte\n"
"luma plane, writing into ``dst``.\n"
"\n"
"Uses the same BT.601 fixed-point coefficients as ``cv2.COLOR_RGB2GRAY``, so\n"
"the output is numerically equivalent to the OpenCV call while avoiding the\n"
"per-call allocation. Used by tracking, histograms, and auto-levels.\n"
"\n"
"Raises:\n"
"    ValueError: either buffer is too small, or the geometry is invalid.\n");

static PyObject *
aphelion_rgb_to_luma(PyObject *self, PyObject *args)
{
    PyObject *src_object = NULL;
    PyObject *dst_object = NULL;
    Py_ssize_t width = 0, height = 0;
    Py_buffer src_view;
    Py_buffer dst_view;
    const unsigned char *src;
    unsigned char *dst;
    Py_ssize_t count, index;

    (void)self;

    if (!PyArg_ParseTuple(args, "OOnn:rgb_to_luma",
                          &src_object, &dst_object, &width, &height)) {
        return NULL;
    }

    if (PyObject_GetBuffer(src_object, &src_view, PyBUF_SIMPLE) != 0) {
        return NULL;
    }
    if (!aphelion_check_geometry(src_view.len, width, height,
                                 "rgb_to_luma src")) {
        PyBuffer_Release(&src_view);
        return NULL;
    }

    if (PyObject_GetBuffer(dst_object, &dst_view, PyBUF_SIMPLE) != 0) {
        PyBuffer_Release(&src_view);
        return NULL;
    }
    if (dst_view.readonly) {
        PyBuffer_Release(&src_view);
        PyBuffer_Release(&dst_view);
        PyErr_SetString(PyExc_BufferError, "rgb_to_luma: dst is read-only");
        return NULL;
    }
    if (dst_view.len < width * height) {
        PyBuffer_Release(&src_view);
        PyBuffer_Release(&dst_view);
        PyErr_Format(PyExc_ValueError,
                     "rgb_to_luma: dst holds %zd bytes, need %zd",
                     dst_view.len, width * height);
        return NULL;
    }

    src = (const unsigned char *)src_view.buf;
    dst = (unsigned char *)dst_view.buf;
    count = width * height;

    for (index = 0; index < count; ++index) {
        unsigned int weighted =
            (unsigned int)src[0] * APHELION_LUMA_R +
            (unsigned int)src[1] * APHELION_LUMA_G +
            (unsigned int)src[2] * APHELION_LUMA_B +
            APHELION_LUMA_ROUND;
        dst[index] = (unsigned char)(weighted >> APHELION_LUMA_SHIFT);
        src += APHELION_CHANNELS;
    }

    PyBuffer_Release(&src_view);
    PyBuffer_Release(&dst_view);
    Py_RETURN_NONE;
}

/* ---------------------------------------------------------------------- */
/* Frame buffer pool                                                       */
/* ---------------------------------------------------------------------- */

/*
 * A byte-budgeted pool of reusable frame buffers.
 *
 * The pipeline allocates and discards multi-megabyte frame buffers many
 * times per second. CPython's allocator handles that without leaking, but the
 * churn shows up as page faults and allocator time, and every transient
 * buffer is a Python object the cyclic GC has to walk.
 *
 * The pool hands back a ``bytearray`` — which NumPy can wrap with
 * ``np.frombuffer`` as a *view* rather than a copy — and takes it back when
 * the frame is no longer displayed.
 *
 * Buckets are keyed by exact byte size, which is the right trade-off for a
 * video pipeline: frame geometry repeats for long stretches, so exact-size
 * hits dominate and no splitting logic is needed.
 */

typedef struct {
    PyObject_HEAD
    PyObject *idle;        /* dict[int, list[bytearray]] */
    Py_ssize_t budget;     /* maximum bytes retained in the pool */
    Py_ssize_t idle_bytes; /* bytes currently sitting idle */
    Py_ssize_t hits;
    Py_ssize_t misses;
    Py_ssize_t releases;
    Py_ssize_t discards;
} AphelionPool;

static void
aphelion_pool_dealloc(AphelionPool *self)
{
    Py_XDECREF(self->idle);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
aphelion_pool_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    AphelionPool *self = (AphelionPool *)type->tp_alloc(type, 0);
    (void)args;
    (void)kwargs;

    if (self == NULL) {
        return NULL;
    }
    self->idle = PyDict_New();
    if (self->idle == NULL) {
        Py_DECREF(self);
        return NULL;
    }
    /* 256 MiB default: enough for a deep 4K preview ring, bounded so a
     * pathological project cannot pin the whole machine. */
    self->budget = 256 * 1024 * 1024;
    self->idle_bytes = 0;
    self->hits = 0;
    self->misses = 0;
    self->releases = 0;
    self->discards = 0;
    return (PyObject *)self;
}

static int
aphelion_pool_init(AphelionPool *self, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"budget_bytes", NULL};
    Py_ssize_t budget = self->budget;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|n:Pool", keywords,
                                     &budget)) {
        return -1;
    }
    if (budget < 0) {
        PyErr_SetString(PyExc_ValueError,
                        "Pool: budget_bytes must not be negative");
        return -1;
    }

    self->budget = budget;
    if (self->idle_bytes > budget) {
        PyDict_Clear(self->idle);
        self->idle_bytes = 0;
    }
    return 0;
}

PyDoc_STRVAR(pool_acquire_doc,
"acquire(size) -> bytearray\n"
"\n"
"Return a writable buffer of exactly ``size`` bytes, reusing a released\n"
"buffer of the same size when one is pooled.\n"
"\n"
"The returned object supports the buffer protocol, so it can be wrapped\n"
"zero-copy with ``np.frombuffer(buf, dtype=np.uint8)`` and released back to\n"
"the pool when the frame is no longer displayed.\n");

static PyObject *
aphelion_pool_acquire(AphelionPool *self, PyObject *args)
{
    Py_ssize_t size = 0;
    PyObject *key = NULL;
    PyObject *bucket = NULL;
    PyObject *buffer = NULL;

    if (!PyArg_ParseTuple(args, "n:acquire", &size)) {
        return NULL;
    }
    if (size <= 0) {
        PyErr_SetString(PyExc_ValueError, "Pool.acquire: size must be positive");
        return NULL;
    }

    /* The key is an owned reference for the whole lookup: passing a
     * temporary straight into PyDict_GetItemWithError would leak it. */
    key = PyLong_FromSsize_t(size);
    if (key == NULL) {
        return NULL;
    }

    bucket = PyDict_GetItemWithError(self->idle, key);
    if (bucket == NULL && PyErr_Occurred()) {
        Py_DECREF(key);
        return NULL;
    }

    if (bucket != NULL && PyList_GET_SIZE(bucket) > 0) {
        /* Steal the last element: O(1), and the most recently released
         * buffer is the one most likely still warm in cache. */
        buffer = PyList_GET_ITEM(bucket, PyList_GET_SIZE(bucket) - 1);
        Py_INCREF(buffer);
        if (PyList_SetSlice(bucket, PyList_GET_SIZE(bucket) - 1,
                            PyList_GET_SIZE(bucket), NULL) != 0) {
            Py_DECREF(buffer);
            Py_DECREF(key);
            return NULL;
        }
        self->idle_bytes -= size;
        self->hits += 1;
        Py_DECREF(key);
        return buffer;
    }

    Py_DECREF(key);
    buffer = PyByteArray_FromStringAndSize(NULL, size);
    if (buffer == NULL) {
        return NULL;
    }
    self->misses += 1;
    return buffer;
}

PyDoc_STRVAR(pool_release_doc,
"release(buffer) -> bool\n"
"\n"
"Return ``buffer`` to the pool for reuse.\n"
"\n"
"Returns ``True`` when the buffer was retained. Returns ``False`` when the\n"
"pool is already at its byte budget, in which case the buffer is simply\n"
"dropped and will be reclaimed by normal Python reference counting.\n"
"\n"
"Releasing a buffer that is still referenced elsewhere is safe — the caller\n"
"retains ownership; the pool's reference is released when the caller drops\n"
"its own.\n");

static PyObject *
aphelion_pool_release(AphelionPool *self, PyObject *args)
{
    PyObject *buffer = NULL;
    Py_ssize_t size;
    PyObject *key = NULL;
    PyObject *bucket = NULL;

    if (!PyArg_ParseTuple(args, "O:release", &buffer)) {
        return NULL;
    }
    if (!PyByteArray_Check(buffer)) {
        PyErr_SetString(PyExc_TypeError,
                        "Pool.release expects a bytearray");
        return NULL;
    }

    size = PyByteArray_GET_SIZE(buffer);
    if (size <= 0) {
        Py_RETURN_FALSE;
    }
    self->releases += 1;

    if (self->idle_bytes + size > self->budget) {
        self->discards += 1;
        Py_RETURN_FALSE;
    }

    key = PyLong_FromSsize_t(size);
    if (key == NULL) {
        return NULL;
    }

    bucket = PyDict_GetItemWithError(self->idle, key);
    if (bucket == NULL) {
        if (PyErr_Occurred()) {
            Py_DECREF(key);
            return NULL;
        }
        bucket = PyList_New(0);
        if (bucket == NULL) {
            Py_DECREF(key);
            return NULL;
        }
        if (PyDict_SetItem(self->idle, key, bucket) != 0) {
            Py_DECREF(bucket);
            Py_DECREF(key);
            return NULL;
        }
        Py_DECREF(bucket);
        bucket = PyDict_GetItemWithError(self->idle, key);
        if (bucket == NULL) {
            Py_DECREF(key);
            return NULL;
        }
    }

    if (PyList_Append(bucket, buffer) != 0) {
        Py_DECREF(key);
        return NULL;
    }
    self->idle_bytes += size;
    Py_DECREF(key);
    Py_RETURN_TRUE;
}

PyDoc_STRVAR(pool_clear_doc,
"clear() -> None\n"
"\n"
"Drop every pooled buffer, releasing its memory immediately.\n");

static PyObject *
aphelion_pool_clear(AphelionPool *self, PyObject *ignored)
{
    (void)ignored;
    PyDict_Clear(self->idle);
    self->idle_bytes = 0;
    Py_RETURN_NONE;
}

PyDoc_STRVAR(pool_stats_doc,
"stats() -> dict\n"
"\n"
"Return the pool's byte accounting and reuse counters.\n");

static PyObject *
aphelion_pool_stats(AphelionPool *self, PyObject *ignored)
{
    PyObject *result = NULL;
    Py_ssize_t requests = self->hits + self->misses;

    (void)ignored;

    result = Py_BuildValue(
        "{s:n,s:n,s:n,s:n,s:n,s:n,s:n,s:d}",
        "idle_bytes", self->idle_bytes,
        "budget_bytes", self->budget,
        "hits", self->hits,
        "misses", self->misses,
        "releases", self->releases,
        "discards", self->discards,
        "live_buffers", (Py_ssize_t)PyDict_Size(self->idle),
        "hit_rate", requests > 0
            ? (double)self->hits / (double)requests
            : 0.0);
    return result;
}

static PyMethodDef aphelion_pool_methods[] = {
    {"acquire", (PyCFunction)aphelion_pool_acquire, METH_VARARGS,
     pool_acquire_doc},
    {"release", (PyCFunction)aphelion_pool_release, METH_VARARGS,
     pool_release_doc},
    {"clear", (PyCFunction)aphelion_pool_clear, METH_NOARGS, pool_clear_doc},
    {"stats", (PyCFunction)aphelion_pool_stats, METH_NOARGS, pool_stats_doc},
    {NULL, NULL, 0, NULL}
};

static PyTypeObject AphelionPoolType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "aphelion_native.Pool",      /* tp_name */
    sizeof(AphelionPool),        /* tp_basicsize */
    0,                           /* tp_itemsize */
    (destructor)aphelion_pool_dealloc, /* tp_dealloc */
    0,                           /* tp_vectorcall_offset */
    0,                           /* tp_getattr */
    0,                           /* tp_setattr */
    0,                           /* tp_as_async */
    0,                           /* tp_repr */
    0,                           /* tp_as_number */
    0,                           /* tp_as_sequence */
    0,                           /* tp_as_mapping */
    0,                           /* tp_hash */
    0,                           /* tp_call */
    0,                           /* tp_str */
    0,                           /* tp_getattro */
    0,                           /* tp_setattro */
    0,                           /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
    "Byte-budgeted pool of reusable frame buffers.", /* tp_doc */
    0,                           /* tp_traverse */
    0,                           /* tp_clear */
    0,                           /* tp_richcompare */
    0,                           /* tp_weaklistoffset */
    0,                           /* tp_iter */
    0,                           /* tp_iternext */
    aphelion_pool_methods,       /* tp_methods */
    0,                           /* tp_members */
    0,                           /* tp_getset */
    0,                           /* tp_base */
    0,                           /* tp_dict */
    0,                           /* tp_descr_get */
    0,                           /* tp_descr_set */
    0,                           /* tp_dictoffset */
    (initproc)aphelion_pool_init, /* tp_init */
    0,                           /* tp_alloc */
    aphelion_pool_new,           /* tp_new */
};

/* ---------------------------------------------------------------------- */
/* Module                                                                  */
/* ---------------------------------------------------------------------- */

PyDoc_STRVAR(module_doc,
"Native frame kernels and buffer pooling for the Aphelion media engine.\n"
"\n"
"Optional: the Python package detects this module at import time and falls\n"
"back to equivalent NumPy/OpenCV implementations when it is absent.\n"
"\n"
"Kernels:\n"
"    swap_bgr_rgb_inplace  in-place channel swap (no allocation)\n"
"    resize_bgr_to_rgb     fused channel swap + box downscale\n"
"    rgb_to_luma           RGB -> luma plane into a caller buffer\n"
"\n"
"Types:\n"
"    Pool                  byte-budgeted reusable frame buffers\n");

static PyMethodDef aphelion_methods[] = {
    {"swap_bgr_rgb_inplace", aphelion_swap_bgr_rgb_inplace, METH_VARARGS,
     swap_bgr_rgb_inplace_doc},
    {"resize_bgr_to_rgb", aphelion_resize_bgr_to_rgb, METH_VARARGS,
     resize_bgr_to_rgb_doc},
    {"rgb_to_luma", aphelion_rgb_to_luma, METH_VARARGS, rgb_to_luma_doc},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef aphelion_module = {
    PyModuleDef_HEAD_INIT,
    "aphelion_native",
    module_doc,
    -1,
    aphelion_methods,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC
PyInit_aphelion_native(void)
{
    PyObject *module = NULL;

    if (PyType_Ready(&AphelionPoolType) < 0) {
        return NULL;
    }

    module = PyModule_Create(&aphelion_module);
    if (module == NULL) {
        return NULL;
    }

    Py_INCREF(&AphelionPoolType);
    if (PyModule_AddObject(module, "Pool", (PyObject *)&AphelionPoolType) < 0) {
        Py_DECREF(&AphelionPoolType);
        Py_DECREF(module);
        return NULL;
    }

    if (PyModule_AddIntConstant(module, "APHELION_NATIVE_VERSION", 1) < 0) {
        Py_DECREF(module);
        return NULL;
    }

    return module;
}
