# 8 — Driving properties over time

Keyframes are not the only way to animate. **Property Drive** lets a Number
connection override any numeric property of any node, which is how you build
procedural, non-repetitive motion cheaply.

**You will build:** an `Oscillator` driving a `Transform 2D`'s rotation with no
keyframes at all.

## The two property nodes

| Node | Direction | Use |
|---|---|---|
| **Property Drive** | value → another node's property | Animate/override a property from a Number |
| **Property Link** | another node's property → value | Read a property as a Number for math or routing |

Both take a **node reference**: drag the target node's output socket into the
`target` (Drive) or `source` (Link) input, then choose the property from the
`Drive → Property` / `Source → Property` dropdown. The dropdown lists that
node's numeric properties, grouped by their Properties-panel group.

## Steps: procedural rotation

1. Add a **Transform 2D** after your footage
   (`Video Input → Transform 2D → Viewer`).
2. Add an **Oscillator**:
   - `Wave → Waveform` = Sine
   - `Wave → Frequency` = 0.25 (cycles per second)
   - `Wave → Amplitude` = 30
   - `Wave → Offset` = 0
3. Add a **Property Drive**.
4. Drag `Transform 2D.frame` into `Property Drive.target`.
5. In `Property Drive` properties, set
   **Drive → Property** = `Transform · Rotation`.
6. Connect `Oscillator.value → Property Drive.value`.
7. Scrub or play. The Transform 2D rotation now oscillates ±30°, driven entirely
   by the oscillator.

> The Drive's `Drive → Enabled` toggle temporarily suspends the override, and
> `Source → Fallback` is the value used while nothing is connected to `value`.

## Useful drivers

| Driver | Waveform / settings | Effect |
|---|---|---|
| **Oscillator** | Sine, 0.1–0.5 Hz | Smooth breathing/pulsing motion |
| **Oscillator** | Triangle | Linear ramps up and down |
| **Oscillator** | Square, `Wave → Duty` | Hard on/off switching |
| **Random** | `Random → Per Frame` off | One random value, held |
| **Random** | `Random → Per Frame` on, `Interval` = 2 | A new value every 2 frames — stutter/glitch |
| **Timeline Normalized** | — | 0 → 1 across the whole timeline, for a one-way ramp |
| **Timeline Frame** | — | Current frame number |
| **Timeline Time** | — | Current time in seconds |
| **Timeline FPS** | — | Project frame rate |
| **Timeline Max Frame** | — | Last frame of the timeline |

`Timeline Normalized` is the keyframe-free way to ramp a parameter across the
whole shot: drive `Mix`, `Opacity`, a blur radius, anything.

## Combining and scaling

Insert a **Math** or **Math Function** node between the driver and the Drive:

```
Oscillator.value → Math(a) → Property Drive.value
```

`Math → Operation` can add, multiply, remap, and so on; `Math → A`/`B` provide
constants for the operand. Use **Clamp** to keep a driven property inside a safe
range, and **Remap** to map one range onto another.

`Logic → Compare`, `Logic Gate`, `Select`, `Range Check`, and `Smooth Step`
let a numeric driver make decisions — for example, "only glitch when the random
value is above 0.7".

## Reading properties

**Property Link** is the reverse: point it at a node property and it emits that
value as a Number. This is how you feed one node's parameter into another's
math without keyframing both.

## Tips

- Driven properties are still keyframable; the drive simply overrides the
  value while `Enabled` is on.
- Drivers are evaluated per frame, so a timeline scrub updates them live.
- Use `Processing → Mix` on an effect as a drive target for smooth effect
  fade-ins without touching keyframes.

## Related

- [Psychedelic VFX (advanced)](09-psychedelic-vfx-advanced.md) — a full example using four drivers.
