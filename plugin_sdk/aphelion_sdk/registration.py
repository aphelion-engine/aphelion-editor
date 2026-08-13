"""Plugin registration and discovery.

Two ways for a plugin class to reach the host application:

1. ``@register_plugin`` — for plugins that are already importable in the
   running process (e.g. dropped into a folder the app imports at startup).
2. Installed-package entry points — for plugins distributed as their own
   pip package, advertised under the ``"aphelion.plugins"`` group.
"""

from __future__ import annotations

from importlib import metadata
from typing import TypeVar

from core.nodes.base import Node

_PLUGIN_ENTRY_POINT_GROUP: str = "aphelion.plugins"

_registered_plugins: list[type[Node]] = []

NodeT = TypeVar("NodeT", bound=Node)


def register_plugin(plugin_class: type[NodeT]) -> type[NodeT]:
    """Class decorator that registers a plugin class for in-process discovery.

    Usage:
        @register_plugin
        class MyEffect(EffectPlugin):
            ...
    """
    if plugin_class not in _registered_plugins:
        _registered_plugins.append(plugin_class)
    return plugin_class


def get_registered_plugins() -> tuple[type[Node], ...]:
    """Return every plugin class registered so far via ``register_plugin``."""
    return tuple(_registered_plugins)


def discover_installed_plugins() -> tuple[type[Node], ...]:
    """Discover plugin classes exposed by installed packages.

    Third-party packages advertise plugins under the ``"aphelion.plugins"``
    entry-point group, each entry pointing at an ``EffectPlugin`` (or other
    SDK base class) subclass.

    Returns:
        The discovered plugin classes. Entries that fail to load or are not
        ``Node`` subclasses are silently skipped.
    """
    discovered: list[type[Node]] = []
    for entry_point in metadata.entry_points(group=_PLUGIN_ENTRY_POINT_GROUP):
        try:
            plugin_class = entry_point.load()
        except (ImportError, AttributeError):
            continue
        if isinstance(plugin_class, type) and issubclass(plugin_class, Node):
            discovered.append(plugin_class)
    return tuple(discovered)
