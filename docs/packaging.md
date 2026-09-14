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

`scripts/build_installer.ps1` wraps the same command and changes into the editor directory first, which matters — cx_Freeze and setuptools both resolve relative outputs from the working directory, and running the build from elsewhere produces a package with missing payload rather than an error.

### Always verify the package

A produced `.msi` is not evidence that the installer works:

```bash
python scripts/verify_msi.py                  # newest MSI in releases/
python scripts/verify_msi.py path/to/setup.msi
```

It checks three things that have each broken silently:

- **Every dialog's `Control_Next` chain is a single cycle over all its controls.** Windows Installer otherwise fails *at install time, on the user's machine*, with error 2810 — "the next control pointers do not form a cycle". The message names control ordinals rather than controls and does not say which dialog is at fault. The offending shape here was two controls pointing at the same successor plus a `Next → Cancel → Back → Next` sub-loop, which is how `OptionsDlg` was built; the build now repairs any broken dialog before committing the database, and this check asserts the repair took effect.

- **`aphelion_native.pyd` is present in the package.** When the native build could not find its output, cx_Freeze froze the app without it and the installer still built.

- **`ProductVersion` matches `APP_VERSION`.** The installer carried `0.1.0` while the application had moved on to `0.1.2`.

`scripts/check_msi_cycles.py` covers the validator itself, including the chains it must reject, plus the Control table the generator produces before the repair pass runs.

Do not interrupt a `cx_Freeze` build. Killing it mid-flight leaves a directory lock behind and the next run fails with `the build_exe directory cannot be cleaned`.
