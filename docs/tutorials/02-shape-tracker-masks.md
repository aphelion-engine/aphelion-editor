# 2 — Shape Tracker masks

Track one feature and carry an editable matte with it: an ellipse, a rectangle,
or a hand-drawn polygon. This is the fastest way to isolate a moving subject
when a full roto is overkill.

**You will build:** `Video Input → Shape Tracker`, with `Shape Tracker.mask`
cutting a replacement into the plate via `Merge`.

## Before you start

- `Video Input → Viewer`, file set to `samples/source.mp4`.
- Scrub to a frame where the subject is clearly visible.

## Steps

1. Add a **Shape Tracker** node (`Tab` → `Shape Tracker`).
2. Connect `Video Input.frame → Shape Tracker.frame`.
3. Select the node. The control strip shows two rows:
   - Row 1: **◄ Track**, **Track ►**, **Clear**.
   - Row 2: **Draw polygon**, **Undo vertex**, **Clear polygon**.
4. Drag the tracking point onto a textured part of the subject
   (a button, a logo, an eye — anything with contrast).
5. Set the matte shape in Properties:
   - `Shape → Shape` = **Ellipse** (64-point smooth oval),
     **Rectangle** (four corners), or **Polygon** (your points).
   - `Shape → Width` / `Shape → Height` = percent of the frame (default 20).
6. For a soft edge, raise `Shape → Feather` (0–100 preview pixels).
7. Press **Track ►**. Scrub the timeline: the matte follows the track.

## Drawing a custom polygon

1. Turn on **Draw polygon**.
2. Click around the subject in the viewport. Each click adds a vertex; the
   outline closes automatically once you have three or more.
3. **Undo vertex** removes the last point; **Clear polygon** removes them all
   (without touching the tracked motion).
4. Turn **Draw polygon** off to go back to dragging the tracking point.

Polygon vertices are stored as offsets from the tracked point, in frame
percent, so they move with the track. Both vertices and shape edits support
**Undo/Redo**.

## Using the mask

The Shape Tracker outputs `x`, `y`, `valid`, `confidence`, `predicted`, and
`mask` (grayscale, matching the preview size, `1` inside the shape).

To drop a replacement inside the shape:

1. Add an **Image Input** with your replacement and a **Merge**.
2. Connect the plate (Video Input) to `Merge.background`.
3. Connect `Image Input.frame → Merge.foreground`.
4. Connect `Shape Tracker.mask → Merge.mask`.

To keep only the subject and remove the background, invert the matte:

1. Add an **Invert Mask** node.
2. Connect `Shape Tracker.mask → Invert Mask.mask`.
3. Feed `Invert Mask.mask` into `Merge.mask` (background = new plate,
   foreground = original footage).

## Disabling during a gap

Set `Tracking Recovery → During Gaps = Disable Effect During Gap`. On a frame
with no valid measurement the Shape Tracker emits an **empty mask**, so a
downstream `Merge` shows the background only. Other policies (Hold,
Interpolate, Extrapolate) keep emitting a coordinate so the matte keeps moving.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Matte is locked to one spot | The track failed. Re-check the seed is on texture, then re-track |
| Matte dissolves to nothing on some frames | `During Gaps` is **Disable** and those frames are gaps — expected. Choose **Hold** to keep the last position |
| Mask is the wrong size | `Width`/`Height` are percents of the **frame**, not pixels. A value of 20 is 20% wide |
| Feather looks blocky | Feather is in preview pixels; raise it, or raise the Viewer's **Proxy Width** for a sharper preview |
| Point placed near the frame edge | Supported — the pattern box is clamped to the frame; the point stays on the feature |

## Related

- [Point tracking](01-point-tracking.md) — the same engine without a matte.
- [Roto and masks](07-roto-and-masks.md) — per-vertex animation when a single shape is not enough.
- [Shape Tracker reference](../shape-tracker.md).
