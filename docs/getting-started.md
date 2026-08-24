# Getting started

Aphelion Editor is a Python 3.11+ desktop app. The public plugin SDK lives in the sibling `aphelion-sdk` package and is installed automatically with the editor.

## Requirements

| Dependency | Role |
|---|---|
| Python 3.11+ | Runtime |
| [PyQt6](https://pypi.org/project/PyQt6/) ≥ 6.6 | UI |
| [NumPy](https://pypi.org/project/numpy/) ≥ 1.26 | Frame buffers |
| [OpenCV](https://pypi.org/project/opencv-python-headless/) ≥ 4.8 | Decode, tracking, effects |
| [imageio](https://pypi.org/project/imageio/) ≥ 2.34 + [imageio-ffmpeg](https://pypi.org/project/imageio-ffmpeg/) | Media I/O |
| [cx_Freeze](https://pypi.org/project/cx-Freeze/) ≥ 8.6 | Optional freeze / MSI |

## Install from source

From `aphelion-editor/`:

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

Editable install with tests and freeze extras (pulls in `../aphelion-sdk`):

```bash
pip install -e ".[dev,freeze]"
```

Runtime-only:

```bash
pip install -r requirements.txt
```

`requirements.txt` does not install the SDK. Prefer `pip install -e ".[dev,freeze]"` for development.

## Launch

```bash
python main.py
aphelion --version
```

The launcher opens first: new project, open a `.aph` file, or pick a recent project.

Default new project is **1920×1080**, **30 fps**, **10 seconds**.

## Next

- [User guide](user-guide.md)
- [Packaging](packaging.md) (wheels, freeze, Windows installer)
- [SDK authoring](../../aphelion-sdk/docs/authoring.md)
