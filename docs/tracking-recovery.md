# Tracking recovery and evaluation performance

## Architecture and implementation

The existing UI-independent point tracker used a fixed grayscale template,
TM_CCOEFF_NORMED, a 0.45 confidence floor, local search, subpixel refinement,
and a minimum template standard deviation of 1. PointTrackingWorker sampled
the connected upstream frame, supported cancellation/progress, and emitted
successful coordinate pairs. Both UI entry points converted those into X/Y
AnimationCurves. Failed frames were omitted, making interpolation hide gaps.
Forward/backward tracking already supplied an ordered frame-number list.

The same tracker now returns TrackingSample records for every processed frame.
It retains the original template and the existing variance/preprocessing helpers.
Workers still own Qt signalling; the algorithm and result model have no Qt dependency.
The point tracker, Shape Tracker, worker, properties-panel controls, viewport
controls, undo/redo, and project serialization all carry the new samples.
Old documents containing only curves continue to work.

## States and samples

TrackingState contains TRACKING, LOST, and REACQUIRING. Each raw sample has
frame_number, nullable x/y, confidence, valid, predicted, state, prediction
coordinates, a reacquired flag, and a reason. Raw missing samples always have
x/y=None and valid=False. Motion predictions remain in predicted_x/y rather than
being inserted as measured curve keys. The predicted field is reserved for
explicit synthetic samples; automatic recovery stores missing samples with
separate predictions. Serialization preserves sample processing order.

The first failure enters LOST. Subsequent frames enter REACQUIRING, searching
around last_valid_position + velocity * signed_frame_delta. Search expands
from 1x to 2x to 4x (up to its configured cap). Two consistent strong candidates
are required by default. The confirmation frames remain missing; only the
confirmed reacquisition becomes a valid measurement. Timeout stops automatic
matching and source sampling; remaining requested frames are explicitly LOST.
Restart tracking to establish a new template.

Lost means unavailable/invalid frames, invalid template geometry, inadequate
texture, insufficient confidence, ambiguous appearance, impossible motion, or
an out-of-frame predicted trajectory during normal tracking. Actual measured
positions are never clamped to an image border. Predicted coordinates may lie
outside the image. Re-entry can be recovered when a confident candidate lies
within the bounded search and motion tolerance.

## Configuration on Tracker and Shape Tracker

| Property | Default | Meaning |
| --- | --- | --- |
| Track threshold | 0.45 | Continuing-track confidence floor |
| Reacquire threshold | 0.65 | Must exceed the tracking threshold |
| Max lost frames | 30 | Missing-frame recovery time limit |
| Confirmation frames | 2 | Consistent strong candidates before recovery |
| Max search multiplier | 4 | Maximum expansion of existing search radius |
| Max jump | 10% | Maximum normalized distance from predicted position |
| Ambiguity margin | 0.08 | Minimum score lead over a spatially separate competing peak |
| During gaps | Hold Last Position | Hold, interpolate, extrapolate, or disable |

The existing Pattern Size and Search Radius still apply. Invalid configuration
is reported before launching the worker. Full-frame searching is not enabled
as a separate mode; large configured regional searches can cover the image,
but remain bounded by frame geometry and maximum lost duration.

## Gap interpretation and UI

Raw gaps are preserved regardless of policy. A separate resolver implements
hold, interpolation between valid endpoints, motion extrapolation, and disabling.
Interpolation without a later valid endpoint holds the last valid position.
Point outputs include Valid, Confidence, and Predicted in addition to X/Y.
Valid always describes a measured sample, even if the selected policy provides
a substitute coordinate. Predicted marks a synthesized gap output, including
held/interpolated coordinates. Wire Valid into an effect's Enabled property
through Property Drive when it should turn off on missing frames. Disable returns
no X/Y coordinate; Shape Tracker also emits an empty mask. It does not silently
switch off arbitrary downstream effects.

The viewport labels Tracked, Lost, Reacquiring (prediction), and Reacquired.
Missing/predicted points use the untracked color. Drawing a predicted location
never converts it into measured data. Explicit manual corrections create a
manual sample and support undo; clearing tracking removes both samples and curves.

## False-match protection, direction, cancellation

