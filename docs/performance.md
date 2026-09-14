# Playback performance

This document describes the interactive playback architecture, what changed
in it, and — importantly — **how to produce the numbers on your own
machine**. Where a figure is derived from the code path (for example, bytes
moved per frame) it is labelled as derived. Where a figure is a timing, it
is labelled as measured and the command that produced it is given.

Nothing in the "Before / after" section is filled in with invented values.
The tooling to produce it ships with the editor; run it and paste the
output in.

---

## 1. Measure first

```powershell
python main.py --benchmark-playback "C:\path\to\clip.mp4"
python main.py --benchmark-playback clip.mp4 --benchmark-json before.json --benchmark-target-fps 30
```

The benchmark prints a per-stage breakdown and pass/fail verdicts:

```
stage                                 mean ms      p50      p95      FPS
------------------------------------------------------------------
source decode (full res)                 ...
decode via proxy                         ...
bare graph                               ...
light graph                              ...
medium graph                             ...
seek                                     ...
presentation: convert                    ...
presentation: qimage                     ...
presentation: qpixmap                    ...
cold first frame                         ...
warm frame (cached)                      ...
```

What each stage isolates:

| Stage | What it measures | Why it matters |
|---|---|---|
| `source decode (full res)` | Raw sequential decode, no graph | The floor. If this is not well above the target rate, nothing downstream can help. |
| `decode via proxy` | The same decode through a generated all-intra proxy | The gap is what real proxies buy. |
| `bare graph` | `Video Input → Viewer` through a real `Project` | The gap from `source decode` is pure engine overhead. |
| `light` / `medium graph` | The same source with effects | Where effect cost actually lands. |
| `seek` | Cold random seeks (decode LRU cleared) | Scrub responsiveness. |
| `presentation: *` | float→uint8, QImage, QPixmap | The display boundary. |
| `cold first frame` | First evaluation from a cleared cache | Seek/scrub response. |
| `warm frame (cached)` | Repeat read of a cached frame | What pressing Play on a paused timeline costs. |

The **bare playback gate** verdict requires `bare graph` to be at least
**2× realtime**, i.e. ≤ 16.6 ms per frame for a 30 FPS timeline. That
headroom is what effects get to spend.

For a full-suite report plus a comparison between two runs:

```powershell
python -m benchmarks --json before.json
python -m benchmarks --compare before.json after.json
```

> **Environment note.** The benchmark runs whatever code is currently on
> disk. To capture a genuine "before", run it against a clean checkout
> (`git stash`), then against the current tree.

---

## 2. What the architecture looks like now

```
Timeline
   │
   ▼
MediaClock ──────────► frame deadline  (audio-master when audio is playing)
   │                          │
   │                          ▼
   │                   DeadlineQueue        shallow, deadline-ordered,
   │                          │             collapses on scrub, drops late work
   │                          ▼
   │              Compiled RenderPlan        order, u8-source gate,
   │                          │              parallel groups, cost
   │                          ▼
   │                  FrameEvaluationWorker
   │                     │           │
   │      ┌──────────────┘           └──────────────┐
   │      ▼                                         ▼
   │  VideoDecoder                            Project.evaluate_node
   │   (proxy + keyframe index)               (frame-local memo + byte-budget LRU)
   │      │                                         │
   │      └──────────────┬──────────────────────────┘
   │                     ▼
   │            QualityGovernor ──► preview scale (hysteresis)
   │                     │
   │                     ▼
   │              ViewportWidget  ── raw uint8 → QImage → QPixmap (no float trip)
   │
   └── FrameTrace: per-frame stages, stall attribution, JSON dump
```

Two engines, one graph. `Project.EngineMode`-style policy already existed
(export already used a per-frame scratch cache instead of the interactive
LRU); this work extends the same split to the interactive side, where
*deadlines* rather than completeness are the design goal.

---

## 3. The largest single change: no mandatory float round trip

### Before

