# 4 — Depth maps and effects

Aphelion has a family of **Depth Generator** nodes that synthesise depth passes,
and a family of **Depth** effects that consume one through a `depth` input. This
tutorial builds a depth pass, drives it with animation, and uses it for
parallax, fog, defocus, and slices.

> **Where depth comes from.** Aphelion does not estimate depth from ordinary
> video. A depth map is a grayscale frame you supply or generate:
> procedurally (below), from a rendered depth pass via **Image Input**, or from
> a matte painted with **Roto**/**Shape Tracker**. Everything in this tutorial
> works with any of those sources.

## Part A — Build a depth pass

A depth effect wants a frame where **white = far** (or near, per the effect's
`Invert Depth` toggle) and black = close.

### Option 1: a gradient backdrop

1. Add a **Depth Gradient**. Its outputs are a depth frame:
   - `Gradient → Near` = 0, `Mid` = 0.5, `Far` = 1.
2. Add a **Depth Noise** (`Noise → Scale` = 32, `Noise → Seed` = 0) and a
   **Merge** to add surface variation, or feed the noise into a **Displace**
   for lateral detail.
3. Preview it by connecting `Depth Gradient.depth → Viewer.frame`.

### Option 2: a shaped object

1. Add a **Depth Shape** and set `Shape → Shape` to the primitive you want.
2. Follow it with **Depth Noise** for organic break-up.

### Option 3: volume / position passes

| Node | Output | Use |
|---|---|---|
| `Camera Depth` | `depth` | Perspective-consistent depth from `Camera → FOV` |
| `Volume Noise` | `volume` | 3D noise field |
| `Volume Slice` | `slice` | A 2D slice through that volume (`Slice → Axis`) |
| `Height Map` | `height` | Fractal height field for bump/relief |
| `Displacement Map` | `displace` | Vector map for `Displace` |
| `Position Map` | `position` | World-position pass |
| `UV Grid` / `UV Sphere` | `uv` | Reference/UV passes |

## Part B — Drive a flat plate with parallax

`Depth Parallax` offsets pixels by depth, which reads as a 2.5D move.

1. Chain: `Video Input → Depth Parallax → Viewer`.
2. Add **Depth Gradient** and connect `Depth Gradient.depth → Depth Parallax.depth`.
3. Animate the move:
   - `Parallax → Shift X` = 0 → 40 over the shot.
   - `Parallax → Shift Y` = 0 → -15.
4. Keyframe `Shift X`/`Shift Y` at the start and end frames (see
   [Keyframes](../user-guide.md)).

Near pixels move more than far pixels, so the frame gains depth without a 3D render.

## Part C — Depth-driven effect stack

Add these after the plate, each with the same depth pass wired into its `depth`
input. Effects are independent — use the ones the shot needs.

| Node | Key controls | Look |
|---|---|---|
| **Depth Tilt Shift** | `Blur → Near Blur` (0), `Blur → Far Blur` (32) | Miniature/toy-scale defocus |
| **Depth Haze** | `Atmosphere → Near` (40), `Far` (100), `Color`, `Density` (60) | Atmospheric depth fade |
| **Depth Of Field** | defocus by depth | Lens defocus on near/far planes |
| **Depth Relight** | `Light → Light X/Y`, `Surface → Relief`, `Strength`, `Ambient` | Re-light from the depth surface (see tutorial 5) |
| **Depth Rim Light** | `Rim → Strength` | Edge light on depth discontinuities |
| **Z Fog Advanced** / **Z Glow Advanced** | fog/glow falloff by depth | Distance fog or depth-gated glow |
| **Depth Displace** | `Displace → Strength` (20) | Push pixels along depth |
| **Anaglyph 3D** | `Stereo → Separation`, `Glasses` | Red/cyan stereo from depth |
| **Depth Edge** | outputs a `mask` | Outline of depth discontinuities |
| **Depth Slice** | `Slice → Near/Far/Softness` | Isolate a depth band as a matte |

### Using Depth Slice as a matte

`Depth Slice` outputs a **mask**, not a frame:

1. `Video Input → Depth Slice.depth` (wire your depth pass in).
2. Add a **Merge**; `background` = your far background, `foreground` = the plate.
3. Connect `Depth Slice.mask → Merge.mask`.

Now only the depth band you selected shows the plate; the rest is the
background. Scrub or keyframe `Slice → Near`/`Far` to rack focus between planes.

## Part D — Composite the depth layers

A common pattern is to split the shot into two depth bands with two
**Depth Slice** nodes (one inverted), grade each separately, then **Dissolve**
between them driven by a value.

`Dissolve → Dissolve → Mix` accepts 0–100 and can itself be keyframed, giving a
depth-racked transition.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Effect looks inverted (background blurred instead of subject) | Turn on the effect's `Depth → Invert Depth` |
| Parallax tears at the edges | The shift moved pixels past the frame. Reduce `Shift X/Y`, or set a `Border Mode` on a following `Transform 2D` |
| Depth Slice produces an empty mask | `Near`/`Far` are on the wrong side of the depth range — swap them or invert |
| Depth noise looks static | `Depth Noise` is a still field. Animate a following `Offset` or drive `Seed` with the frame number |

## Related

- [Normals and relighting](05-normals-and-relighting.md) — turn a depth pass into a normal pass.
- [Driving properties over time](08-driving-properties-over-time.md) — animate depth controls procedurally.
