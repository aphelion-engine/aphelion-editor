"""Tests for the public plugin SDK and drop-in plugin loader."""

from __future__ import annotations

from pathlib import Path

import pytest

import aphelion_sdk
from aphelion_sdk import VideoEffectPlugin
from app_io.plugin_loader import _import_plugin_file
from core.nodes.enums import BlendMode


class _ProbeEffect(VideoEffectPlugin):
    """Minimal effect used to assert SDK metadata mapping."""

    plugin_name = "SdkProbe"
    plugin_category = "Plugins"
    plugin_description = "Loader probe."
    plugin_color = (10, 20, 30)

    def setup_effect_properties(self) -> None:
        """Register a single unused slider so the node can construct."""
        self.set_property(
            "amount",
            aphelion_sdk.slider_property(0, 0, 1, label="Amount"),
        )

    def process_frame(
        self,
        frame: aphelion_sdk.Frame,
        frame_num: int,
    ) -> aphelion_sdk.Frame:
        """Return the source frame unchanged."""
        del frame_num
        return frame


def test_video_effect_plugin_maps_metadata() -> None:
    """Plugin class attributes must copy onto the internal node schema."""
    assert _ProbeEffect.plugin_kind == "video"
    assert _ProbeEffect.node_type == "SdkProbe"
    assert _ProbeEffect.node_category == "Plugins"
    assert _ProbeEffect.node_description == "Loader probe."
    assert _ProbeEffect.node_color == (10, 20, 30)


def test_choice_property_is_exported() -> None:
    """choice_property must be part of the public SDK surface."""
    prop = aphelion_sdk.choice_property(BlendMode.Normal, label="Blend")
    assert prop.label == "Blend"


def test_register_plugin_is_idempotent() -> None:
    """Decorating the same class twice must not duplicate the registry."""
    aphelion_sdk.register_plugin(_ProbeEffect)
    aphelion_sdk.register_plugin(_ProbeEffect)
    matches = [
        cls for cls in aphelion_sdk.get_registered_plugins() if cls is _ProbeEffect
    ]
    assert matches == [_ProbeEffect]


def test_register_plugin_rejects_non_plugin() -> None:
    """Only Plugin subclasses may be registered."""

    class NotAPlugin:
        """Unrelated class used as a negative registration case."""

    with pytest.raises(TypeError):
        aphelion_sdk.register_plugin(NotAPlugin)  # type: ignore[arg-type]


def test_import_plugin_file_registers(tmp_path: Path) -> None:
    """Drop-in ``.py`` files must run ``@aphelion_sdk.register_plugin``."""
    source = tmp_path / "folder_probe.py"
    source.write_text(
        "import aphelion_sdk\n"
        "\n"
        "@aphelion_sdk.register_plugin\n"
        "class FolderProbe(aphelion_sdk.VideoEffectPlugin):\n"
        "    plugin_name = 'FolderProbe'\n"
        "    plugin_category = 'Plugins'\n"
        "    plugin_description = 'Imported from a folder.'\n"
        "    plugin_color = (1, 2, 3)\n"
        "    def setup_effect_properties(self) -> None:\n"
        "        return\n"
        "    def process_frame(self, frame: aphelion_sdk.Frame, _frame_num: int) -> aphelion_sdk.Frame:\n"
        "        return frame\n",
        encoding="utf-8",
    )
    _import_plugin_file(source)
    names = [cls.node_type for cls in aphelion_sdk.get_registered_plugins()]
    assert "FolderProbe" in names


def test_clear_registered_plugins() -> None:
    """Host reload must be able to empty the in-process plugin list."""
    aphelion_sdk.register_plugin(_ProbeEffect)
    aphelion_sdk.clear_registered_plugins()
    assert _ProbeEffect not in aphelion_sdk.get_registered_plugins()