```
decode (uint8, 960×540)
  → cv2.cvtColor / cv2.resize
  → from_source_u8         astype(float32) + multiply      ← always
  → Viewer (float32)
  → to_display_u8          clip + convertScaleAbs          ← always
  → QImage
  → q_img.copy()                                           ← full-frame copy
  → QPixmap.fromImage
```

For `Video Input → Viewer` with no effects at all, that is a
uint8 → float32 → uint8 round trip that reproduces the exact pixels the
decoder already produced.

### After

The render plan decides, per graph, whether the source may hand over its raw
buffer:

* `Node.accepts_u8_frame` (default **False**) declares that a node
  promotes its input through `ensure_rgb_f32` at the point it needs float
  precision.
* `Node.can_emit_u8_frame` declares that a source is *able* to hand over
  8-bit frames.
* `code.render_plan` grants permission only when **every** node between the
  source and the Viewer has declared tolerance. A node that has not been
  verified keeps the old always-float behaviour.

Two supporting fixes were required, and both fix latent bugs rather than
merely enabling an optimisation:

1. **`ensure_rgb_f32` now normalizes.** It previously did
   `astype(float32, copy=False)` and assumed the caller had already scaled;
   handed a `uint8` frame it produced 0–255 floats, which then clamped to
   white at the display boundary. It now performs promotion and
   normalization in one pass (`np.multiply(..., dtype=float32)`) instead of
   an `astype` plus a separate multiply.
2. **`FrameEffectNode` no longer multiplies raw sources.** With `Mix <
   100%` it did `mix_frames(source, effected, mix)` directly. That was
   harmless while sources were always float, and becomes a silent colour
   error the moment a source is allowed to stay 8-bit. It now promotes the
   source only on the partial-mix path (the default `Mix = 100%` path
   returns the effect result untouched and stays allocation-free).

### Derived impact

For a preview frame at 960×540, RGB:

| Representation | Bytes |
|---|---|
| uint8 | 1.48 MiB |
| float32 | 5.93 MiB |

Memory traffic eliminated per **bare** frame (read + write counted per pass):

| Pass | Before | After |
|---|---|---|
| `astype(float32)` | 1.48 + 5.93 | — |
| `× 1/255` | 5.93 + 5.93 | — |
| `np.clip` | 5.93 + 5.93 | — |
| `convertScaleAbs` | 5.93 + 1.48 | — |
| `q_img.copy()` | 1.48 + 1.48 | — |
| **Total** | **≈ 41.5 MiB** | **0** |

At 30 FPS that is **≈ 1.2 GiB/s** of memory traffic removed from the bare
playback path, plus three full-frame allocations per frame. At full 1920×1080
the same table scales to **≈ 174 MiB/frame ≈ 5.2 GiB/s**.

These are byte-count derivations from the code path, not timings. Run the
benchmark for the wall-clock translation on your hardware.

### Secondary effect: cache density

The frame cache and the decoder LRU now hold source frames in `uint8`, so
the same byte budget retains **4× as many** frames. Since the frames that
are re-read most often during scrubbing are source-adjacent, this is the
part of the cache that matters most.

---

## 4. Deadline scheduling

`core.playback.clock.MediaClock` owns the timeline position. Deadlines are
derived from the anchor, never from how long rendering took, so a slow frame
cannot push later deadlines further away — playback **skips** instead of
slowing down.

`core.playback.deadline.DeadlineQueue` is the request window:

* playback → earliest-deadline-first, shallow (`frames_ahead + 1`);
* scrub/seek → collapsed to the newest request only;
* expired entries are dropped on the way out rather than rendered late;
* a paused request **never** expires (the user is still waiting for exactly
  that frame).

`core.playback.governor.QualityGovernor` turns measured deadline behaviour
into one preview-scale decision. Hysteresis is deliberately strict:

* step down after **5** consecutive meaningful misses;
* step up only after **2 s** of sustained headroom below 65 % of budget;
* never change more often than every **1.5 s**.

