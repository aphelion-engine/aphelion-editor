# Development

Treat the editor as production software: full type annotations, UI separated from core, no UI-thread decode/export.

## Tests

pytest discovers `tests/` and adds `src/` plus `../aphelion-sdk/` to `pythonpath` (`pytest.ini`).

```bash
pip install -e ".[dev]"
pytest
```

## Type checking

```bash
mypy
```

`mypy.ini` and `pyrefly.toml` treat `src/` as the application root. The SDK's type config also points at `../aphelion-editor/src` because `VideoEffectPlugin` subclasses an internal frame node.

## Layout rules

- `ui/` is PyQt only. `core/` is Qt-free.
- Public plugins import `aphelion_sdk` only.
- Keep functions short; prefer new modules over god classes.

## Logging

Logs write to `logs/aphelion.log` (rotating, 2 MB × 5). Default level is `INFO` (`config.constants`). The in-app log dock is `Ctrl+Shift+L`.

## Running from source

`python main.py` uses `srcpath.py` so `src/` is importable without an editable install. Frozen builds do not use that shim.
