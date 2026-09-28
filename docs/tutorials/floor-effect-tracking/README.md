# Track an Effect to a Floor with Perspective-Aware Tracking

This is an advanced match-move walkthrough. The finished graph takes a source
video, tracks a floor as a projective surface, maps an image into that surface,
around the four tracked corners rather than a translated center point.

![Final floor graph](images/04-final-graph.png)

## What We Are Building

The graph is:

```text
Video Input.frame -> Floor Tracker.frame
Video Input.frame -> Merge.background
Image Input.frame -> Corner Pin.frame
Floor Tracker four corner outputs -> Corner Pin corner modulation inputs
Corner Pin.frame -> Merge.foreground
Merge.frame -> Viewer.frame
```

`Floor Tracker` is a `PlanarTrackerNode` specialization. Its projective result
is exposed as eight numeric corner streams, not as a single rectangular box.
`Corner Pin` consumes those values through its `in_*` modulation sockets. The
original video remains the Merge background, so the inserted graphic is the
only branch being warped.

## Required Nodes

- `Video Input`
- `Floor Tracker`
- `Image Input`
- `Corner Pin`
- `Merge`
- `Viewer`

The exact graph is in `graph.apgraph`; `$USER_VIDEO` and `$FLOOR_GRAPHIC` are
safe placeholders, not machine-specific paths. Replace them in the editor.

## Step 1: Establish the Source Branch

![Initial graph](images/01-initial-graph.png)

Create `Video Input` and connect its `frame` output to `Floor Tracker.frame`.
The `frame` output is a `FrameWithAudio` stream. The tracker samples it in a
background worker; the later compositing branch can continue to use the same
source independently.

Use a real shot with camera movement. A useful floor region contains tile
intersections, floorboards, seams, cracks, texture, or stable shadow detail.
Avoid choosing only a featureless patch or a region dominated by a person.
The selected quadrilateral should cover a meaningful area of the same physical
plane, with points distributed across near and far portions of the floor.

## Step 2: Configure Floor Tracker

![Tracking graph](images/02-tracking.png)

`Floor Tracker` currently exposes these real properties:

| Property | Why it matters here |
| --- | --- |
| `top_left_seed_x`, `top_left_seed_y` | Initial upper-left floor corner in percent coordinates. |
| `top_right_seed_x`, `top_right_seed_y` | Initial upper-right floor corner. |
| `bottom_right_seed_x`, `bottom_right_seed_y` | Initial lower-right floor corner. |
| `bottom_left_seed_x`, `bottom_left_seed_y` | Initial lower-left floor corner. |
| `region_size` | Approximate feature region size as a percentage. A larger floor sample gives the correspondence engine more texture to work with. |
| `search_radius` | Normal local search distance as a percentage. It is not a substitute for recovery; keep it appropriate to normal motion. |

Drag the four corners in the viewport so they describe the floor in
perspective. Do not force the selection to remain a screen-space rectangle.
Run tracking forward from a frame with a clear floor view. For a middle-frame
seed, run backward first and then forward from the same clear reference.

The engine uses short-term optical flow, distributed feature points, robust
homography estimation, trusted reference views, and motion prediction. The
node's actual numeric outputs are:

- `confidence`: normalized `Float` evidence from 0.0 to 1.0.
- `inliers`: number of feature correspondences supporting the accepted update.
- `reprojection_error`: mean inlier error in source-frame pixels.
- `valid`: whether the result is a direct measured observation.
- `top_left_x`, `top_left_y`, `top_right_x`, `top_right_y`, `bottom_right_x`, `bottom_right_y`, `bottom_left_x`, `bottom_left_y`: normalized corner coordinates. They are not clamped when the floor leaves the image.
- `visible`, `predicted`, `state`, `backend`: numeric diagnostic outputs for graph inspection and downstream logic.

This implementation does not expose a `Homography` socket on `Floor Tracker`;
the homography is represented by the eight corner streams and consumed by
`Corner Pin`.

## Step 3: Attach the Graphic

![Effect composite graph](images/03-effect-composite.png)

Connect `Image Input.frame` to `Corner Pin.frame`. Connect the eight Floor
Tracker corner outputs as follows:

```text
Floor Tracker.top_left_x     -> Corner Pin.in_top_left_x
Floor Tracker.top_left_y     -> Corner Pin.in_top_left_y
Floor Tracker.top_right_x    -> Corner Pin.in_top_right_x
Floor Tracker.top_right_y    -> Corner Pin.in_top_right_y
Floor Tracker.bottom_right_x -> Corner Pin.in_bottom_right_x
Floor Tracker.bottom_right_y -> Corner Pin.in_bottom_right_y
Floor Tracker.bottom_left_x  -> Corner Pin.in_bottom_left_x
Floor Tracker.bottom_left_y  -> Corner Pin.in_bottom_left_y
```

These are `Float` to `Float` modulation connections. The `Corner Pin` node's
own `top_left_x` etc. properties remain defaults; each `in_*` socket overrides
the corresponding property for the current frame. Connect `Corner Pin.frame`

The inserted image now follows floor translation, rotation, scale, shear, and
perspective foreshortening. Do not replace this with only `Transform 2D` if the
floor changes viewing angle; translation/rotation/scale cannot represent the
full projective deformation.

## Occlusion and Off-Screen Behavior

A person crossing the floor is an occlusion, not a reason to learn the person
as floor texture. The tracker keeps trusted references frozen when evidence is
weak or the selected surface is mostly hidden. It continues using surviving
inliers where enough of the plane remains visible and otherwise advances the
predicted quadrilateral.

The lifecycle is visible in the diagnostics:

```text
TRACKING -> PARTIALLY_OFFSCREEN -> MOSTLY_OFFSCREEN -> OFFSCREEN
          -> SEARCHING_FOR_REENTRY -> REACQUIRED -> TRACKING
```

Predicted corners can be less than 0.0 or greater than 1.0. That is expected:
the graph retains the full floor geometry while the renderer clips only when
drawing. A later descriptor/reference match must pass projective validation
before it becomes a measured update.

## Debugging a Sliding Insert

If the graphic gradually slides across the floor, inspect the tracker before
changing the composite:

1. Check `confidence`, `inliers`, and `reprojection_error` at the sliding frame.
2. If `inliers` collapse, return to a clearer seed frame and enlarge the selected `region_size` over textured floor.
3. Check that the four corners still describe one convex plane and are not concentrated in a single texture patch.
4. Distinguish `predicted` output from `valid`. A predicted result is not new visual evidence and should not be used as a trusted reference.
5. If the camera changes viewpoint sharply, use `Track Backward` from a clear later frame as well as `Track Forward` from the original seed.
6. Use the overlay's current polygon and diagnostics to identify whether the error starts at an occluder, blur event, or weak texture region.

Do not solve a bad plane selection by making `search_radius` enormous. That
increases ambiguous matches; it does not add geometric evidence.

## Performance

Use a proxy or reduced tracking preview for long 4K shots, then refine the
final composite at the required output resolution. Normal tracking is cheap
relative to global recovery. The background worker keeps the UI responsive and
supports cancellation. Use a larger `region_size` for a large floor rather
than running several redundant trackers over overlapping patches.

## Extensions

The same corner streams can drive a mask, a second `Corner Pin`, or a
diagnostic branch. `Track Distance` can consume numeric tracker outputs when a
relative measurement is useful. For a wall or screen, use the same architecture
with `Wall Tracker` or `Planar Surface Tracker`; the downstream corner dataflow
is identical.