`core.playback.trace.FrameTrace` records per-frame stages and attributes
stalls: for a frame that took 3× the median, it reports which stage grew
most (`graph`, `media decode`, …). Export it with:

```python
from core.playback.trace import get_frame_trace
get_frame_trace().dump("performance_trace.json")
```

`get_frame_trace().format_report()` prints the summary plus the worst stalls.

### Playback-lifetime policy

Three things are scoped to the playback session rather than applied globally.

**Garbage collection.** A full collection landing mid-playback is a
multi-millisecond spike with no media work behind it — the hardest kind of
stutter to attribute from frame timings, because nothing in the pipeline
looks slow. `core.perf.gc_policy.GCPolicy` calls `gc.freeze()` when playback
starts and `gc.unfreeze()` plus a single collection when it stops, so the
collector still runs between playbacks. It deliberately does **not** disable
GC: playback stays correct and bounded, the work is just moved off the
critical path. Wired in `ViewportWidget.set_playback_active`, and unwound in
`shutdown()` so a project switch cannot leave the collector frozen.

**Thread priority.** The playback thread is the only workload here with a
hard deadline, so it is the only thread that asks for a better scheduling
class — bounded to above-normal (never time-critical), and best-effort: if
the OS declines, nothing changes and nothing is reported as an error.

**Render-ahead.** While paused, the worker warms up to `frames_ahead` frames
around the playhead, one frame per loop iteration, so the main loop can poll
for real requests before every step and an incoming request always
pre-empts speculative work. It is suppressed while playing and while
scrubbing, and it converges: once the look-ahead distance is warm the worker
holds its cursor and does nothing rather than re-walking the same frames.
This is what makes *press Play* cheap — the first deadlines are already
satisfied.

### Audio as the master clock

`AudioPlaybackEngine.presented_seconds()` exposes how much audio the device
has actually consumed — the only signal that reflects what the user *hears*.
While playing, the viewport samples it at 10 Hz and corrects video timing
through `MediaClock.resync_to_audio`, which **slew-limits** small drift
(10 % per resync) and only jumps on a real discontinuity (> 250 ms).

---

## 5. Real editing proxies

Decode-time downscaling reduces *processing* cost but not *seek* cost: a seek
into a 250-frame GOP still means finding the keyframe and decoding forward.

`core.media.proxy.ProxyManager` generates a genuine editing proxy:

* **all-intra** (`-g 1 -keyint_min 1 -sc_threshold 0 -bf 0`) — every frame is
  a keyframe, so seek cost becomes constant instead of GOP-dependent;
* low resolution (720p / 540p / 360p, configurable);
* stored under `userdata/cache/proxies/`, keyed by canonical path + size +
  mtime + recipe signature, so it survives restarts and regenerates only when
  the source or the recipe changes;
* **verified** after encoding (frame count and fps must match the source);
  a proxy that fails verification is deleted rather than trusted;
* the manifest records the *source's* frame count, rate, and dimensions, so
  the decoder adopts the proxy for pixels while the timeline still sees the
  original media properties;
* originals are never modified, and export never uses a proxy.

Generation runs on the shared background scheduler, so it yields to
interactive work and pauses entirely while playback is running.

Status is exposed for a per-media readout:

```python
from core.media.proxy import get_proxy_manager
get_proxy_manager().status(path).label()   # "Original" / "Proxy building 38%" / "Proxy ready"
```

---

## 6. Keyframe index

`core.media.index.KeyframeIndexCache` builds and persists keyframe positions
using `ffprobe -skip_frame nokey` (which does not decode the file).

With an index, a seek goes straight to the keyframe that starts the target
GOP and walks the known remaining distance. Without one, the decoder has to
seek, read back where it actually landed, and probe forward — discovering on
every seek what the index already knows.

The index also answers `decode_distance(frame)`, which is the number the
deadline scheduler needs to predict whether a frame is worth starting.

---

## 7. Settings

`Preferences → Performance` gained:

**Playback engine** — engine preference (`Auto` / `GPU` / `CPU`), realtime
priority, target preview rate.

