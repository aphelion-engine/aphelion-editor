# Aphelion native core

Optional C acceleration for the media engine. **Everything here is optional** —
the editor runs unchanged without it.

## Build

```powershell
python native/build.py --check   # is it built?
python native/build.py           # build it
python native/build.py --clean   # remove artefacts
```

Needs a C compiler and the Python headers: Visual Studio Build Tools on
Windows, `build-essential` + `python3-dev` on Linux, Xcode Command Line Tools
on macOS. A CMake project (`CMakeLists.txt`) is also provided for IDE builds.

After building, verify with:

```powershell
python main.py --benchmark-playback some-clip.mp4
```

The report's `notes` section and `core.native.probe().backend` will say
`native` instead of `python`.

## What is native, and why only this

The rule for putting a kernel here is narrow: **native must beat calling into
NumPy or OpenCV.** NumPy is already SIMD-optimised, and OpenCV is already a
C++ library, so duplicating their work in C would add a build dependency and a
second implementation to keep correct for no gain.

That leaves operations that are not compute-bound but *allocation-* or
*pass-bound* — where the win comes from removing a buffer and a memory pass,
not from a faster loop.

### `swap_bgr_rgb_inplace(buffer, width, height)`

Replaces `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)` on the decode path.

OpenCV returns BGR and the pipeline is RGB, so every decoded frame was going
through `cvtColor`, which **allocates a second full frame** and copies through
it. Because the buffer `cv2.VideoCapture.read()` returns is owned solely by
the caller, the swap can be done in place: one pass, no allocation, O(1) extra
memory.

### `resize_bgr_to_rgb(src, dst, sw, sh, ow, oh)`

Replaces `cvtColor` + `cv2.resize` on the proxy/downscale path.

The previous sequence was: allocate full-resolution RGB, copy the whole frame
through it, allocate the scaled output, resample into that. This fuses both
into a single box-filter pass that writes into a caller-supplied destination —
one pass instead of two, one buffer instead of two.

Box bounds use integer arithmetic (`i * src / out`) rather than floating
point, so the mapping is exact, monotonic, and free of accumulated drift.

### `rgb_to_luma(src, dst, width, height)`

RGB → luma plane, using the same BT.601 fixed-point coefficients as
`cv2.COLOR_RGB2GRAY`, so tracking and histogram results are unchanged. The win
is writing into a caller buffer instead of allocating per call.

### `Pool(budget_bytes=...)`

A byte-budgeted pool of reusable frame buffers.

The pipeline allocates and discards multi-megabyte frames many times a second.
CPython handles that without leaking, but the churn is visible as allocator
time, page faults, and GC pressure from transient objects. Buffers are keyed
by exact byte size — correct for video, where geometry repeats for long
stretches so exact-size hits dominate and no splitting logic is needed.

**Ownership rule:** a pooled buffer must not be handed to a cache. Once
released it may be reused by the very next acquire. See
`VideoDecoder._convert_bgr_to_rgb`, which deliberately allocates normally
because its output is cached and can outlive any borrowing scheme.

## What is deliberately *not* here

| Candidate | Why not |
|---|---|
| uint8↔float32 conversion | `np.multiply(..., dtype=np.float32)` is already a single vectorised pass. |
| Blur, colour, keying | OpenCV and NumPy already run these in native SIMD code. |
| Frame cache | Python-side; the win was a byte budget and key shape, not language. |
| Queue / scheduling | The GIL is not the bottleneck — the work is in native libraries that release it. |
| GPU backends | A real change, but it needs a working GPU path first, not a C shim. |

The "very important failure condition" in the brief — that the architecture
must not still be `OpenCV → NumPy float32 → Python node → … → QPixmap` for
every frame — is addressed in the Python layer, where the actual waste was:
the eager float promotion and the redundant copy are gone. See
`docs/performance.md`.

## Correctness contract

The pure-Python implementations in `src/core/native.py` are the *reference*.
The C kernels must agree with them bit-for-bit, and
`tests/test_native_kernels.py` checks that directly whenever the extension is
present. `resize_bgr_to_rgb` in particular must be bit-identical (not merely
close), which the integer box arithmetic guarantees and the test enforces.
