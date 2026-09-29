# Export resource controls

Auto still tests and selects hardware encoders; explicit hardware choices and
parallel frame rendering remain available. A reported black-screen lockup on
2026-09-29 prompted tighter resource bounds. Windows logged an unclean restart
with BugcheckCode 0, which does not establish its cause.

* QSV uses `async_depth=1` and its supported NV12 input format.
* NVENC has four surfaces and zero extra output delay.
* RGB handoff is capped at four frames and 64 MiB (two frames at 4K).
* Admission reserves 512–2048 MiB for the desktop/shared GPU and uses at most
  half the remaining available RAM. Insufficient memory produces an export
  error before allocating the frame queue.
* Render concurrency uses actual rendered dimensions, float working storage,
  and decoder retention, rather than assuming project dimensions equal media
  dimensions. Codec workers are limited to a quarter of logical CPUs, capped
  at four. Export decode retention is limited to two frames and 32 MiB per
  decoder, independently of interactive cache preferences.

Verification: 69 focused tests passed, including resource-budget and hardware
selection regressions. A 320x180 Auto export selected h264_qsv and all 12 frames
decoded correctly. This is a low-load smoke test, not evidence that an unknown
driver/system lockup cannot recur on a long 4K export.

## Follow-up: software export also froze

The user reproduced a whole-system freeze with Software selected as well as
Auto. Hardware encoding is therefore not the only possible trigger. The shared
render path now clears input-socket references and scratch outputs after each
export frame, reclaims regenerable live preview cache before cloning the graph,
coordinates OpenCV's thread pool, and checks working-memory headroom before each
node. Allocation failures propagate to export cleanup instead of becoming empty
frames that can trigger further downstream allocations. Encoder pipe writes also
have a stall watchdog; this cannot recover a kernel or driver hang.

A single-frame diagnostic of the user's project ran in a separate Windows Job
Object with a 2 GiB memory ceiling and 25% CPU cap, without any encoder. It passed
through multiple effects and both video sources, then the working-memory guard
raised MemoryError before the next effect. This verifies controlled refusal
under observed memory pressure, not successful completion of the full export or
proof of the earlier freezes' root cause. No full-resolution stress export was
used to validate these safeguards.