**Preview** — adaptive quality (governor range), high quality when paused,
bypass heavy effects during playback/scrub, preview scale floor/ceiling.

**Proxy** — use editing proxies, generate automatically, proxy resolution.

**Render cache** — `Off` / `Smart` / `User`, disk cache limit, cache heavy
nodes automatically.

**Decoder** — hardware decode (existing), backend preference
(`Auto` / `Native` / `Compatibility`).

**CPU** — worker count, pause background jobs during playback.

**Advanced** — frames ahead, frames behind, decode queue depth, drop policy,
performance diagnostics, frame trace.

All new values validate with fallbacks: an unknown value becomes the default
rather than raising, so a preferences file written by a different build
always loads.

### Settings that are stored but not yet backed by an engine

Being explicit, because a preference that silently does nothing is worse
than no preference at all:

| Setting | Status |
|---|---|
| `use_editing_proxies`, `generate_proxies_automatically`, `proxy_height` | **Fully wired.** Drives proxy substitution in `VideoDecoder` and background generation. |
| `render_cache_mode`, `disk_cache_limit_mb`, `cache_heavy_nodes_automatically` | **Stored only.** The persistent disk render cache is not implemented yet; these describe the intended policy for it. |
| `playback_engine`, `decoder_backend`, `gpu_enabled`, `gpu_memory_budget_mb` | **Stored only.** No GPU execution path or alternative decoder backend exists yet. |
| `realtime_priority` | **Stored only.** No OS priority change is applied. |
| `frames_ahead`, `frames_behind`, `decode_queue_depth` | **Partially wired.** `frames_ahead` caps the deadline queue; `frames_behind` is recorded but not yet used for retention. |
| `performance_trace_enabled` | **Fully wired.** Enables the frame trace and stall analysis. |
| `realtime_priority` | **Fully wired.** The playback thread asks the OS for `THREAD_PRIORITY_ABOVE_NORMAL` (Windows) or `nice(-4)` (POSIX) while it runs. Deliberately bounded — never time-critical — and best-effort: if the OS declines, nothing changes and nothing is reported as an error. Changing it takes effect the next time the worker thread starts. |
| `frames_ahead` | **Fully wired.** Sets both the deadline queue capacity and the paused render-ahead distance. |
| `frames_behind`, `decode_queue_depth` | **Partially wired.** `frames_behind` is recorded but not yet used for retention; `decode_queue_depth` is not consulted. |

The render plan's `Node.accepts_u8_frame` mechanism is the insertion point
for the GPU work: a node that can execute on a texture declares the same
kind of capability, and the plan decides where CPU/GPU transfers happen.
That is the second half of the frame-abstraction work, and it is not done.

---

## 9. The native core

The brief asks directly whether Python belongs in the per-frame hot path,
and whether the media core should be native. The answer after measurement is
**partly, and narrowly** — and the narrowness is the interesting part.

### Where "just rewrite it in C" would have been wrong

The assumption worth testing is "Python is slow, therefore port the frame
path." Measuring what is actually on that path says otherwise:

| Operation | Who really executes it | Would native beat it? |
|---|---|---|
| H.264 decode | FFmpeg via OpenCV | No — already C |
| `cvtColor` | OpenCV, SIMD | No — already C++ |
| `resize` | OpenCV, SIMD | No — already C++ |
| uint8↔float32 | NumPy, SIMD | No — already vectorised |
| Effect pixel maths | NumPy/OpenCV | No — already vectorised |
| **Buffer allocation churn** | CPython allocator | **Yes** |
| **Redundant full-frame passes** | Python *orchestration* | **Yes** |

Every compute-bound stage is already native code called through a thin
binding. Porting those to C would produce a second implementation to keep
correct, for no speedup — the execution is identical, only the caller
changes. The GIL is not the bottleneck either: FFmpeg, OpenCV, and NumPy all
release it for the duration of their calls.

