# Advanced Wall Tracking and Perspective Compositing

This walkthrough builds a wall replacement for a shot in which the camera pans
and rotates around a room, a person crosses the wall, lighting changes, and the
wall temporarily approaches an edge of frame. It uses `Wall Tracker`, the
actual four-corner outputs, `Corner Pin`, `Merge`, and `Viewer`.

![Final wall graph](images/04-final-graph.png)

## Project Structure

```text
SOURCE
  Video Input.frame -> Wall Tracker.frame
  Video Input.frame -> Merge.background

TRACK + INSERT
  Image Input.frame -> Corner Pin.frame
  Wall Tracker corner outputs -> Corner Pin.in_* corner sockets
  Corner Pin.frame -> Merge.foreground

OUTPUT
  Merge.frame -> Viewer.frame
```

The graph deliberately has two branches from the same `Video Input.frame`.
The tracker observes the original footage; the compositing branch never feeds
the already-warped result back into tracking.

## Why a Wall Tracker Rather Than Transform 2D?

`Wall Tracker` is a planar four-corner tracker. Its actual properties are the
four `*_seed_x`/`*_seed_y` pairs, `region_size`, and `search_radius`. Its actual
outputs are `confidence`, `inliers`, `reprojection_error`, `valid`, and the
eight `top_left_*`, `top_right_*`, `bottom_right_*`, and `bottom_left_*`
corner streams.

There is no `Homography` output socket on this node. The projective transform is
made explicit as the eight corner values, which is exactly what `Corner Pin`
accepts through its `in_top_left_x`, `in_top_left_y`, and corresponding corner
inputs. This is more expressive than Position + Rotation + Scale because a
wall viewed at an oblique angle becomes a trapezoid, not a rotated rectangle.

## Step 1: Choose the Wall Region

![Initial wall graph](images/01-initial-graph.png)

Choose four points on one wall plane. Prefer corners, grout lines, panel edges,
sign borders, or texture that spans the wall. Include depth across the wall so
the feature distribution is not concentrated in a single narrow strip.

Do not include a foreground person, a mirror reflection, or an adjacent wall in
the quadrilateral. The plane can later be partially outside the image; the
initial selection must still describe a coherent convex surface.

## Step 2: Configure and Track

![Wall tracking graph](images/02-tracking.png)

Set the corner seed properties on a frame where the wall is sharp and visible.
For this shot, start with `region_size` around 18-25 percent and
`search_radius` around 18-25 percent, then adjust based on normal inter-frame
motion. These are percentages of the source frame, not arbitrary pixels.

Run forward and backward passes when the clearest wall view is in the middle of
the shot. The tracker uses optical flow for normal adjacent frames, reference
feature matching for drift correction and recovery, and robust projective
validation before accepting a new corner set.

The key diagnostic outputs mean:

- `confidence`: fused visual/geometric reliability in `[0, 1]`.
- `inliers`: correspondences retained by robust estimation.
- `reprojection_error`: mean pixel error of those inliers.
- `valid`: measured observation flag. A false value does not erase predicted geometry.
- `visible`, `predicted`, `state`, `backend`: diagnostic numeric outputs persisted with the tracking result.

The current node does not expose a separate feature-density or occlusion-mask
socket. Do not invent one in a graph. Feature distribution, reference freezing,
and off-screen state handling are internal to the shared tracking engine.

## Step 3: Build the Replacement

![Perspective composite graph](images/03-effect-composite.png)

Connect `Image Input.frame` to `Corner Pin.frame`. The eight real connections
are:

```text
Wall Tracker.top_left_x     -> Corner Pin.in_top_left_x
Wall Tracker.top_left_y     -> Corner Pin.in_top_left_y
Wall Tracker.top_right_x    -> Corner Pin.in_top_right_x
Wall Tracker.top_right_y    -> Corner Pin.in_top_right_y
Wall Tracker.bottom_right_x -> Corner Pin.in_bottom_right_x
Wall Tracker.bottom_right_y -> Corner Pin.in_bottom_right_y
Wall Tracker.bottom_left_x  -> Corner Pin.in_bottom_left_x
Wall Tracker.bottom_left_y  -> Corner Pin.in_bottom_left_y
```

The `Corner Pin` output is a `FrameWithAudio`-compatible frame stream. Connect
it to `Merge.foreground`; connect the source video to `Merge.background`; then
connect `Merge.frame` to `Viewer.frame`.

## Multiple Appearance Views and Drift

A wall can look fundamentally different when it faces the camera and when it
is nearly edge-on. A single original template is a poor long-term reference.
The shared planar session maintains a bounded bank of trusted reference views.
References are only added during strong `TRACKING` frames with adequate
visibility and confidence; `WEAK`, `OCCLUDED`, `PREDICTING`, `OFFSCREEN`, and
search/recovery frames cannot contaminate that bank.

This creates a practical chain of appearance states: front-facing wall, oblique
wall, and a later recovered view. Periodic reference comparison corrects the
small drift that would accumulate if LK flow were composed forever.

## Occlusion, Blur, and Lighting

When a person walks across the wall, the surviving wall features continue to
support the homography. Features that fail forward/backward flow or robust
geometry are removed; the person is not learned as a trusted wall reference.
During full temporary occlusion, the transform becomes predicted and the
appearance model freezes. Exposure changes are handled by descriptor/reference
matching rather than replacing the reference with the occluder.

Motion blur can produce a `WEAK`, `OCCLUDED`, or predicted frame. Inspect the
update as permanent loss.

## Off-Screen Wall Behavior

The wall polygon is not clipped to the frame. When its screen-space corners
become negative or exceed the frame dimensions, that is geometry, not a bad
rectangle. The session retains the complete quadrilateral, last trusted result,
velocity, and reference bank. On re-entry it searches near the predicted
border first, then expands to larger regions and finally verifies a global
reference match geometrically before emitting `REACQUIRED`.

## Troubleshooting

### The wall jumps to another repeated panel

Check `inliers` and `reprojection_error`. Repeated wallpaper can create a
plausible but wrong match. Reseed on a larger region with asymmetric detail,
keep the quad convex, and use a clear mid-shot frame for a backward pass.

### The insert drifts while the camera rotates

The usual cause is using only a subset of corners or tracking a wall edge as a
point. Verify all eight `Corner Pin.in_*` connections. The downstream node must
receive both X and Y for all four corners.

### The wall becomes narrow at a grazing angle

Do not discard it just because its area shrinks. A supported, ordered
quadrilateral with adequate inliers is valid foreshortening. A collapsed,
self-intersecting polygon or high-error solution should remain predicted until
the reference bank can verify a better view.

## Final Graph Breakdown

`Video Input.frame` is the sole observation source. `Wall Tracker` converts
visual correspondence into four reusable corner streams. `Corner Pin` applies
those values to the artwork. `Merge` combines the warped artwork with the
untouched source. This separation makes it easy to replace the artwork without
retracking the wall.

## Extensions

The same wall track can drive a second `Corner Pin`, a mask branch, or a
diagnostic view. `Track Offset` can adjust numeric point coordinates when a
controlled offset is required, but it cannot replace projective tracking for a
rotating wall.
