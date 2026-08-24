# Plugins in the editor

Aphelion loads third-party nodes written against [`aphelion_sdk`](../../aphelion-sdk/README.md). Authors never import `core`, `effects`, `render`, or `ui`.

## Discovery order

1. Bundled `plugins/*.py` (next to the app)
2. User `userdata/plugins/*.py`
3. Installed packages that advertise `aphelion.plugins` entry points
4. Classes decorated with `@aphelion_sdk.register_plugin` in those modules

A same-stem file in the user folder overrides the bundled module. Files whose names start with `_` are skipped.

Drop-in example: copy `../aphelion-sdk/examples/grayscale_effect.py` into `plugins/` or `userdata/plugins/`, then reload.

## Preferences → Plugins

- Toggle **bundled**, **user**, and **entry-point** loading.
- Enable or disable each discovered plugin. Disabled plugins stay listed but are omitted from Add Node.
- **Reload plugins** re-imports files from disk without restarting.
- **Open bundled folder** / **Open user folder** opens those directories in the system file manager.

Discovery and enablement flags are stored in `userdata/preferences.json` and applied at boot.

Reload applies to **new** nodes. Reopen the project to refresh plugin nodes already on the graph (they keep the class object from when they were created).

## Installing a packaged plugin

```bash
aphelion-sdk build path/to/effect.py -o dist
pip install dist/aphelion_plugin_*.whl
```

Then enable it under Preferences → Plugins (entry points) and reload, or restart the editor.

See [SDK packaging](../../aphelion-sdk/docs/packaging.md) for wheels, entry points, and copying sources into the editor's user plugin folder.
