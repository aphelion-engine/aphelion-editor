# Aphelion Plugin SDK

Public, stable API for writing custom node plugins for the Aphelion video
editor. This package wraps Aphelion's internal node system (`core.nodes`)
and exposes only the pieces plugin authors need, under a small, documented
surface.

## Rules for plugin authors

- Only ever `import aphelion_sdk` (or its submodules). Never import from
  `core`, `effects`, `render`, `ui`, or any other internal Aphelion package.
  The internal API is not stable and is not part of this contract.
- Plugins run inside the Aphelion process, so this package must be
  importable from an environment where the Aphelion application itself is
  also importable (either running from the app's repo root, or installed
  alongside it).

## Installation (development)

From the Aphelion repo root, in the app's virtual environment:

```bash
pip install -e ./plugin_sdk
```

## Quick start

```python
from aphelion_sdk import EffectPlugin, Frame, slider_property


class GrayscaleEffect(EffectPlugin):
    """Desaturates a frame by a user-controlled amount."""

    plugin_name = "Grayscale"
    plugin_category = "Plugins"
    plugin_description = "Blend a frame toward grayscale."
    plugin_color = (140, 140, 140)

    def setup_effect_properties(self) -> None:
        self.set_property(
            "amount",
            slider_property(
                100, 0, 100,
                label="Amount",
                description="How much to desaturate the frame.",
                suffix="%",
            ),
        )

    def process_frame(self, frame: Frame, frame_num: int) -> Frame:
        amount = self.float_value("amount", 100.0) / 100.0
        luma = (
            frame[..., 0] * 0.2126
            + frame[..., 1] * 0.7152
            + frame[..., 2] * 0.0722
        )
        gray = luma[..., None].repeat(3, axis=2)
        return frame * (1.0 - amount) + gray * amount
```

See `examples/grayscale_effect.py` for the full runnable example.

## Registering a plugin

Plugins are discovered by the host application in one of two ways:

1. **In-process registration** — decorate your class with
   `@register_plugin` before the app's plugin loader stage runs.
2. **Installed package discovery** — expose your plugin class under the
   `aphelion.plugins` entry-point group in your package's `pyproject.toml`:

```toml
[project.entry-points."aphelion.plugins"]
grayscale = "my_plugin_package.grayscale:GrayscaleEffect"
```

## API surface

| Symbol | Purpose |
|---|---|
| `EffectPlugin` | Base class for a single-input/output frame effect. |
| `Frame` | Type alias for a plugin frame buffer (`HxWx3` `float32`, `[0, 1]`). |
| `ColorRgb` | Type alias for an RGB color property (`tuple[int, int, int]`, 0-255). |
| `slider_property`, `number_property`, `toggle_property`, `text_property`, `color_property`, `choice_property` | Property builders for `setup_effect_properties`. |
| `register_plugin` | Decorator to register a plugin class for in-process discovery. |
| `get_registered_plugins` | Returns all classes registered via `register_plugin`. |
