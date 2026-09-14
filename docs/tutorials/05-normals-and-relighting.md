# 5 — Normals and relighting

A **normal pass** stores surface direction as colour (red = X, green = Y,
blue = Z). Aphelion can generate one from a depth pass, generate one
procedurally, and use it to relight or restyle a plate.

**You will build:** a depth pass → `Normal From Depth` → a relight via
`Depth Relight`, plus a stylised normal-pass look.

## Part A — Generate a normal pass

There is no generic node that consumes a `normal` socket; a normal pass is a
**frame**, so it flows through the normal video chain.

1. Build a depth pass (see [Depth maps and effects](04-depth-maps-and-effects.md)):
   `Depth Gradient` or `Depth Shape` + `Depth Noise`.
2. Add a **Normal From Depth** node.
3. Connect `Depth*.depth → Normal From Depth.depth`.
4. Connect `Normal From Depth.normal → Viewer.frame` to inspect it.

You now have an RGB frame encoding surface direction. For a purely procedural
normal field with no depth pass, use **Normal Shape** instead — it has a
`Shape → Shape` primitive choice.

## Part B — Relight with the depth surface

`Depth Relight` derives its own normals from depth and re-lights the image, so
it needs the **frame** and the **depth** — not a normal pass.

1. Chain: `Video Input → Depth Relight → Viewer`.
2. Connect your depth pass into `Depth Relight.depth`.
3. Set the light:
   - `Light → Light X` = -50, `Light → Light Y` = -65 (upper-left key).
   - `Surface → Relief` = 300 — how much the depth surface slopes; high values
     exaggerate relief, low values flatten it.
   - `Light → Strength` = 100, `Light → Ambient` = 20.
4. Turn on `Depth → Invert Depth` if the light reads inverted (the effect
   assumes white = far).

Animate `Light X`/`Light Y` across the shot to sweep the key light, or drive
them with an `Oscillator` (see [Driving properties](08-driving-properties-over-time.md)).

For an edge-light look instead, use **Depth Rim Light** with `Rim → Strength`.

## Part C — Restyle the normal pass

Because the normal pass is just an image, every colour and stylise node applies:

| Chain | Result |
|---|---|
| `Normal From Depth → Color Grading` | Rebalance the pass (`Primary → Saturation` 170, `Contrast` 120) |
| `Normal From Depth → Duotone` | Two-colour normal map (`Colors → Shadows` / `Highlights`) |
| `Normal From Depth → Posterize` | Banded, screen-print normal look |
| `Normal From Depth → Bloom` | Glowing relief ridges |
| `Normal From Depth → Displace.displace` | Use normals to warp the plate itself |
| `Normal From Depth → Bump Map.height_map` | Fake surface bumps from the normal pass |

To composite a normal-pass look over the plate, `Merge` it as the `foreground`
with a low `Opacity`, or use a `Dissolve`.

## Part D — Bump and relief from a height map

`Bump Map` takes a **height map**, not a normal pass, and shades it with a light:

1. Chain: `Video Input → Bump Map → Viewer`.
2. Connect a `Height Map` node (or a `Depth Noise`) into `Bump Map.height_map`.
3. Set `Bump → Intensity` = 10, `Light → Light X` = -50, `Light → Light Y` = -70.
4. Raise `Bump → Smooth` if the relief is too harsh.

Use `Height Map → Height → Scale` (default 32) to change the surface frequency.

## Part E — Position pass for depth compositing

**Position Map** outputs a world-position pass. Like normals it is an RGB
frame, so use it as a stylised background, a `Displace` map, or a colour-graded
element — useful for technical-looking VFX and data-visualisation styles.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Relight has no visible effect | Depth is flat (all one value). Add contrast with `Depth Noise` or a `Depth Shape` |
| Relief looks inverted | Toggle `Depth → Invert Depth`, or swap the light's Y sign |
| Normal pass is mostly flat blue | That is correct for a front-facing flat depth plane. Add depth variation for curvature |
| Bump Map is too noisy | Raise `Bump → Smooth`, or lower `Height Map → Scale` |

## Related

- [Depth maps and effects](04-depth-maps-and-effects.md)
- [Psychedelic VFX (advanced)](09-psychedelic-vfx-advanced.md) — uses depth to drive parallax in a stylised look.
