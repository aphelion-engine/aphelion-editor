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
        _frame_num: int,
    ) -> aphelion_sdk.Frame:
        """Return the source frame unchanged."""
        return frame


def test_video_effect_plugin_maps_metadata() -> None:
    """Plugin class attributes must copy onto the internal node schema."""
    assert _ProbeEffect.plugin_kind == "video"
    assert _ProbeEffect.node_type == "SdkProbe"
    assert _ProbeEffect.node_category == "Plugins"
    assert _ProbeEffect.node_description == "Loader probe."
    assert _ProbeEffect.node_color == (10, 20, 30)
    probe = _ProbeEffect()
    assert probe.node_type == "SdkProbe"


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
