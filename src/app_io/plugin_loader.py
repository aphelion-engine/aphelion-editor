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
import sys
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar, TypeGuard

from config.constants import PLUGINS_DIR_NAME, USERDATA_DIR_NAME
from core.nodes import Node, global_node_registry
from core.preferences.models import PluginSettings
from core.widgets.registry import (
    attached_widget_classes,
    global_widget_registry,
    registration_from_widget,
)
from utils.logging_setup import get_logger
from utils.paths import app_data_path, app_root, ensure_directory

_LOG = get_logger("plugins")
_MODULE_PREFIX: str = "aphelion_plugin_"

SOURCE_BUNDLED: str = "bundled"
SOURCE_USER: str = "user"
SOURCE_ENTRY_POINT: str = "entry-point"
SOURCE_IN_PROCESS: str = "in-process"


@dataclass(frozen=True, slots=True)
class PluginRecord:
    """Discovered plugin identity shown in Preferences and used for enablement."""

    key: str
    name: str
    category: str
    description: str
    author: str
    source: str
    enabled: bool
    module_name: str
    kind: str


def plugin_directories() -> tuple[Path, Path]:
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


def plugin_registry_key(plugin_class: type[Any]) -> str:
    """Return the ``category.name`` registry key for a plugin class."""
    return f"{_plugin_category(plugin_class)}.{_plugin_display_name(plugin_class)}"


def _plugin_category(plugin_class: type[Any]) -> str:
    """Return the public category for ``plugin_class``."""
    category = getattr(plugin_class, "plugin_category", None)
    if isinstance(category, str) and category:
        return category
    node_category = getattr(plugin_class, "node_category", None)
    if isinstance(node_category, str) and node_category:
        return node_category
    return "Plugins"


def _plugin_display_name(plugin_class: type[Any]) -> str:
    """Return the public display name for ``plugin_class``."""
    name = getattr(plugin_class, "plugin_name", None)
    if isinstance(name, str) and name:
        return name
    node_type = getattr(plugin_class, "node_type", None)
    if isinstance(node_type, str) and node_type:
        return node_type
    return plugin_class.__name__


def _plugin_python_files(directory: Path) -> tuple[Path, ...]:
    """Return top-level plugin modules in ``directory`` (no ``_`` prefix)."""
    return tuple(
        sorted(
            path
            for path in directory.glob("*.py")
            if path.is_file() and not path.name.startswith("_")
        )
    )


def _import_plugin_file(path: Path, source: str = SOURCE_USER) -> str | None:
    """Import one plugin module so ``@register_plugin`` can run.

    Parameters:
        path: Absolute path to a ``.py`` plugin file.
        source: Discovery origin recorded for Preferences (``bundled`` / ``user``).

    Returns:
        Imported module name, or ``None`` when the file could not be loaded.

    Side effects:
        Executes the module, may register plugin classes, and records the
        module on ``PluginLoader`` for later unload.

    Raises:
        None. Import failures are logged and skipped.
    """
    module_name: str = f"{_MODULE_PREFIX}{path.stem}"
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        _LOG.warning("Could not create import spec for plugin: %s", path)
        return None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001
        sys.modules.pop(module_name, None)
        _LOG.exception("Failed to import plugin module: %s", path)
        return None
    PluginLoader.track_imported_module(module_name, source)
    return module_name


def _import_directory_plugins(directory: Path, source: str) -> int:
    """Import every drop-in plugin file from ``directory``."""
    imported = 0
    for path in _plugin_python_files(directory):
        if _import_plugin_file(path, source) is not None:
            imported += 1
    return imported


def _unique_plugin_classes(classes: tuple[type[Any], ...]) -> tuple[type[Any], ...]:
    """Return ``classes`` with duplicates removed, preserving order."""
    seen: set[type[Any]] = set()
    unique: list[type[Any]] = []
    for plugin_class in classes:
        if plugin_class in seen:
            continue
        seen.add(plugin_class)
        unique.append(plugin_class)
    return tuple(unique)


def _latest_by_registry_key(
    classes: tuple[type[Any], ...],
) -> tuple[type[Any], ...]:
    """Keep the last class for each registry key."""
    by_key: dict[str, type[Any]] = {}
    for plugin_class in classes:
        by_key[plugin_registry_key(plugin_class)] = plugin_class
    return tuple(by_key.values())


def _is_node_class(candidate: type[Any]) -> TypeGuard[type[Node]]:
    """Return whether ``candidate`` can be registered as a graph node."""
    return issubclass(candidate, Node)


