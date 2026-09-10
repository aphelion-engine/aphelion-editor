# Packaging the editor

Two different artifacts: **pip wheels** (library/CLI install) and **standalone freeze** (end-user executable / MSI).

All standalone packaging lives in one module, `src/aphelion_build.py`. It owns the release config, the freeze options, the MSI wizard tables, the MSI UI patch, and the plugin-SDK wheel build — so a version bump is a single edit to `BuildConfig` in that file.

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
python -m aphelion_build --exe
python -m aphelion_build --exe --build-dir path/to/output
```

The same flags are available through the app entry point (`python main.py --build`).

On Windows the binary is `AphelionEditor.exe`. The freeze copies `resources/`, `userdata/`, `plugins/`, and `logs/` into the output tree.

To wipe build artifacts:

```bash
python -m aphelion_build --clean
```

## Windows installer

```bash
python -m aphelion_build --installer
python -m aphelion_build --installer --build-dir path/to/output
```

`--installer` is Windows-only. It freezes the editor, bundles the plugin SDK wheel built from `../aphelion-sdk`, and writes `AphelionEditorSetup-<version>-win64.msi` into `releases/` (or `--build-dir`). `--installer` includes a freeze, so it wins if combined with `--exe`.

The MSI wizard defaults to a per-user install under Local App Data, and offers all-users (Program Files), PATH, and desktop-shortcut options, plus an optional pip install of the bundled SDK. Building it requires `cx_Freeze` and `python-msilib` (used to finish the installer UI).
