"""Registers third-party Aphelion SDK plugins into the global node registry.

Plugins are authored against ``aphelion_sdk`` (see ``plugin_sdk/``) and never
touch ``core`` directly. This loader is the one place that bridges plugin
classes back into the same ``NodeRegistry`` built-in nodes use, so plugin
nodes are indistinguishable from built-ins everywhere else in the app.
"""

from __future__ import annotations

from typing import ClassVar

from core.nodes import Node, global_node_registry
from utils.logging_setup import get_logger

_LOG = get_logger("plugins")


class PluginLoader:
    """Bootstraps SDK plugin node classes into ``global_node_registry``."""

    _loaded: ClassVar[bool] = False

    @staticmethod
    def load_installed() -> int:
        """Register every discoverable plugin class.

        Combines classes registered in-process via ``@register_plugin`` with
        classes exposed by installed packages via the ``"aphelion.plugins"``
        entry-point group. Missing or broken plugins never abort startup:
        the SDK being absent (e.g. not yet installed) is treated as "zero
        plugins found", not an error.

        Returns:
            The number of plugin node types registered.
        """
        try:
            from aphelion_sdk import discover_installed_plugins, get_registered_plugins
        except ImportError:
            _LOG.info("aphelion_sdk not installed; skipping plugin discovery")
            return 0

        plugin_classes: tuple[type[Node], ...] = (
            *discover_installed_plugins(),
            *get_registered_plugins(),
        )
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
        PluginLoader._loaded = True
        return registered
