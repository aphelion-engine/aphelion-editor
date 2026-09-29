# Repository Guidelines

## Project Structure & Module Organization

Aphelion Editor is a Python/PyQt6 node-based compositor. Project state and undoable
commands live in `src/core/`; widgets and the editor bridge live in `src/ui/`.
Media decode, playback, and export span `src/render/` and the required `native/`
backend. Keep core logic Qt-free and widget access on the GUI thread. Avoid
blocking that thread with networking, decoding, or export work.

The AI subsystem separates provider adapters, agent execution, transaction-backed
tools, and its Qt UI. Preserve provider-neutral messages and keep authentication
inside adapters. Project files and model context must not contain credentials.
Public plugins use `aphelion_sdk`, not internal editor imports.

## Build, Test, and Development Commands

Keep `aphelion-sdk`, `aphelion-styling`, and `aphelion-editor` as siblings. From the
editor directory, with a Python 3.11+ virtual environment active:

```bash
python -m pip install -e ../aphelion-sdk -e ../aphelion-styling -e ".[dev]"
python native/build.py
python main.py
python -m pytest
python -m pytest tests/test_editor_sdk_extensions.py -q
python -m mypy src
```

`pytest.ini` adds `src` and the sibling SDK to the import path. Use
`QT_QPA_PLATFORM=offscreen` for headless Qt tests. Native build prerequisites are
documented in `native/README.md`; `python native/build.py --check` verifies the
backend. Packaging uses the optional `freeze` dependencies.

## Coding Style & Testing Guidelines

Follow existing Python type annotations and keep UI integration separate from
core behavior. Type-checker configuration treats `src/` as the application root.
Use the editor command/history system for undoable mutations. Test relevant
behavior; include rollback and cancellation checks for agent execution changes.
New test modules need explicit `.gitignore` exceptions because `tests/*` is ignored.

## Commit & Pull Request Guidelines

Recent history uses short descriptive commit subjects without a mandatory prefix.
Follow `CONTRIBUTING.md` and `.github/PULL_REQUEST_TEMPLATE.md`. Describe resulting
behavior, validation, and dependent SDK/styling changes. Keep generated binaries,
private media, credentials, and local user data out of changes.
