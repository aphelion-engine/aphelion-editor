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
