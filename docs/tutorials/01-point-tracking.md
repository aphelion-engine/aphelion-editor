# 1 — Point tracking

Track a single feature (a logo, a face mark, a corner of a sign) across frames
and drive other nodes with its position.

**You will build:** `Video Input → Tracker`, with the Tracker's X/Y outputs
driving a `Transform 2D`.

## Before you start

- Add a **Video Input** (`1`) and a **Viewer** (`2`), and connect
  `Video Input.frame → Viewer.frame`.
- Point the Video Input's **Source → File** at `samples/source.mp4`.
- Scrub to the frame where the feature is clearest.

## Steps

1. Add a **Tracker** node (press `Tab`, type `Tracker`).
2. Connect `Video Input.frame → Tracker.frame`.
3. Select the Tracker. A control strip appears above the preview with
   **◄ Track**, **Track ►**, and **Clear**.
4. In the viewport, click the feature you want to track. A single-point
   Tracker jumps to the click — this is the *seed* position.
5. Check the seed before tracking:
   - The dashed circle is the **search radius**.
   - The solid square is the **pattern box**; it should sit on textured detail,
     not on a flat area or a hard edge.
6. Press **Track ►** to track forward to the last frame, or **◄ Track** to
   track back to frame 0. A progress dialog appears; **Cancel** stops cleanly
   and keeps the frames already solved.
7. Scrub the timeline and watch the overlay label: it reads **Tracked**,
   **Lost**, **Reacquiring (prediction)**, or **Reacquired**.

## Settings that matter

| Group → Label | Default | What to do |
|---|---|---|
| Seed → Center X / Center Y | 50 / 50 | Set automatically when you click in the viewport |
| Pattern → Pattern Size | 8 | Percent of frame width. Raise for repetitive detail, lower to avoid neighbouring features |
| Pattern → Search Radius | 15 | Max motion per frame, in percent of frame width. Must exceed the feature's fastest movement |
| Tracking Recovery → Track Threshold | 0.45 | Raise to reject more weak matches |
| Tracking Recovery → Reacquire Threshold | 0.65 | Must stay above Track Threshold |
| Tracking Recovery → Max Lost Frames | 30 | How long the tracker keeps hunting after losing the feature |
| Tracking Recovery → During Gaps | Hold Last Position | What to output for missing frames (see below) |

## Using the result

The Tracker exposes five Number outputs:

| Output | Meaning |
|---|---|
| `x`, `y` | Measured position as a percentage of frame width/height (0–100) |
| `valid` | `1` on a measured frame, `0` on a missing/predicted frame |
| `confidence` | Match score of the measurement |
| `predicted` | `1` when the coordinate came from the gap policy, not a measurement |

To move something with the track:

1. Add an **Image Input** (your logo/element) and a **Transform 2D**.
2. Connect `Image Input.frame → Transform 2D.frame`.
3. Connect `Tracker.x → Transform 2D.in_translate_x` and
   `Tracker.y → Transform 2D.in_translate_y`.

`Transform 2D`'s X/Y are also 0–100 percent of frame, so the element lands on
the tracked point. Connect the result into a **Merge** over the plate.

To switch an effect off when the track is lost, add a **Property Drive**,
connect `Tracker.valid → Property Drive.value`, drag the effect's output into
`Property Drive.target`, then pick the effect's `Enabled` property in the
**Drive → Property** dropdown.

## During Gaps

Raw measurements are never altered. The gap policy only decides what a missing
frame *outputs*:

| Policy | Missing frame outputs |
|---|---|
| Hold Last Position | The last measured position |
| Interpolate Gap | A straight line between the surrounding measurements |
| Extrapolate Motion | The tracker's constant-velocity prediction |
| Disable Effect During Gap | No coordinate at all (`x`/`y` are empty) |

**Clear** removes all tracked keyframes; the seed position is kept.

## Troubleshooting

| Message / symptom | Cause and fix |
|---|---|
| "the seed pattern has too little detail or lies outside the frame" | The pattern box is on a flat/dark area. Move the point onto visible texture, or lower **Pattern Size** |
| "the source frames could not be read" | The `frame` input is not connected, or the Video Input's file is missing |
| Tracking drifts to a similar-looking feature | Raise **Pattern Size**, raise **Track Threshold**, or raise **Ambiguity Margin** |
| Loses the feature on fast motion | Raise **Search Radius** and **Max Jump** |
| Never reacquires | Raise **Max Lost Frames**, or lower **Reacquire Threshold** slightly |
| Points placed near the picture edge | Supported: the pattern box is clamped to the frame and the point stays anchored to the feature you picked |

## Related

- [Shape Tracker masks](02-shape-tracker-masks.md) — same engine plus a matte output.
- [Planar tracking and match-move](03-planar-tracking-match-move.md) — four corners, perspective.
- [Tracking recovery reference](../tracking-recovery.md) — full algorithm notes.