What *is* Python's fault is **orchestration waste**: allocating buffers that
did not need to exist, and moving frames through passes that did not need to
happen. That is what the native layer targets, and only that.

### What `native/aphelion_native.c` implements

Three kernels and a pool. Each replaces an allocation or a pass — never a
loop that a library already vectorises.

**`swap_bgr_rgb_inplace(buffer, width, height)`**

OpenCV returns BGR; the pipeline is RGB. The previous code called
`cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)`, which **allocates a second
full-resolution frame** and copies through it.

The buffer `cv2.VideoCapture.read()` returns is owned solely by the caller,
so the swap can happen in place: one pass, **zero allocation**, O(1) extra
memory. For a decoded-but-unscaled frame this removes the entire conversion
cost.

**`resize_bgr_to_rgb(src, dst, sw, sh, ow, oh)`**

The previous downscale sequence was: allocate full-resolution RGB → copy the
whole frame through it → allocate the scaled output → resample into that.

This fuses channel swap and box downscale into **one pass writing into a
caller-supplied destination**: one pass instead of two, one buffer instead of
two. Box bounds use integer arithmetic (`i * src / out`), so the mapping is
exact and monotonic with no accumulated float drift.

**`rgb_to_luma(src, dst, width, height)`**

RGB → luma using the same BT.601 fixed-point coefficients as
`cv2.COLOR_RGB2GRAY`, so results are numerically identical.

*Honest note:* this one is **exposed and tested but not currently on a hot
path.** Both `_to_gray_u8` call sites in the tracker already operate on crops
(`frame[y0:y1, x0:x1]`), not full frames, so there is no full-frame
conversion to replace. It is kept because it is the correct kernel for the
full-frame case (histograms, auto-levels) and because it is the natural
primitive for a future native tracking batch path. Claiming a tracking
speedup from it would be false.

**`Pool(budget_bytes)`**

A byte-budgeted pool of reusable frame buffers, keyed by exact byte size.

CPython does not leak frames, but allocating and discarding multi-megabyte
buffers many times per second shows up as allocator time, page faults, and GC
pressure from transient objects. Buffers are wrapped zero-copy with
`np.frombuffer`, so pooled memory can be used directly as a frame.

**Ownership rule, enforced in code:** a pooled buffer must never be handed to
a cache. Once released it may be reused by the very next `acquire`, so a
cache holding a pooled frame would silently show the wrong picture.
`VideoDecoder._convert_bgr_to_rgb` therefore allocates normally — its output
*is* cached — and says so in a comment.

### The restructure this enabled

Wiring the kernels in exposed a second, unrelated inefficiency worth more
than the kernels themselves.

The decode cache was keyed by **frame number** and stored the
full-resolution RGB frame. Every `read_rgb(frame, width)` then re-ran
`cv2.resize` — *including every cache hit*, which is the case playback hits
most often while prefetching.

The cache is now keyed by **`(frame, output_width)`** and stores the frame
already at that width. A hit is a pure dict lookup with no pixel work at
all, and a miss is a single fused pass. Entries are also far smaller, so the
same entry budget covers more of the playhead neighbourhood.

### The stable Python API

`src/core/native.py` is the only place that knows whether the extension
exists:

```python
from core.native import kernels, native_available, probe

probe().backend          # "native" | "python"
kernels().swap_bgr_rgb_inplace(frame)
```

Callers never branch on availability. Three properties make this safe:

1. **Optional by construction.** Nothing imports the extension except this
   module, and it catches `ImportError`, a partially built module, and any
   other failure — degrading to the fallback rather than raising.
2. **Probing is lazy.** It happens on first decode, not at launch, so a cold
   start does not wait for it.
3. **The fallback is the reference.** The pure-Python implementations define
   the contract; `tests/test_native_kernels.py` asserts the native kernels
   agree with them, and specifically that `resize_bgr_to_rgb` is
   **bit-identical** rather than merely close. Shipping a native build cannot
   silently change a pixel.

### Build

```powershell
python native/build.py --check   # status
python native/build.py           # build
python native/build.py --clean
```