def test_plugin_settings_roundtrip() -> None:
    """Plugin preferences must survive JSON serialization."""
    from core.preferences.models import AppPreferences, PluginSettings

    settings = PluginSettings(
        load_bundled=False,
        load_user=True,
        load_entry_points=False,
        disabled_plugin_keys=["Plugins.Demo"],
    )
    restored = PluginSettings.from_dict(settings.to_dict())
    assert restored == settings
    document = AppPreferences(plugins=settings)
    assert AppPreferences.from_dict(document.to_dict()).plugins == settings


def test_node_registry_unregister() -> None:
    """Unregister must drop a type and leave other keys intact."""
    from core.nodes.registry import NodeRegistry

    registry = NodeRegistry()
    registry.register(_ProbeEffect, "Plugins", "SdkProbe", "probe", (1, 2, 3))
    assert registry.unregister("Plugins", "SdkProbe") is True
    assert registry.get_node_info("Plugins", "SdkProbe") is None
    assert registry.unregister("Plugins", "SdkProbe") is False


def _write_effect_plugin(path: Path, class_name: str, node_name: str) -> None:
    """Write a minimal drop-in ``VideoEffectPlugin`` module for loader tests."""
    path.write_text(
        "import aphelion_sdk\n"
        "\n"
        "@aphelion_sdk.register_plugin\n"
        f"class {class_name}(aphelion_sdk.VideoEffectPlugin):\n"
        f"    plugin_name = '{node_name}'\n"
        "    plugin_category = 'Plugins'\n"
        "    plugin_description = 'Loader test plugin.'\n"
        "    plugin_color = (4, 5, 6)\n"
        "    def setup_effect_properties(self) -> None:\n"
        "        return\n"
        "    def process_frame(self, frame: aphelion_sdk.Frame, _frame_num: int)"
        " -> aphelion_sdk.Frame:\n"
        "        return frame\n",
        encoding="utf-8",
    )


def test_plugin_loader_disable_and_reload(tmp_path: Path) -> None:
    """Disabled keys skip registry; reload picks up newly added files."""
    from app_io.plugin_loader import PluginLoader
    from core.nodes.registry import global_node_registry
    from core.preferences.models import PluginSettings

    first = tmp_path / "reload_alpha.py"
    _write_effect_plugin(first, "ReloadAlpha", "ReloadAlpha")
    base = PluginSettings(load_entry_points=False)
    PluginLoader.unload()
    try:
        enabled = PluginLoader.load_installed(base, directories=(tmp_path,))
        assert enabled == 1
        assert global_node_registry.get_node_info("Plugins", "ReloadAlpha") is not None

        disabled = PluginSettings(
            load_entry_points=False,
            disabled_plugin_keys=["Plugins.ReloadAlpha"],
        )
        assert PluginLoader.reload(disabled, directories=(tmp_path,)) == 0
        assert global_node_registry.get_node_info("Plugins", "ReloadAlpha") is None
        records = PluginLoader.listed_plugins()
        assert len(records) == 1
        assert records[0].enabled is False

        _write_effect_plugin(tmp_path / "reload_beta.py", "ReloadBeta", "ReloadBeta")
        loaded = PluginLoader.reload(base, directories=(tmp_path,))
        assert loaded == 2
        assert global_node_registry.get_node_info("Plugins", "ReloadBeta") is not None
    finally:
        PluginLoader.unload()


def test_msi_upgrade_code_is_guid() -> None:
    """The installer upgrade code must be a Windows GUID string."""
    from freeze_config import MSI_OUTPUT_NAME, MSI_UPGRADE_CODE

    assert MSI_UPGRADE_CODE.startswith("{")
    assert MSI_UPGRADE_CODE.endswith("}")
    assert len(MSI_UPGRADE_CODE) == 38
    assert MSI_OUTPUT_NAME.endswith(".msi")


