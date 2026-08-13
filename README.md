# Aphelion

**A modern, node-based video editor.** Compose effects in a graph, preview in real time, and export finished sequences from any Viewer.

Aphelion is a desktop compositing suite: a node graph, viewport, timeline, media pool, and property inspector, with a float32 RGB pipeline, background export, and a public plugin SDK.

Version **0.1.0**. Requires **Python 3.11+**.

---

## Features

- **Node graph** — 77 built-in node types spanning input/output, generators, color, filters, compositing, transform, keying, roto, tracking, timing, distort, stylize, and math.
- **Real-time preview** — decode-time proxy scaling, frame cache, and prefetch during playback. Default preview width is 960px; playback can drop to a 640px proxy independently of paused review.
- **Compositing tools** — chroma key, matte edge, spill suppress, bezier roto, point and planar tracking, corner pin, and merge/dissolve.
- **Color and look** — color grading, exposure, hue/saturation, white balance, levels, vibrance, shadows/highlights, and a full set of creative/stylize effects.
- **Timeline and keyframes** — playback, in/out marks, and animated node properties. Default project is 1920×1080 at 30 fps, 10 seconds.
- **Projects** — `.aph` JSON documents with autosave (every 30 seconds once a path exists).
- **Export** — MP4 video or PNG image sequence from the active Viewer, on a background worker.
- **Plugins** — third-party nodes via the [Aphelion Plugin SDK](../aphelion-sdk/README.md), discovered in-process or through the `aphelion.plugins` entry-point group.

---

## Requirements

| Dependency | Role |
|---|---|
| Python 3.11+ | Runtime |
| [PyQt6](https://pypi.org/project/PyQt6/) ≥ 6.6 | UI |
| [NumPy](https://pypi.org/project/numpy/) ≥ 1.26 | Frame buffers |
| [OpenCV](https://pypi.org/project/opencv-python-headless/) ≥ 4.8 (`opencv-python-headless`) | Decode, tracking, effects |
| [imageio](https://pypi.org/project/imageio/) ≥ 2.34 + [imageio-ffmpeg](https://pypi.org/project/imageio-ffmpeg/) | Media I/O |
| [cx_Freeze](https://pypi.org/project/cx-Freeze/) ≥ 8.6 | Standalone freeze (optional) |

---

## Getting started

From the `aphelion-editor` directory:

```bash
python -m venv .venv
```

Activate the environment:

```bash
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install the editor (editable) with development extras. The editor requires
the sibling `aphelion-sdk` package and installs it automatically:

```bash
pip install -e ".[dev,freeze]"
```

Runtime-only (no editable install):

```bash
pip install -r requirements.txt
```

Launch the editor:

```bash
python main.py
```

```bash
aphelion --version
```

The launcher opens first: create a new project, browse for an existing `.aph`, or reopen a recent one.

---

## Pip packages

Two packages, two build commands. `pip install -e ".[dev]"` provides the `build` frontend.

| Package | Directory | Wheel name |
|---|---|---|
| Editor | `aphelion-editor/` | `aphelion-editor` |
| Plugin SDK | `../aphelion-sdk/` | `aphelion-plugin-sdk` |

```bash
python -m build
python -m build ../aphelion-sdk
```

Wheels land in `dist/`. Install them with `pip install dist/<wheel>.whl`.

Standalone freeze is separate from pip wheels. Intermediates go to `build/`; the executable tree defaults to `dist/`.

```bash
python main.py --build
python main.py --build --build-dir path/to/output
```

On Windows the frozen binary is `AphelionEditor.exe`. The freeze copies `resources/`, `userdata/`, `plugins/`, and `logs/` into the output tree.

---

## Plugin SDK

Custom plugins are written against `aphelion_sdk` only. Do not import `core`, `effects`, `render`, or `ui`. Video effects subclass `VideoEffectPlugin`; audio bases will follow later. The editor requires the sibling `aphelion-sdk` package.

```python
import aphelion_sdk


@aphelion_sdk.register_plugin
class GrayscaleEffect(aphelion_sdk.VideoEffectPlugin):
    plugin_name = "Grayscale"
    plugin_category = "Plugins"
    plugin_description = "Blend a frame toward grayscale."
    plugin_color = (140, 140, 140)

    def setup_effect_properties(self) -> None:
        self.set_property(
            "amount",
            aphelion_sdk.slider_property(100, 0, 100, label="Amount", suffix="%"),
        )

    def process_frame(
        self,
        frame: aphelion_sdk.Frame,
        _frame_num: int,
    ) -> aphelion_sdk.Frame:
        amount = self.float_value("amount", 100.0) / 100.0
        luma = (
            frame[..., 0] * 0.2126
            + frame[..., 1] * 0.7152
            + frame[..., 2] * 0.0722
        )
        gray = luma[..., None].repeat(3, axis=2)
        return frame * (1.0 - amount) + gray * amount
```

Plugins are discovered at boot from:

1. `plugins/*.py` (bundled) and `userdata/plugins/*.py` (user)
2. The `aphelion.plugins` entry-point group on installed packages
3. Classes decorated with `@aphelion_sdk.register_plugin`

See [`../aphelion-sdk/README.md`](../aphelion-sdk/README.md) and `../aphelion-sdk/examples/grayscale_effect.py`.

---

## Architecture

Application packages live under `src/`. `main.py` puts that tree on `sys.path` during development; frozen builds already ship packages beside the interpreter.

| Package | Responsibility |
|---|---|
| `ui/` | PyQt windows, docks, dialogs, node-graph view, timeline chrome, QSS |
| `core/` | Project document, node graph model, serialization, preferences, roto, tracking |
| `timeline/` | Timeline state and playback control |
| `render/` | Decode, probe, frame evaluation, preview, export and tracking workers |
| `effects/` | Frame-level effect implementations used by built-in nodes |
| `app_io/` | `.aph` I/O, plugin and node loaders, theme files |
| `config/` | Constants, default keybinds, theme tokens |
| `utils/` | Logging, paths, process environment |
| `../aphelion-sdk/aphelion_sdk/` | Public plugin SDK (`VideoEffectPlugin`; audio later) |
| `plugins/` | Drop-in `*.py` plugin modules loaded at boot |

UI never owns core logic. Rendering and export run off the UI thread. The frame pipeline is `float32` RGB in `[0, 1]`.

---

## Development

Tests (pytest discovers `tests/` and adds `src/` and `../aphelion-sdk/` to `pythonpath`):

```bash
pip install pytest
pytest
```

Type checking:

```bash
pip install mypy
mypy
```

`mypy.ini` and `pyrefly.toml` both treat `src/` as the application root. Logs write to `logs/aphelion.log` (rotating, 2 MB × 5).

---

## Keyboard shortcuts

Defaults — all remappable in **Preferences** (`Ctrl+,`) or **Keyboard Shortcuts** (`Ctrl+/`).

| Action | Shortcut |
|---|---|
| New / Open / Save | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` |
| Export | `Ctrl+E` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Search nodes | `Tab` |
| Fit graph | `F` |
| Play / Pause | `Space` |
| Previous / Next frame | `Left` / `Right` |
| In / Out | `I` / `O` |
| Focus viewport / graph / timeline / properties | `Ctrl+1` … `Ctrl+4` |

Number keys `1` and `2` create a Video Input and Viewer by default. Slots `3`–`0` are unassigned create-node shortcuts.

---

## License

Proprietary. The plugin SDK is licensed the same way; see `../aphelion-sdk/pyproject.toml`.
