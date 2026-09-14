# Architecture

Application code lives under `src/`. `main.py` puts that tree on `sys.path` in development. Frozen builds ship packages beside the interpreter.

## Packages

| Package | Responsibility |
|---|---|
| `ui/` | PyQt windows, docks, dialogs, node-graph view, timeline chrome, QSS |
| `core/` | Project document, node graph model, serialization, preferences, roto, tracking |
| `timeline/` | Timeline state and playback control |
| `render/` | Decode, probe, frame evaluation, preview, export and tracking workers |
| `effects/` | Frame-level implementations used by built-in nodes |
| `app_io/` | `.aph` I/O, plugin and node loaders, theme files |
| `config/` | Constants, default keybinds, theme tokens |
| `utils/` | Logging, paths, process environment |
| `../aphelion-sdk/aphelion_sdk/` | Public plugin SDK |
| `plugins/` | Drop-in `*.py` modules loaded at boot |

UI never owns core logic. Rendering and export run off the UI thread.

## Boot

`EditorBootDriver` (Qt-free) runs staged init: runtime, built-in node registry, plugins (using persisted `PluginSettings`), project document, graph validation, media probe. The bootloader UI reports each stage.

## Frame pipeline

Preview and export evaluate the graph into **float32 RGB** frames, shape `(height, width, 3)`, values nominally in `[0, 1]`. Alpha is not carried on this buffer. Mixing, color, and most effects stay in that space.

Built-in unary effects subclass `FrameEffectNode`. Plugin video effects subclass `aphelion_sdk.VideoEffectPlugin`, which is the same host node type behind a public API.

### Frame representations

The pipeline moves frames between **two** representations rather than one:

* `SOURCE_DTYPE` (`uint8`) — what the decoder, the importer, and the cache
  produce. Four times denser, so a byte-budgeted cache holds four times as
  many frames.
* `FRAME_DTYPE` (`float32`, `[0, 1]`) — the canonical *processing* contract.

Promotion between them is **lazy and demand-driven**. `ensure_rgb_f32`
normalizes any input representation, so a node that needs float precision
promotes once, at the point of use, instead of the source promoting eagerly
and the display boundary immediately quantizing back.

Whether a source is *allowed* to hand over its raw 8-bit frame is decided by
the compiled render plan (`core/render_plan.py`), which grants permission
only when every node between that source and the Viewer has declared
`Node.accepts_u8_frame`. The declaration defaults to `False`, so an
unverified node keeps the always-float behaviour and opting in is a
deliberate act.

### Compiled execution plan

Graph structure — evaluation order, raw-8-bit eligibility, dependency depth,
independent branches, longest-path cost — is compiled once into an immutable
`RenderPlan` and reused until `Project.topology_revision` changes. Changing a
property deliberately does *not* invalidate it.

### Deadlines and adaptive quality

`core/playback/` holds the Qt-free playback engine: `MediaClock` (audio-master
capable), `DeadlineQueue` (bounded, earliest-deadline-first, supersedes stale
work), `QualityGovernor` (hysteretic preview scaling driven by measured
deadline misses), `CostEstimator`, and `FrameTrace` (per-frame stage timings
with stall attribution).

### Media layer

`core/media/proxy.py` generates and caches all-intra editing proxies
(`-g 1`, so any frame is one decode step away), keyed by source identity and
recipe version, with frame counts verified before a proxy is trusted.
`core/media/index.py` caches keyframe positions so seeking goes straight to
the right GOP instead of probing. Both are produced on the background
scheduler and never block opening a project.

### Native kernels

`native/aphelion_native.c` provides the operations where native code beats
calling into NumPy/OpenCV — in-place BGR→RGB swap, fused convert+downscale,
and a buffer pool. Everything compute-bound stays with the libraries that
already vectorise it.

`core/native.py` is the only module that knows whether the extension exists,
and every operation has a pure-Python reference implementation that the test
suite compares against. **The extension is optional**: the editor runs
unchanged without it, and `probe().backend` reports which path is live. See
`native/README.md`.

## Registry

`NodeLoader` registers `BUILTIN_NODE_TYPES` from `core.nodes.catalog` (77 types). `PluginLoader` then registers enabled SDK plugins into the same `global_node_registry`, so plugin nodes appear in the same menus and search palette as built-ins. `CustomNodeStore` then registers saved custom node definitions under the `Custom` category.

## Custom nodes

`core.nodes.custom_nodes` defines reusable subgraph chips. A `CustomNode`
carries a serializable `CustomNodeDefinition` (ports, parameters, inner nodes,
and wires) and evaluates the inner graph in a private nested `Project` held by
`CustomNode._ensure_subgraph`.

- Terminals are two unregistered node types: `Subgraph Input` (one output,
  fed from the parent graph) and `Subgraph Output` (one input, returns its
  value). Ports are the terminals; `CustomPort` maps an outer socket name to a
  terminal id.
- `CustomProperty` exposes an inner node property as an adjustable parameter
  on the chip. `CustomNode.evaluate` pushes each parameter value onto its
  target inner property before evaluating, so parameters drive the graph and
  support animation curves.
- The nested project mirrors the parent's resolution, fps, frame range, and
  preview width via `Project.set_preview_width_override`.
- Instances embed their definition in `to_dict`, so `Project.from_dict` can
  reconstruct a chip even when the type is not registered locally.
- Definitions persist in `userdata/custom_nodes.json`; `CustomNodeStore`
  registers them at boot and pushes edits onto live instances.

## Persistence

- Projects: `.aph` JSON via `app_io.aph_format`
- Preferences: `userdata/preferences.json`
- Recent projects: `userdata/recent_projects.json`
- Custom nodes: `userdata/custom_nodes.json`
- Logs: `logs/aphelion.log` (rotating, 2 MB × 5)

## Related

- [User guide](user-guide.md)
- [Development](development.md)
- [SDK authoring](../../aphelion-sdk/docs/authoring.md)
