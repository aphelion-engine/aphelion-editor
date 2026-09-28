# Building a Robust Multi-Tracker Compositing Pipeline

This is the advanced systems walkthrough. One source video fans out into
independent floor, wall, object, and camera tracking branches. The resulting
data is reused by corner-pin inserts, a motion-driven transform, a numeric
distance diagnostic, and a final compositing chain.

![Final enterprise graph](images/04-final-graph.png)

## What We Are Building

The graph is organized into four conceptual areas:

```text
INPUT
  Video Input.frame

TRACKING
  -> Floor Tracker
  -> Wall Tracker
  -> Object Tracker
  -> Camera Tracker

GEOMETRY + MOTION
  Floor/Wall corner values -> Corner Pin nodes
  Camera translation_x/y -> Transform 2D.in_translate_x/y
  Object.x/y + Floor.top_left_x/y -> Track Distance

COMPOSITING
  Floor insert -> floor Merge -> wall Merge
  Motion-driven image -> final Merge
  final Merge.frame -> Viewer.frame
```

The complete graph is stored in `graph.apgraph`. It is deliberately a real
graph file, not a diagram-only approximation: every connection validates
against the live node registry.

## Tracker Selection

Use the tracker that matches the target model:

- `Floor Tracker`: a planar surface specialization for a floor or road.
- `Wall Tracker`: a planar surface specialization for a vertical wall.
- `Object Tracker`: a point/object-oriented long-term tracker with real
  properties `mode`, `use_gpu`, `deep_recovery`, and `reidentification`.
- `Camera Tracker`: the registered camera-motion node. Its current graph
  outputs include `translation_x`, `translation_y`, `rotation`, `scale`, and
  `inliers` in addition to the inherited point diagnostics.

The two surface nodes expose corner streams rather than a nonexistent
`Homography` port. The downstream `Corner Pin` nodes are the projective
consumers. This is an important graph-design rule: use the actual output type
that the current node exposes.

## Step 1: Split the Source Correctly

![Initial pipeline](images/01-initial-graph.png)

Connect `Video Input.frame` separately to:

```text
Floor Tracker.frame
Wall Tracker.frame
Object Tracker.frame
Camera Tracker.frame
```

Each connection transfers a `FrameWithAudio` stream. The branches do not imply
that one tracker consumes another track's image; they all inspect the same
original source. This prevents a warped composite or an occluder-contaminated
branch from becoming tracking input.

## Step 2: Configure the Four Trackers

![Tracking branches](images/02-tracking.png)

### Floor and Wall

Set the four seed property pairs on both planar nodes. Their actual tunables
are `region_size` and `search_radius`; the seed coordinates are percent values.
Use a region large enough to cover distributed detail, but keep it on one
physical plane. Their outputs include:

```text
confidence, inliers, reprojection_error, valid
top_left_x, top_left_y
top_right_x, top_right_y
bottom_right_x, bottom_right_y
bottom_left_x, bottom_left_y
visible, predicted, state, backend
```

### Object Tracker

Set its actual point/appearance properties as needed:

- `center_x`, `center_y`, `region_size`, `search_radius`
- `track_threshold`, `reacquire_threshold`
- `max_lost_frames`, `confirmation_frames`
- `max_search_multiplier`, `max_jump`, `ambiguity_margin`
- `gap_policy`
- `mode`, `use_gpu`, `deep_recovery`, `reidentification`

`mode` is the real quality selector. Use `BALANCED` for editorial iteration
and `ACCURATE` or `MAXIMUM` for difficult final passes. `deep_recovery` and
`reidentification` are switches for the optional recovery layers; they do not
mean that every installation has a downloaded neural model.

### Camera Tracker

The current registered node shares the tracker configuration surface and adds
`translation_x`, `translation_y`, `rotation`, `scale`, and `inliers`. Treat
these as motion data. `inliers` is useful for diagnosing whether the dominant
motion is supported by enough background features.

## Step 3: Reuse Geometry in Compositing

![Geometry and composite branches](images/03-effect-composite.png)

Both `Corner Pin` nodes use the same eight-corner connection pattern. For each
surface:

```text
Floor Tracker.top_left_x     -> Floor Corner Pin.in_top_left_x
Floor Tracker.top_left_y     -> Floor Corner Pin.in_top_left_y
...
Wall Tracker.bottom_left_x   -> Wall Corner Pin.in_bottom_left_x
Wall Tracker.bottom_left_y   -> Wall Corner Pin.in_bottom_left_y
```

The ellipsis means the same real mapping for the other three corners; the graph
file contains all sixteen connections explicitly. Each `Corner Pin.frame`
receives an `Image Input.frame`. The floor pin becomes `floor_comp.foreground`;
the source video is `floor_comp.background`. That result becomes the wall
composition background, and the wall pin becomes its foreground.

