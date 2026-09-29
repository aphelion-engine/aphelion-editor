# Contributing to Aphelion Editor

Contributions to the editor, tests, documentation, and plugins are welcome.
Participate respectfully under our [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up the source workspace

The editor requires both [aphelion-sdk](https://github.com/aphelion-engine/aphelion-sdk)
and [aphelion-styling](https://github.com/aphelion-engine/aphelion-styling).
Clone all three repositories into the same parent directory. Keep these folder
names: the editor's package metadata references the two sibling paths.

```bash
git clone https://github.com/aphelion-engine/aphelion-sdk.git
git clone https://github.com/aphelion-engine/aphelion-styling.git
git clone https://github.com/aphelion-engine/aphelion-editor.git
cd aphelion-editor
python -m venv .venv
```

Your workspace should look like this:

```text
workspace/
  aphelion-editor/
  aphelion-sdk/
  aphelion-styling/
```

Use Python 3.11 or newer. Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install the development environment from `aphelion-editor/`:

```bash
python -m pip install --upgrade pip
python -m pip install -e ../aphelion-sdk -e ../aphelion-styling -e ".[dev]"
python native/build.py
python main.py
```

The native backend requires a C compiler and Python development headers. Use
Visual Studio Build Tools on Windows, Xcode Command Line Tools on macOS, or
`build-essential` and `python3-dev` on Debian/Ubuntu. See the
[native backend guide](native/README.md). Packaging tools are optional; install
`.[dev,freeze]` when working on frozen applications or installers.

If your change needs SDK or styling changes, submit a separate pull request to
that repository and link the dependent pull requests. Document the revisions
needed to reproduce your result. Those repositories have their own licensing terms.

## Find the right place for a change

- `src/core/`: Qt-free project, node, and editing logic.
- `src/render/`: media decoding, rendering, and playback.
- `src/ui/`: PyQt widgets and editor integration.
- `src/ai/`: provider adapters, agent execution, tools, and assistant UI.
- `native/`: required C acceleration backend.
- `docs/` and `tests/`: documentation and regression coverage.

Keep Qt widget access on the GUI thread and long-running decode, export, and
network work off it. Route undoable project changes through the existing command
and history system. Public plugins should import `aphelion_sdk`, rather than
editor internals. Follow the existing type annotations and module conventions.

## Validate a change

Run the relevant checks from the editor directory:

```bash
python -m pytest
python -m pytest tests/test_editor_sdk_extensions.py -q
python -m mypy src
python native/build.py --check
```

For headless Qt tests, set `QT_QPA_PLATFORM=offscreen`. Add focused regression
coverage for behavior changes. Report pre-existing failures separately from
failures caused by your change. The repository currently ignores most new files
under `tests/`; add a specific exception in `.gitignore` for a new test module so
it is included in your pull request.

Manually check affected editor interactions, including undo/redo and cancellation
where relevant. For UI changes, include a screenshot or short recording. For
performance changes, include a reproducible input and before/after measurements.
Never include private footage, credentials, local user data, or unredacted logs.

## Issues and pull requests

Search existing issues before opening a new one. Use the bug report form for
reproduction steps, expected behavior, actual behavior, and environment details.
Use the feature request form to describe the editing problem and desired result.

Create a focused branch, make a small coherent change, and open a pull request
against `main`. Complete the pull request template with the problem, resulting
behavior, validation, and any related SDK or styling changes. Existing commit
messages use short descriptive subjects; a Conventional Commits prefix is not
required. Keep unrelated formatting and generated build output out of the change.

Maintainers may request revisions before merging. A submitted change is not a
promise of acceptance or a release date. By submitting code for inclusion, you
agree to make that contribution available under this repository's
[MIT License](LICENSE), and confirm that you have the right to submit it.