def test_plugin_widget_is_not_a_plugin() -> None:
    """Dialog and panel widgets must not be Plugin subclasses."""

    class NotesDialog(aphelion_sdk.DialogWidget):
        """Test dialog attached to a plugin."""

        widget_id = "notes"

        def build_view(self, host: aphelion_sdk.WidgetHost) -> aphelion_sdk.WidgetView:
            """Return an empty host view."""
            return host.create_view()

    assert not issubclass(NotesDialog, aphelion_sdk.Plugin)
    with pytest.raises(TypeError):
        aphelion_sdk.register_plugin(NotesDialog)  # type: ignore[arg-type]


def test_loader_attaches_widgets_to_parent_plugin(tmp_path: Path) -> None:
    """Widgets listed on Plugin.widgets are indexed under the plugin key."""
    from app_io.plugin_loader import PluginLoader
    from core.nodes.registry import global_node_registry
    from core.preferences.models import PluginSettings
    from core.widgets.registry import global_widget_registry

    source = tmp_path / "widget_parent.py"
    source.write_text(
        "import aphelion_sdk\n"
        "\n"
        "class NotesDialog(aphelion_sdk.DialogWidget):\n"
        "    widget_id = 'notes'\n"
        "    widget_title = 'Notes'\n"
        "    def build_view(self, host):\n"
        "        return host.create_view()\n"
        "\n"
        "@aphelion_sdk.register_plugin\n"
        "class ParentEffect(aphelion_sdk.VideoEffectPlugin):\n"
        "    plugin_name = 'ParentEffect'\n"
        "    plugin_category = 'Plugins'\n"
        "    widgets = (NotesDialog,)\n"
        "    def setup_effect_properties(self):\n"
        "        return\n"
        "    def process_frame(self, frame, _frame_num):\n"
        "        return frame\n",
        encoding="utf-8",
    )
    PluginLoader.unload()
    try:
        loaded = PluginLoader.load_installed(
            PluginSettings(load_entry_points=False),
            directories=(tmp_path,),
        )
        assert loaded == 1
        assert global_node_registry.get_node_info("Plugins", "ParentEffect") is not None
        assert global_node_registry.get_node_info("Plugins", "NotesDialog") is None
        attached = global_widget_registry.resolve(
            "notes",
            plugin_key="Plugins.ParentEffect",
        )
        assert attached is not None
        assert attached.plugin_key == "Plugins.ParentEffect"
        assert attached.widget_id == "notes"
        records = PluginLoader.listed_plugins()
        assert [record.name for record in records] == ["ParentEffect"]
    finally:
        PluginLoader.unload()


def test_custom_property_stores_widget_id() -> None:
    """custom_property must point at a widget id on the parent plugin."""
    prop = aphelion_sdk.custom_property("", widget_id="notes", label="Notes")
    assert prop.custom_widget_id == "notes"
    assert prop.label == "Notes"


def test_build_qt_widget_defaults_to_none() -> None:
    """Widgets without custom Qt code must fall back to build_view."""

    class EmptyDialog(aphelion_sdk.DialogWidget):
        """Dialog that only uses the default hooks."""

        widget_id = "empty"

    dialog = EmptyDialog()
    assert dialog.build_qt_widget(None, _NullHost()) is None


def test_is_qt_widget_rejects_plain_objects() -> None:
    """is_qt_widget must not treat arbitrary objects as QWidgets."""
    assert aphelion_sdk.is_qt_widget(object()) is False


class _NullHost:
    """Minimal WidgetHost for unit tests that never touch the editor."""

    def create_view(self) -> aphelion_sdk.WidgetView:
        raise NotImplementedError

    def context(self) -> aphelion_sdk.WidgetContext:
        return aphelion_sdk.WidgetContext()

    def qt_parent(self) -> object:
        return None

    def open_dialog(self, widget_id: str) -> bool:
        del widget_id
        return False

    def get_property_value(self, key: str) -> object | None:
        del key
        return None

    def set_property_value(self, key: str, value: object) -> None:
        del key, value