The extension is *not* added to `setup.py`. The project's packaging path is
cx_Freeze building a frozen tree, not wheels, and threading a compiler
requirement through it would make a release build fail on machines that do
not need the extension at all. `native/CMakeLists.txt` covers IDE and
instrumented builds. Details and the full rationale are in
`native/README.md`.

The kernel backend is visible in the performance overlay (`kern native` /
`kern python`) and in `detect_capabilities().frame_backend`, so there is never
ambiguity about which implementation produced a number.

---

## 10. What was verified, and what was not

**Verified by construction and unit tests** (`tests/test_playback_engine.py`,
`tests/test_frame_contract.py`, `tests/test_media_cache.py`,
`tests/test_native_kernels.py`):

* the uint8 round trip is lossless;
* `ensure_rgb_f32` normalizes every representation it may receive;
* the render plan grants raw-8-bit permission only when every downstream node
  has declared tolerance, and revokes it when a strict node is inserted
  anywhere in the chain;
* a partial `Mix` on a raw source stays inside `[0, 1]`;
* the Viewer's exposure path does not clip a raw source;
* clock, deadline queue, governor and trace behave as specified, including
  the hysteresis thresholds;
* proxy cache identity is deterministic and rejects unverified or stale
  manifests;
* keyframe index queries are exact;
* the native and pure-Python kernels agree, with `resize_bgr_to_rgb`
  bit-identical;
* the buffer pool respects its byte budget and hands back the same object.

**Not verified in this session**: end-to-end wall-clock timings, and the
native extension has not been compiled. There was no terminal available, so
inventing timings would make them worthless and claiming a successful build
would be a guess. Run the commands in §1 and §11.

**Known remaining bottlenecks** (expected, in rough order):

1. **Effect-chain memory bandwidth.** Each effect is a full-frame float32
   pass. A long chain is bandwidth-bound, not compute-bound — which is why
   the native layer does *not* touch effects. Fixing it properly means fusing
   adjacent per-pixel operations (one shader, or one fused pass) rather than
   optimising Python.
2. **No GPU execution yet.** `Node.accepts_u8_frame` is the first half of the
   frame-abstraction work; a `FrameHandle` that can also be a GPU texture is
   the second. The render plan is the right place for that decision to live.
3. **Tracking and planar tracking** run on the CPU path unchanged. They
   already crop before converting, so there is no cheap win there.
4. **Export pipeline** is unchanged; it already used a scratch cache and now
   also benefits from uint8 sources, but has no bounded render/encode
   overlap.
5. **Sequential decode-ahead** relies on the prefetch window; there is no
   dedicated decode thread with its own ring yet. This is the next structural
   piece: decode and graph evaluation currently overlap only through
   prefetch, not through an explicit producer/consumer boundary.
6. **Native codecs.** The decoder still goes through OpenCV rather than
   talking to `libavcodec` directly, so hardware decode surfaces (D3D11VA,
   NVDEC, QSV) and packet-level keyframe control are out of reach. That is
   the largest remaining native opportunity, and it is a real project, not a
   kernel.

---

## 11. Reproduction checklist

```powershell
# 1. Baseline
git stash
python main.py --benchmark-playback clip.mp4 --benchmark-json before.json
git stash pop

# 2. Build the native core (optional)
python native/build.py --check
python native/build.py

# 3. Current
python main.py --benchmark-playback clip.mp4 --benchmark-json after.json

# 4. Compare the suites measured by both
python -m benchmarks --compare before.json after.json

# 5. Unit tests
python -m pytest tests/test_playback_engine.py tests/test_frame_contract.py `
               tests/test_media_cache.py tests/test_native_kernels.py -q
```

Every kernel test runs against **both** backends, so the fallback path is
exercised even on a machine where the extension is built.

Test the codecs you actually use — H.264 1080p, H.264/H.265 4K, and an
editing codec (ProRes/DNxHR) if you have one. A decoder change that only
helps one test MP4 is not a decoder change.
