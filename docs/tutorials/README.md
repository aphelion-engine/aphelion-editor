# Tutorials

Hands-on, task-oriented walkthroughs for Aphelion Editor. Each tutorial is
self-contained: it lists what you need, the exact nodes to add, the controls to
set, and how to check that it worked.

If you have never opened the editor, read [Getting started](../getting-started.md)
and the [User guide](../user-guide.md) first — this folder assumes you can add a
node, wire a socket, and scrub the timeline.

## Contents

| # | Tutorial | You will learn |
|---|---|---|
| 1 | [Point tracking](01-point-tracking.md) | Track one feature and drive a transform with it |
| 2 | [Shape Tracker masks](02-shape-tracker-masks.md) | Track a point and animate an ellipse/rectangle/polygon matte |
| 3 | [Planar tracking and match-move](03-planar-tracking-match-move.md) | Track four corners and corner-pin an insert onto a surface |
| 4 | [Depth maps and effects](04-depth-maps-and-effects.md) | Build depth passes and drive parallax, fog, defocus, and more |
| 5 | [Normals and relighting](05-normals-and-relighting.md) | Generate a normal pass, restyle it, and relight a plate |
| 6 | [Keying and compositing](06-keying-and-compositing.md) | Pull a chroma key, refine the matte, and composite |
| 7 | [Roto and masks](07-roto-and-masks.md) | Draw shape masks and combine them with other mattes |
| 8 | [Driving properties over time](08-driving-properties-over-time.md) | Animate any property with Oscillator/Random/Property Drive |
| 9 | **[Psychedelic VFX (advanced)](09-psychedelic-vfx-advanced.md)** | Build a full stylised music-video look on `samples/source.mp4` |

## Sample media

The repository ships one clip used by the tutorials:

```
aphelion-editor/samples/source.mp4
```

Point a **Video Input** node's **File** at it, or drag the file onto the node
graph. Tutorial 9 is written entirely around this clip.

## Conventions used here

- **Node names** are the labels in the Add Node menu / `Tab` search palette
  (for example `Video Input`, `Shape Tracker`, `Depth Parallax`).
- **Properties** are written as `Group → Label`, matching the Properties panel,
  followed by the value to set (for example `Pattern → Pattern Size = 8`).
- **Sockets** are written as `Node.output → Node.input`.
- Every video chain must end at a **Viewer** node; the Viewer is what the
  viewport previews and what Export renders.
