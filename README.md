# Aphelion Editor

Aphelion Editor is a desktop, node-based video compositor for building,
previewing, and exporting procedural video projects. It combines a node graph,
timeline, media pool, viewport, property inspector, audio playback, tracking
tools, and an extensible plugin system in one application.

**Current version:** `0.1.2`
**Runtime:** Python `3.11+`
**Status:** Active development

## Highlights

- Node-based video compositing with generators, filters, transforms, color,
  keying, roto, tracking, timing, distortion, stylization, logic, and math
  nodes.
- Real-time preview with decode-time scaling, frame caching, adaptive quality,
  frame dropping, background prefetch, and editing proxies.
- Timeline editing with playback, scrubbing, in/out points, clip timing, and
  keyframed properties.
- Video, image, and audio inputs with Viewer output and audio-aware graph
  evaluation.
- Point tracking, planar tracking, corner pinning, roto tools, chroma keying,
  depth workflows, and VFX utilities.
- MP4 and PNG-sequence export from the active Viewer.
- `.aph` project files with recent-project launch and autosave support.
- Plugin support through the sibling [`aphelion-sdk`](https://github.com/aphelion-engine/aphelion-sdk)
  package.

## Requirements

- Python `3.11` or newer
- A C compiler and Python development headers for the required native backend
- Windows, macOS, or Linux
- FFmpeg supplied through `imageio-ffmpeg` for media I/O

Runtime dependencies include PyQt6, NumPy, OpenCV, imageio, imageio-ffmpeg,
sounddevice, and cryptography. The editable development install also resolves
the sibling `aphelion-sdk` and `aphelion-styling` packages.

## Installation

Source builds require the editor, [SDK](https://github.com/aphelion-engine/aphelion-sdk),
and [styling](https://github.com/aphelion-engine/aphelion-styling) repositories as
siblings. From your workspace directory:

```bash
git clone https://github.com/aphelion-engine/aphelion-sdk.git
git clone https://github.com/aphelion-engine/aphelion-styling.git
git clone https://github.com/aphelion-engine/aphelion-editor.git
cd aphelion-editor
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS or Linux
source .venv/bin/activate
```

Install the editor with development and packaging tools:

```bash
python -m pip install --upgrade pip
python -m pip install -e ../aphelion-sdk -e ../aphelion-styling -e ".[dev,freeze]"
```

For a source environment without development or packaging tools, use:

```bash
python -m pip install -e ../aphelion-sdk -e ../aphelion-styling -e .
```

The editable install is recommended because it also installs the sibling SDK
and styling packages required by the source tree.

## Launching

```bash
python main.py
```

The source launcher builds or verifies the native backend before starting the
application. The launch screen can create a project, open an `.aph` project,
or restore a recent project.

The default new project is 1920x1080 at 30 FPS with a 10-second timeline.

If the package is installed, the console entry point is also available:

```bash
aphelion
aphelion --version
```

## High-Resolution Media

Large HEVC, 10-bit, HDR, and high-frame-rate sources may not decode in real
time directly from the original file. Aphelion prepares editing proxies and
keyframe indexes in the background when media is added. Playback uses the
proxy when it is ready; exports continue to use the original source.

For difficult media, open **Preferences > Performance** and use the low-lag
settings. Lower preview and proxy resolutions reduce decode and graph cost
without changing export resolution. The performance overlay reports displayed
FPS, preview dimensions, cache usage, and render timing.

You can benchmark a source without opening the UI:

```bash
python main.py --benchmark-playback path/to/video.mov
python main.py --benchmark-playback path/to/video.mov --benchmark-frames 120
```

## Command-Line Operations

```bash
# Launch the editor
python main.py

# Build a standalone frozen application
python main.py --build

# Build a Windows MSI installer
python main.py --build-installer

# Choose an output directory for a build
python main.py --build-dir path/to/output --build

# Print the installed version
aphelion --version
```

Packaging details are documented in [docs/packaging.md](docs/packaging.md).

## Development

Run the test suite from `aphelion-editor/`:

```bash
python -m pip install -e ".[dev]"
pytest
```

Run type checking when the development toolchain is installed:

```bash
mypy
```

Useful development diagnostics:

- Application logs: `logs/aphelion.log`
- In-app log dock: `Ctrl+Shift+L`
- Playback benchmark: `python main.py --benchmark-playback <media>`
- Native backend check: `python native/build.py --check`

The project keeps UI code in `src/ui/` and Qt-free application logic in
`src/core/`. Media decoding and rendering live primarily in `src/render/`.
Public plugins should use `aphelion_sdk` rather than importing internal editor
modules.

## Native Backend

The native backend is required for normal source-tree launches and is built
from `native/`:

```bash
python native/build.py --check
python native/build.py
python native/build.py --clean
```

See [native/README.md](native/README.md) for compiler requirements and the
native correctness contract.

## Documentation

| Guide | Description |
|---|---|
| [Getting started](docs/getting-started.md) | Installation and first launch |
| [User guide](docs/user-guide.md) | Workspace, graph, timeline, and export |
| [Playback performance](docs/playback-performance.md) | Proxies, adaptive preview, and diagnostics |
| [VFX tools](docs/vfx-tools.md) | Tracking, roto, and compositing workflows |
| [Plugins](docs/plugins.md) | Plugin locations, loading, and reloads |
| [Architecture](docs/architecture.md) | Packages, boot process, and frame pipeline |
| [Development](docs/development.md) | Tests, typing, and logging |
| [Packaging](docs/packaging.md) | Standalone builds and Windows MSI packaging |
| [Plugin SDK](https://github.com/aphelion-engine/aphelion-sdk) | Public plugin development |

## Contributing and Community

See [CONTRIBUTING.md](CONTRIBUTING.md) for source setup, SDK and styling
dependencies, validation, and the pull request process. Participants follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Use the
[issue forms](https://github.com/aphelion-engine/aphelion-editor/issues/new/choose)
to report bugs or propose features; pull requests include a review template.

## Repository Layout

```text
aphelion-editor/
  src/       Application packages: core, render, UI, plugins, and utilities
  native/    Required C acceleration backend
  plugins/   Bundled plugin modules
  tests/     Automated tests
  docs/      User, developer, and packaging documentation
  main.py    Source-tree launcher
```

## License

Aphelion Editor is licensed under the [MIT License](LICENSE). Dependencies,
including the separately maintained SDK and styling packages, retain their own
licenses; this license applies to the editor repository.