This dataflow preserves the distinction between geometry and pixels:

```text
Floor Tracker.top_left_x (Float)
  -> Corner Pin.in_top_left_x (Float)
```

The value is a scalar corner coordinate, not an image. `Corner Pin` combines
all eight scalar streams to form the perspective warp.

## Step 4: Use Camera Motion and Object Data as Graph Data

`tracked_image.frame` feeds `Transform 2D.frame`. The camera branch connects:

```text
Camera Tracker.translation_x -> Transform 2D.in_translate_x
Camera Tracker.translation_y -> Transform 2D.in_translate_y
```

These are numeric modulation inputs. The transform therefore receives an
ordinary source image and a global motion signal. It can be used for a motion
matched graphic or a stabilization experiment without modifying the floor or
wall tracks.

The diagnostic branch connects:

```text
Object Tracker.x            -> Track Distance.x1
Object Tracker.y            -> Track Distance.y1
Floor Tracker.top_left_x    -> Track Distance.x2
Floor Tracker.top_left_y    -> Track Distance.y2
```

`Track Distance` outputs `distance`, `angle`, `mid_x`, and `mid_y`. These are
percent-coordinate measurements useful for debugging or later numeric control.
They are not a substitute for the object's mask; the current `Object Tracker`
does not expose a mask or bounding-box port.

## Recovery and Long-Term Stability

The branches use different evidence models. Short-term flow is efficient when
the image is stable. Reference matching and re-identification become important
after a whip pan, a person crossing the target, severe blur, or an off-screen
interval. Planar branches estimate a full projective update and reject low
inlier/high-error candidates instead of replacing the last trusted transform.

The shared lifecycle distinguishes measured and predicted results. A surface
can be `PARTIALLY_OFFSCREEN`, `MOSTLY_OFFSCREEN`, `OFFSCREEN`, or
`SEARCHING_FOR_REENTRY` while its full polygon remains outside the visible
image. The `predicted` output identifies motion-model geometry. A later
reference match must pass geometric verification before the state becomes
`REACQUIRED`.

Do not add recovery frames to reference memory while the state is weak,
occluded, predicted, or searching. That is how a foreground person or a frame
border becomes a false target.

## Confidence and State in Practice

The graph exposes confidence and state as numeric outputs because the current
socket system is strongly typed around `Number`. They are useful for inspection
and future control nodes, but this graph does not pretend that a numeric state
code is a textual enum socket. Read the hover documentation and node schema for
the output meanings. Keep `valid` and `predicted` distinct when deciding
whether to treat a frame as direct evidence.

## Performance Strategy

Start all trackers in `BALANCED` mode and use proxy footage while designing the
graph. The expensive part is global/recovery matching, not ordinary graph
evaluation. Enable `deep_recovery` and `reidentification` on `Object Tracker`
only when the shot actually contains disappearance, distractors, or large
appearance change. The optional ML provider remains CPU-safe when no model or
GPU runtime is installed.

For final tracking, run offline from a clear middle frame in both directions.
Keep source decoding shared and let each tracker read the editor's frame/cache
path rather than making separate media copies.

## Diagnostics and Failure Analysis

Inspect these outputs at the first bad frame:

- planar `inliers` and `reprojection_error`: geometric support and fit quality;
- planar `visible`, `predicted`, and `state`: visibility versus direct evidence;
- object `confidence`, `valid`, `predicted`, and `state`: identity/motion state;
- camera `inliers`, `translation_x`, and `translation_y`: dominant-motion support;
- `Track Distance.distance` and `angle`: whether a perceived jump is object motion or a floor-track failure.

If a floor insert slides but wall insert remains stable, debug the floor branch,
not the final Merge. If both move together, inspect the source branch or camera
motion. If only the object branch fails, increase trusted target texture or use
`ACCURATE` mode with re-identification rather than changing planar settings.

## Final Graph Breakdown

![Final pipeline](images/04-final-graph.png)

The final `Merge.frame` is connected to `Viewer.frame`. The graph keeps source,
tracking, geometry, motion diagnostics, and compositing visually separated with
groups. This makes the project easy to inspect, export as `.apgraph`, validate
in CI, and explain to an AI system using `aphelion nodes export-schema`.

## Extensions

Add a second `Image Input` for a different floor graphic, route a tracker
corner into another `Corner Pin`, or feed `Track Distance.distance` into a
numeric-control node once a suitable effect-control branch is chosen. Keep
those additions downstream of the trusted tracking branches so experiments do
not contaminate observations.
