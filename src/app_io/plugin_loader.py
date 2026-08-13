"""Registers third-party Aphelion SDK plugins into the global node registry.

Plugins are authored against ``aphelion_sdk`` (see the sibling
``aphelion-sdk/`` package) and never touch ``core`` directly. This loader
is the one place that bridges plugin classes back into the same
``NodeRegistry`` built-in nodes use, so plugin nodes are indistinguishable
from built-ins everywhere else in the app.

Discovery order:
1. Import ``*.py`` files from bundled ``plugins/`` and ``userdata/plugins/``.
2. Load classes advertised under the ``aphelion.plugins`` entry-point group.
3. Collect classes registered in-process via ``@register_plugin``.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import ClassVar

from config.constants import PLUGINS_DIR_NAME, USERDATA_DIR_NAME
from core.nodes import Node, global_node_registry
from utils.logging_setup import get_logger
from utils.paths import app_data_path, app_root, ensure_directory

_LOG = get_logger("plugins")
_MODULE_PREFIX: str = "aphelion_plugin_"


def plugin_directories() -> tuple[Path, ...]:
    """Return bundled then user plugin folders, creating them when missing.

    Returns:
        ``(bundled_plugins, user_plugins)``. Bundled files load first so a
        same-named user module can override them.

    Side effects:
        Creates both directories when they do not exist.
    """
    bundled: Path = ensure_directory(app_root() / PLUGINS_DIR_NAME)
    user: Path = ensure_directory(app_data_path(USERDATA_DIR_NAME, PLUGINS_DIR_NAME))
    return bundled, user


def _plugin_python_files(directory: Path) -> tuple[Path, ...]:
    """Return top-level plugin modules in ``directory`` (no ``_`` prefix)."""
    return tuple(
        sorted(
            path
            for path in directory.glob("*.py")
            if path.is_file() and not path.name.startswith("_")
        )
    )


def _import_plugin_file(path: Path) -> None:
    """Import one plugin module so ``@register_plugin`` can run.

    Parameters:
        path: Absolute path to a ``.py`` plugin file.

    Side effects:
        Executes the module and may register plugin classes.

    Raises:
        None. Import failures are logged and skipped.
    """
    module_name: str = f"{_MODULE_PREFIX}{path.stem}"
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        _LOG.warning("Could not create import spec for plugin: %s", path)
        return
    module: ModuleType = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001
        _LOG.exception("Failed to import plugin module: %s", path)


def _import_directory_plugins() -> int:
    """Import every drop-in plugin file from known plugin folders."""
    imported = 0
    for directory in plugin_directories():
        for path in _plugin_python_files(directory):
            _import_plugin_file(path)
            imported += 1
    return imported


def _unique_plugin_classes(classes: tuple[type[Node], ...]) -> tuple[type[Node], ...]:
    """Return ``classes`` with duplicates removed, preserving order."""
    seen: set[type[Node]] = set()
    unique: list[type[Node]] = []
    for plugin_class in classes:
        if plugin_class in seen:
            continue
        seen.add(plugin_class)
        unique.append(plugin_class)
    return tuple(unique)


def _discover_plugin_classes() -> tuple[type[Node], ...]:
    """Return graph-capable plugin classes, or empty if the SDK is missing."""
    try:
        from aphelion_sdk import discover_installed_plugins, get_registered_plugins
    except ImportError:
        _LOG.info("aphelion_sdk not installed; skipping plugin discovery")
        return ()
    discovered = (*discover_installed_plugins(), *get_registered_plugins())
    node_plugins: tuple[type[Node], ...] = tuple(
        cls for cls in discovered if issubclass(cls, Node)
    )
    return _unique_plugin_classes(node_plugins)


class PluginLoader:
    """Bootstraps SDK plugin node classes into ``global_node_registry``."""

    _loaded: ClassVar[bool] = False

    @staticmethod
    def load_installed() -> int:
        """Register every discoverable plugin class.

        Missing or broken plugins never abort startup: a missing SDK is
        treated as "zero plugins found", not an error.

        Returns:
            The number of plugin node types registered.
        """
        imported = _import_directory_plugins()
        _LOG.debug("Imported %s drop-in plugin module(s)", imported)
        registered = PluginLoader._register_classes(_discover_plugin_classes())
        PluginLoader._loaded = True
        return registered

    @staticmethod
    def _register_classes(plugin_classes: tuple[type[Node], ...]) -> int:
        """Register ``plugin_classes`` on the global node registry."""
        registered = 0
        for plugin_class in plugin_classes:
            try:
                global_node_registry.register(
                    plugin_class,
                    plugin_class.node_category,
                    plugin_class.node_type,
                    plugin_class.node_description,
                    plugin_class.node_color,
                )
                registered += 1
            except Exception:  # noqa: BLE001
                _LOG.exception("Failed to register plugin node: %s", plugin_class)
        return registered