The fixed template is never updated, including during loss. Tracking rejects
low variance, low scores, competing distinct peaks, excessive prediction error,
and inconsistent recovery candidates. Signed frame differences estimate velocity,
so descending and non-unit frame sequences do not assume increasing time.
Gap hold/interpolation respect the job's processing direction.

A seed whose pattern box crosses the image border is clamped to the frame
instead of being rejected, and the seed's pixel offset inside the clamped patch
is preserved so the tracked coordinate stays anchored to the chosen feature.
Only a seed whose pattern box lies entirely outside the frame (or a genuine
low-texture patch) still reports an invalid template, with a message naming the
cause rather than the generic "no frames could be matched".

Correlation searches use overlapping tiles with at most 128x128 candidate
positions per OpenCV call. Cancellation is checked between tiles, frames, and
after sampling. Debug logging records loss, recovery entry, radius changes,
rejected jumps, successful reacquisition, and timeout; no per-pixel logs.

## Performance changes

- Cache all outputs from a node's single evaluation in preview and export;
  previously, requesting another output reran the node/subgraph.
- Cache Viewer results, enabling ready-frame audio look-ahead and avoiding
  repeat display-transform work. Normal graph invalidation covers these entries.
- Reading stored point/planar tracking coordinates no longer evaluates the
  connected video source. Tracking jobs still explicitly sample that source.
- Four planar corner trackers advance together, retaining just one shared
  source frame instead of independently traversing the video four times.
- Dense animation curves use constant-time exact-key lookup instead of sorting
  and scanning the entire curve every frame.
- Unchanged exposed custom-node parameters no longer invalidate their subgraphs.
- Recovery converts local search regions only and stops source sampling after
  timeout, rather than searching indefinitely.

A reproducible synthetic benchmark is in scripts/benchmark_tracking_performance.py.
Run from the editor root:

```
.venv/Scripts/python scripts/benchmark_tracking_performance.py --baseline f72f014
```

Measured against revision f72f014 on this workspace: an eight-output blur-based
graph over 30 frames fell from 2.163 s / 240 node evaluations to 0.236 s / 30
(~9.2x). 1,000 exact lookups on a 10,000-key curve fell from 0.628 s to 0.00104 s
(~606x). Output equality is checked. These are microbenchmarks, not measured FPS
on user footage; codec, effect, image size, cache budget, and hardware still matter.
The planar test also verifies one source sample per frame (3 reads instead of 12).

## Changed files

- core/tracking/model.py: samples, states, options, gap policy/resolver.
- core/tracking/point_tracker.py and __init__.py: recovery and shared planar scheduling.
- render/tracking_worker.py: options and sample results.
- core/nodes/tracking_nodes.py and shape_tracker.py: controls, sample persistence, gap outputs.
- core/serialization.py: gap-policy enum restoration.
- core/history/commands.py: sample-aware undo/redo and manual correction.
- ui/widgets/tracking_actions.py, properties.py, tracker_overlay.py: both job entry points and state feedback.
- core/nodes/base.py, core/project.py: required-input hook and complete output caching.
- core/animation/curve.py: exact-key lookup.
- core/nodes/custom_nodes.py: avoid unchanged-parameter invalidation.
- tests/test_tracking_recovery.py and test_tracking_graph_integration.py: regression coverage.
- scripts/benchmark_tracking_performance.py: repeatable benchmark.

## Validation and limits

Deterministic NumPy/OpenCV tests cover uninterrupted motion, temporary occlusion,
exit/re-entry, permanent exit/timeouts, low-confidence matches, impossible jumps,
long gaps, edge searches, backward recovery, cancellation during recovery and
inside tiled matching, low-variance templates, fixed-template preservation,
explicit invalid samples, clean recovery transitions, competing identical textures,
gap policies, persistence, undo/manual edits, empty masks, source-decode avoidance,
and shared-output caching. Broader test results are recorded in the delivery message.

Fixed-template correlation cannot establish identity between truly indistinguishable
objects or recover arbitrary rotation, scale, deformation, or long occlusions.
Constant-velocity prediction can miss abrupt direction changes outside the configured
search/tolerance. Large templates can still make an individual tile or upstream
frame decode slow; cancellation is cooperative, not an interruption inside OpenCV
or a decoder. The legacy planar public API continues to expose successful corner
curves; explicit gap controls and persisted samples are provided by the point and
Shape Tracker nodes. Old tracks need retracking to gain historical loss metadata.
