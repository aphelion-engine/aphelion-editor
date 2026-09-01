# Aphelion Editor

**A node-based video compositor.** Build a graph, preview in real time, export from any Viewer.

![Sample](https://github.com/aphelion-engine/aphelion-editor/blob/main/resources/aphelion-editor-app-sample.png)

Aphelion is a desktop suite: node graph, viewport, timeline, media pool, and property inspector. The pipeline is float32 RGB. Export and tracking run off the UI thread. Third-party nodes use the sibling [Plugin SDK](../aphelion-sdk/README.md).

Version **0.1.0**. Python **3.11+**.

## Features

- **80+ built-in nodes** — input/output, generators, color, filters, compositing, transform, keying, roto, tracking, timing, distort, stylize, math
- **Real-time preview** — decode-time proxy (default 960px), optional 640px playback proxy, frame cache and prefetch
- **Compositing** — chroma key, matte edge, spill suppress, bezier roto, point and planar tracking, corner pin, merge/dissolve
- **Color** — grading, exposure, hue/saturation, white balance, levels, vibrance, shadows/highlights, creative looks
- **Timeline** — playback, in/out, keyframed properties (default 1920×1080 @ 30 fps, 10 s)
- **Projects** — `.aph` JSON with autosave once a path exists
- **Export** — MP4 or PNG sequence from the active Viewer
- **Plugins** — `aphelion_sdk` drop-ins, wheels, and **Preferences → Plugins** (enable, disable, reload)

## Quick start

```bash
cd aphelion-editor
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
pip install -e ".[dev,freeze]"
python main.py
```

The launcher creates a project, opens a `.aph`, or restores a recent file. `aphelion --version` prints the app version.

Full install notes: [docs/getting-started.md](docs/getting-started.md).

## Documentation

| Guide | Contents |
|---|---|
| [Getting started](docs/getting-started.md) | Environment, install, launch |
| [User guide](docs/user-guide.md) | Workspace, graph, playback, export, shortcuts |
| [Plugins](docs/plugins.md) | Folders, preferences, reload |
| [Architecture](docs/architecture.md) | Packages, boot, frame pipeline |
| [Packaging](docs/packaging.md) | Wheels, freeze, Windows MSI |
| [Development](docs/development.md) | Tests, typing, logging |
| [Plugin SDK](../aphelion-sdk/README.md) | Writing and shipping plugins |

## CLI

```bash
python main.py
python main.py --build
python main.py --build-installer          # Windows MSI → dist/AphelionEditorSetup-0.1.0-win64.msi
python main.py --build-dir path/to/output
aphelion --version
```

`--build-installer` includes a freeze. Details: [docs/packaging.md](docs/packaging.md).

## Layout

```
aphelion-editor/
  src/           Application packages (ui, core, render, …)
  plugins/       Bundled drop-in plugin modules
  tests/         pytest
  main.py        Source-tree launcher
aphelion-sdk/    Public plugin SDK (sibling package)
```

UI stays in `ui/`. Core logic is Qt-free. Frames are `float32` RGB in `[0, 1]`.

## License

Proprietary. Same for the plugin SDK; see `../aphelion-sdk/pyproject.toml`.
