"""Setuptools shim. Package metadata lives in ``pyproject.toml``.

From ``aphelion-editor``:

    pip install -e ".[dev,freeze]"
    python -m build

The plugin SDK is the sibling package ``../aphelion-sdk`` and is required
by this project.
"""

from setuptools import setup

setup()