def _node_plugin_classes(classes: tuple[type[Any], ...]) -> tuple[type[Node], ...]:
    """Return classes that can be registered as graph nodes."""
    return tuple(cls for cls in classes if _is_node_class(cls))


def _directories_to_import(
    settings: PluginSettings,
    override: tuple[Path, ...] | None,
) -> list[tuple[Path, str]]:
    """Return ``(directory, source)`` pairs that should be imported."""
    if override is not None:
        return [(path, SOURCE_USER) for path in override]
    bundled, user = plugin_directories()
    pairs: list[tuple[Path, str]] = []
    if settings.load_bundled:
        pairs.append((bundled, SOURCE_BUNDLED))
    if settings.load_user:
        pairs.append((user, SOURCE_USER))
    return pairs


class PluginLoader:
    """Bootstraps SDK plugin node classes into ``global_node_registry``."""

    _loaded: ClassVar[bool] = False
    _registered_keys: ClassVar[list[str]] = []
    _imported_modules: ClassVar[list[str]] = []
    _module_sources: ClassVar[dict[str, str]] = {}
    _records: ClassVar[list[PluginRecord]] = []
    _last_settings: ClassVar[PluginSettings | None] = None
    _last_directories: ClassVar[tuple[Path, ...] | None] = None
    _entry_point_classes: ClassVar[set[type[Any]]] = set()

    @classmethod
    def track_imported_module(cls, module_name: str, source: str) -> None:
        """Record a drop-in module so ``unload`` can drop it from ``sys.modules``."""
        cls._module_sources[module_name] = source
        if module_name not in cls._imported_modules:
            cls._imported_modules.append(module_name)

    @staticmethod
    def listed_plugins() -> tuple[PluginRecord, ...]:
        """Return the last discovered plugin records (enabled and disabled)."""
        return tuple(PluginLoader._records)

    @staticmethod
    def load_installed(
        settings: PluginSettings | None = None,
        *,
        directories: tuple[Path, ...] | None = None,
    ) -> int:
        """Register every discoverable, enabled plugin class.

        Missing or broken plugins never abort startup: a missing SDK is
        treated as "zero plugins found", not an error.

        Parameters:
            settings: Discovery and enablement flags. Defaults to all-on.
            directories: Optional folder override used by tests. When set,
                bundled/user directories from ``settings`` are ignored.

        Returns:
            The number of plugin node types registered.
        """
        if PluginLoader._loaded:
            return sum(1 for record in PluginLoader._records if record.enabled)
        resolved = settings if settings is not None else PluginSettings()
        PluginLoader._last_settings = resolved
        PluginLoader._last_directories = directories
        imported = 0
        for directory, source in _directories_to_import(resolved, directories):
            imported += _import_directory_plugins(directory, source)
        _LOG.debug("Imported %s drop-in plugin module(s)", imported)
        registered = PluginLoader._register_classes(
            PluginLoader._discover(resolved),
            resolved,
        )
        PluginLoader._loaded = True
        return registered

    @staticmethod
    def reload(
        settings: PluginSettings | None = None,
        *,
        directories: tuple[Path, ...] | None = None,
    ) -> int:
        """Unload plugin nodes and re-import from disk.

        Parameters:
            settings: Replacement discovery flags. Defaults to the last load.
            directories: Optional folder override. Defaults to the last load.

        Returns:
            The number of plugin node types registered after reload.

        Side effects:
            Unregisters previously loaded plugin types, drops imported plugin
            modules, and re-registers enabled classes.
        """
        resolved = settings if settings is not None else PluginLoader._last_settings
        dirs = directories if directories is not None else PluginLoader._last_directories
        PluginLoader.unload()
        return PluginLoader.load_installed(resolved, directories=dirs)

    @staticmethod
    def unload() -> None:
        """Remove plugin node types, attached widgets, and drop imported modules.

        Built-in node types are left registered. Existing graph instances keep
        their previous class objects until the project is reopened.

        Side effects:
            Mutates ``global_node_registry``, ``global_widget_registry``,
            and ``sys.modules``.
        """
        PluginLoader._unregister_tracked()
        global_widget_registry.clear()
        PluginLoader._drop_imported_modules()
        try:
            from aphelion_sdk import clear_registered_plugins
        except ImportError:
            clear_registered_plugins = None
        if clear_registered_plugins is not None:
            clear_registered_plugins()
        PluginLoader._records = []
        PluginLoader._entry_point_classes = set()
        PluginLoader._loaded = False

    @staticmethod
    def _discover(settings: PluginSettings) -> tuple[type[Any], ...]:
        """Return every discoverable plugin class, tagging entry-point origins."""
        try:
            from aphelion_sdk import discover_installed_plugins, get_registered_plugins
        except ImportError:
            _LOG.info("aphelion_sdk not installed; skipping plugin discovery")
            return ()
        entry_classes: tuple[type[Any], ...] = ()
        if settings.load_entry_points:
            entry_classes = tuple(discover_installed_plugins())
        PluginLoader._entry_point_classes = set(entry_classes)
        registered = tuple(get_registered_plugins())
        merged = _unique_plugin_classes((*entry_classes, *registered))
        return _latest_by_registry_key(_node_plugin_classes(merged))

    @staticmethod
    def _unregister_tracked() -> None:
        """Unregister node types previously added by this loader."""
        for key in PluginLoader._registered_keys:
            category, _, name = key.partition(".")
            global_node_registry.unregister(category, name)
        PluginLoader._registered_keys = []

    @staticmethod
    def _drop_imported_modules() -> None:
        """Remove drop-in plugin modules from ``sys.modules``."""
        for module_name in PluginLoader._imported_modules:
            sys.modules.pop(module_name, None)
        PluginLoader._imported_modules = []
        PluginLoader._module_sources = {}

    @staticmethod
    def _register_classes(
        plugin_classes: tuple[type[Any], ...],
        settings: PluginSettings,
    ) -> int:
        """Register enabled plugins and store Preferences records."""
        disabled = set(settings.disabled_plugin_keys)
        records: list[PluginRecord] = []
        registered = 0
        for plugin_class in plugin_classes:
            record = PluginLoader._make_record(plugin_class, disabled)
            records.append(record)
            if not record.enabled:
                continue
            if PluginLoader._register_enabled(plugin_class, record.key):
                registered += 1
        PluginLoader._records = records
        return registered

    @staticmethod
    def _register_enabled(plugin_class: type[Any], key: str) -> bool:
        """Register one enabled plugin node and harvest its widgets."""
        if not _is_node_class(plugin_class):
            _LOG.warning("Skipping non-node plugin type: %s", plugin_class)
            return False
        if not PluginLoader._register_one(plugin_class, key):
            return False
        PluginLoader._register_attached_widgets(plugin_class, key)
        return True

    @staticmethod
    def _register_attached_widgets(plugin_class: type[Any], plugin_key: str) -> None:
        """Index ``plugin_class.widgets`` on the parent plugin key."""
        plugin_name = _plugin_display_name(plugin_class)
        for widget_class in attached_widget_classes(plugin_class):
            try:
                global_widget_registry.register(
                    registration_from_widget(widget_class, plugin_key, plugin_name)
                )
            except Exception:  # noqa: BLE001
                _LOG.exception(
                    "Failed to attach widget %s to plugin %s",
                    widget_class,
                    plugin_key,
                )

    @staticmethod
    def _make_record(plugin_class: type[Any], disabled: set[str]) -> PluginRecord:
        """Build a Preferences row for ``plugin_class``."""
        key = plugin_registry_key(plugin_class)
        kind = str(getattr(plugin_class, "plugin_kind", "plugin"))
        return PluginRecord(
            key=key,
            name=_plugin_display_name(plugin_class),
            category=_plugin_category(plugin_class),
            description=str(getattr(plugin_class, "plugin_description", "")),
            author=str(getattr(plugin_class, "plugin_author", "")),
            source=PluginLoader._source_for(plugin_class),
            enabled=key not in disabled,
            module_name=plugin_class.__module__,
            kind=kind,
        )

    @staticmethod
    def _source_for(plugin_class: type[Any]) -> str:
        """Return the discovery origin for a plugin class."""
        source = PluginLoader._module_sources.get(plugin_class.__module__)
        if source is not None:
            return source
        if plugin_class in PluginLoader._entry_point_classes:
            return SOURCE_ENTRY_POINT
        return SOURCE_IN_PROCESS

    @staticmethod
    def _register_one(plugin_class: type[Node], key: str) -> bool:
        """Register one plugin class; return whether it succeeded."""
        try:
            global_node_registry.register(
                plugin_class,
                plugin_class.node_category,
                plugin_class.node_type,
                plugin_class.node_description,
                plugin_class.node_color,
            )
        except Exception:  # noqa: BLE001
            _LOG.exception("Failed to register plugin node: %s", plugin_class)
            return False
        PluginLoader._registered_keys.append(key)
        return True
