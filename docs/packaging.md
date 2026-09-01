# Packaging the editor

Two different artifacts: **pip wheels** (library/CLI install) and **standalone freeze** (end-user executable / MSI).

## Pip wheels

From `aphelion-editor/` (`pip install -e ".[dev]"` provides the `build` frontend):

```bash
python -m build
python -m build ../aphelion-sdk
```

| Package | Directory | Distribution name |
|---|---|---|
| Editor | `aphelion-editor/` | `aphelion-editor` |
| Plugin SDK | `../aphelion-sdk/` | `aphelion-plugin-sdk` |

Wheels land in each package's `dist/`.

Console script after install: `aphelion`.

## Standalone freeze

Requires the `freeze` extra (`cx_Freeze` ≥ 8.6). Intermediates go to `build/`. The executable tree defaults to `dist/`.

```bash
python main.py --build
python main.py --build --build-dir path/to/output
```

On Windows the binary is `AphelionEditor.exe`. The freeze copies `resources/`, `userdata/`, `plugins/`, and `logs/` into the output tree.

## Windows installer

```bash
python main.py --build-installer
python main.py --build-installer --build-dir path/to/output
```

`--build-installer` is Windows-only. It freezes the editor and writes `AphelionEditorSetup-0.1.0-win64.msi` into `dist/` (or `--build-dir`). If both `--build` and `--build-installer` are passed, the installer path is used.

The MSI defaults to a per-user install under Local App Data, with optional all-users (Program Files), PATH, and desktop shortcut. Building it requires `cx_Freeze` and `python-msilib` (used to finish the installer UI).
