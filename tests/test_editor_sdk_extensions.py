"""Integration coverage for product-scoped SDK contracts and editor UI."""
from types import SimpleNamespace

import numpy as np
import pytest
from aphelion_sdk import editor as sdk
from app_io.plugin_loader import PluginLoader
from core.history.stack import HistoryStack
from core.nodes.registry import global_node_registry
from core.preferences.models import PluginSettings
from core.project import Project


class Gain(sdk.AudioEffectPlugin):
    plugin_name = "SDK Test Gain"
    def setup_effect_properties(self):
        self.set_property("gain", sdk.number_property(2, 0, 4, label="Gain"))
    def process_audio(self, audio, frame_num):
        return sdk.AudioData(audio.samples * self.float_value("gain", 1), audio.sample_rate)


class Source(sdk.NodePlugin):
    plugin_name = "SDK Test Source"
    def setup_input_outputs(self):
        for name, kind in (("audio", sdk.NodeSocketType.Audio), ("frame", sdk.NodeSocketType.Frame),
                           ("mask", sdk.NodeSocketType.Mask), ("number", sdk.NodeSocketType.Number)):
            self.add_output(name, kind)
    def evaluate(self, frame_num):
        return {"audio": sdk.AudioData(np.full((8, 2), .25, np.float32), 48000),
                "frame": np.ones((2, 2, 3), np.float32),
                "mask": np.ones((2, 2), np.float32), "number": 3.0}


@pytest.fixture
def registered():
    for cls in (Gain, Source):
        global_node_registry.register(cls, cls.node_category, cls.node_type)
    yield
    for cls in (Gain, Source):
        global_node_registry.unregister(cls.node_category, cls.node_type)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application


def test_audio_mix_bypass_and_shape_validation():
    node = Gain()
    audio = sdk.AudioData(np.full((8, 2), .25, np.float32), 48000)
    node.set_input_value("audio", audio)
    assert node.get_property("gain").value == 2
    np.testing.assert_allclose(node.evaluate(0).samples, .5)
    node.set_property("mix", .5)
    np.testing.assert_allclose(node.evaluate(0).samples, .375)
    np.testing.assert_allclose(audio.samples, .25)
    node.set_property("enabled", False)
    assert node.evaluate(0) is audio
    node.set_property("enabled", True)
    node.process_audio = lambda source, frame: sdk.AudioData(np.zeros(2, np.float32), 44100)
    with pytest.raises(ValueError):
        node.evaluate(0)
    assert Gain().evaluate(0) is None


def test_graph_evaluates_multiple_outputs_and_roundtrips(registered):
    project = Project()
    source = project.add_node(Source())
    gain = project.add_node(Gain())
    assert project.connect_nodes(source, "audio", gain, "audio")
    np.testing.assert_allclose(project.evaluate_node(gain, 0, "audio").samples, .5)
    assert project.evaluate_node(source, 0, "number") == 3
    assert project.evaluate_node(source, 0, "frame").shape == (2, 2, 3)
    assert project.evaluate_node(source, 0, "mask").shape == (2, 2)
    restored = Project.from_dict(project.to_dict())
    np.testing.assert_allclose(restored.evaluate_node(gain, 0, "audio").samples, .5)


def test_legacy_video_effect_and_custom_sockets():
    class Invert(sdk.VideoEffectPlugin):
        def process_frame(self, frame, frame_num):
            return 1 - frame
    node = Invert()
    payload = sdk.FrameWithAudio(np.full((2, 2, 3), .2, np.float32), sdk.AudioData.silence(.01))
    node.set_input_value("frame", payload)
    result = node.evaluate(0)
    np.testing.assert_allclose(result.frame, .8)
    assert result.audio is payload.audio
    node.set_property("mix", 50)
    np.testing.assert_allclose(node.evaluate(0).frame, .5)
    class Custom(sdk.VideoEffectPlugin):
        def setup_input_outputs(self):
            self.add_output("value", sdk.NodeSocketType.Number)
        def setup_effect_properties(self):
            self.set_property("value", sdk.number_property(7, 0, 10, label="Value"))
        def evaluate(self, frame_num):
            return self.float_value("value", 0)
    custom = Custom()
    assert list(custom.outputs) == ["value"]
    assert custom.evaluate(0) == 7


def test_product_filter_and_extension_reload(tmp_path):
    source = tmp_path / "extensions.py"
    source.write_text("""
from aphelion_sdk.editor import EditorExtension, PanelWidget, register_plugin
class Tools(PanelWidget):
    widget_id = 'tools'
@register_plugin
class Extension(EditorExtension):
    plugin_name = 'SDK Test Extension'
    widgets = (Tools,)
@register_plugin
class Other(EditorExtension):
    plugin_name = 'Other Product'
    plugin_product = 'other'
@register_plugin
class Future(EditorExtension):
    plugin_name = 'Future API'
    plugin_api_version = 99
""")
    from core.widgets.registry import global_widget_registry
    PluginLoader.unload()
    try:
        settings = PluginSettings(load_entry_points=False)
        assert PluginLoader.load_installed(settings, directories=(tmp_path,)) == 1
        assert global_node_registry.get_node_info("Plugins", "SDK Test Extension") is None
        assert len(global_widget_registry.panels()) == 1
        settings.disabled_plugin_keys = ["Plugins.SDK Test Extension"]
        assert PluginLoader.reload(settings, directories=(tmp_path,)) == 0
        assert not global_widget_registry.all()
    finally:
        PluginLoader.unload()


def test_host_graph_edits_support_undo_redo(registered):
    from ui.widgets.plugin_host import EditorWidgetHost
    project = Project()
    history = HistoryStack(project)
    host = EditorWidgetHost(SimpleNamespace(project=project, history=history), sdk.WidgetContext())
    assert ("Plugins", Source.plugin_name) in host.available_nodes()
    source = host.create_node("Plugins", Source.plugin_name, x=12, y=24)
    gain = host.create_node("Plugins", Gain.plugin_name)
    assert project.nodes[source].x == 12
    assert host.connect_nodes(source, "audio", gain, "audio")
    host.set_node_property(gain, "gain", 3)
    assert host.get_node_property(gain, "gain") == 3
    history.undo()
    assert host.get_node_property(gain, "gain") == 2
    history.redo()
    assert host.get_node_property(gain, "gain") == 3
    assert host.remove_node(source)
    assert not project.connections
    history.undo()
    assert len(project.connections) == 1
    assert source in host.list_nodes()
    with pytest.raises(KeyError):
        host.create_node("Missing", Gain.plugin_name)


def test_inline_inspector_and_control_callbacks(app):
    from PyQt6.QtWidgets import QDoubleSpinBox, QLabel
    from ui.widgets.properties import PropertiesPanel
    from ui.widgets.plugin_host import EditorWidgetHost
    class Inspector(sdk.InspectorWidget):
        widget_title = "Gain tools"
        def build_view(self, host):
            view = host.create_view()
            view.add_label("marker", "Inline SDK inspector")
            view.add_number("gain", "Gain", host.get_property_value("gain"), 0, 4,
                            lambda value: host.set_property_value("gain", value))
            return view
    class InspectedGain(Gain):
        widgets = (Inspector,)
    project = Project()
    node_id = project.add_node(InspectedGain())
    history = HistoryStack(project)
    from PyQt6.QtWidgets import QWidget
    editor = QWidget()
    editor.project, editor.history = project, history
    widget = PropertiesPanel(project, history)
    widget.set_widget_host_factory(lambda context: EditorWidgetHost(editor, context))
    widget.set_node(node_id)
    assert any(label.text() == "Inline SDK inspector" for label in widget.findChildren(QLabel))
    fields = widget.findChildren(QDoubleSpinBox)
    control = next(field for field in fields if field.decimals() == 6)
    control.setValue(3)
    assert project.nodes[node_id].get_property("gain").value == 3
    widget.deleteLater()
    editor.deleteLater()


def test_primitive_updates_are_silent(app):
    from ui.widgets.plugin_view import QtPluginView
    view = QtPluginView()
    changes = []
    view.add_number("number", "Number", 1, 0, 10, changes.append)
    view.add_toggle("toggle", "Toggle", True, changes.append)
    view.add_choice("choice", "Choice", ["a", "b"], "a", changes.append)
    for key, value in (("number", 3), ("toggle", False), ("choice", "b")):
        view.set_value(key, value)
        assert view.get_value(key) == value
    assert changes == []
    with pytest.raises(KeyError):
        view.get_value("missing")
    with pytest.raises(ValueError):
        view.set_value("choice", "missing")
    view.native_widget().deleteLater()


def test_packaging_discovers_new_plugin_bases(tmp_path):
    from aphelion_sdk.packaging.discovery import discover_plugins
    source = tmp_path / "nodes.py"
    source.write_text("from aphelion_sdk.editor import AudioEffectPlugin, EditorExtension\n"
                      "class Audio(AudioEffectPlugin): pass\nclass Tools(EditorExtension): pass\n")
    assert {plugin.class_name for plugin in discover_plugins(source)} == {"Audio", "Tools"}


def test_modeless_dialog_and_disposal(app):
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QWidget
    from core.widgets.registry import global_widget_registry, registration_from_widget
    from ui.dialogs.plugin_dialog import open_attached_dialog, PluginPopupDialog
    from ui.widgets.plugin_host import EditorWidgetHost
    disposed = []
    class Window(sdk.DialogWidget):
        widget_id = "test-modeless"
        widget_modal = False
        def on_dispose(self, host):
            disposed.append(True)
    parent = QWidget()
    project = Project()
    parent.project, parent.history = project, HistoryStack(project)
    registration = registration_from_widget(Window, "Plugins.Window", "Window")
    global_widget_registry.register(registration)
    host = EditorWidgetHost(parent, sdk.WidgetContext(plugin_key="Plugins.Window"))
    try:
        assert open_attached_dialog(parent, "test-modeless", host)
        dialog = parent.findChild(PluginPopupDialog)
        assert dialog is not None and dialog.isVisible() and not dialog.isModal()
        dialog.reject()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert disposed == [True]
        assert global_widget_registry.resolve("test-modeless", plugin_key="Wrong.Plugin") is None
    finally:
        global_widget_registry.clear()
        parent.deleteLater()


def test_extension_menu_command_and_rebuild(app, registered):
    from PyQt6.QtWidgets import QMainWindow
    from ui.windows.menubar import _build_plugin_menu
    def create(host):
        host.create_node("Plugins", Gain.plugin_name)
    class Extension(sdk.EditorExtension):
        plugin_name = "SDK Command Test"
        commands = (sdk.EditorCommand("gain", "Create Gain", create),)
    window = QMainWindow()
    window.project = Project()
    window.history = HistoryStack(window.project)
    PluginLoader._extensions["Plugins.SDK Command Test"] = Extension
    try:
        _build_plugin_menu(window.menuBar(), window)
        menu = window._plugin_command_menu
        action = menu.actions()[0].menu().actions()[0]
        action.trigger()
        assert len(window.project.nodes) == 1
        window.history.undo()
        assert not window.project.nodes
        _build_plugin_menu(window.menuBar(), window)
        assert len([a for a in window.menuBar().actions() if a.text() == "Plugins"]) == 1
    finally:
        PluginLoader._extensions.clear()
        window.deleteLater()


def test_property_values_are_copied_and_batch_is_atomic(registered):
    from ui.widgets.plugin_host import EditorWidgetHost
    project = Project()
    history = HistoryStack(project)
    node = Gain()
    node.set_property("data", sdk.custom_property({"items": [1]}, widget_id="unused", label="Data"))
    node_id = project.add_node(node)
    host = EditorWidgetHost(SimpleNamespace(project=project, history=history), sdk.WidgetContext(node_id=node_id))
    value = host.get_property_value("data")
    value["items"].append(2)
    assert node.get_property("data").value == {"items": [1]}
    assert host.set_node_properties(node_id, {"gain": 3, "mix": .5})
    history.undo()
    assert host.get_node_property(node_id, "gain") == 2
    assert host.get_node_property(node_id, "mix") == 1
    with pytest.raises(KeyError):
        host.set_node_properties(node_id, {"gain": 4, "missing": 1})
    assert host.get_node_property(node_id, "gain") == 2


def test_entry_point_groups_deduplicate_and_isolate_errors(monkeypatch):
    from aphelion_sdk.registration import discover_installed_plugins
    from importlib import metadata
    class Entry:
        def __init__(self, fail=False):
            self.fail = fail
        def load(self):
            if self.fail:
                raise RuntimeError("broken plugin")
            return Gain
    groups = []
    def entries(*, group):
        groups.append(group)
        return [Entry(True), Entry()]
    monkeypatch.setattr(metadata, "entry_points", entries)
    assert discover_installed_plugins() == (Gain,)
    assert groups == ["aphelion.plugins", "aphelion.editor.plugins"]


def test_packaged_example_uses_editor_entry_points(tmp_path):
    import tomllib
    from pathlib import Path
    from aphelion_sdk.packaging.discovery import discover_plugins
    from aphelion_sdk.packaging.project import make_package_spec, materialize_project
    source = Path(__file__).resolve().parents[2] / "aphelion-sdk/examples/editor_extension.py"
    plugins = discover_plugins(source)
    assert len(plugins) == 3
    materialize_project(plugins, tmp_path, make_package_spec(plugins))
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert len(data["project"]["entry-points"]["aphelion.editor.plugins"]) == 3


def test_failed_dropin_does_not_leak_registered_classes(tmp_path):
    source = tmp_path / "broken.py"
    source.write_text("from aphelion_sdk.editor import EditorExtension, register_plugin\n"
                      "@register_plugin\nclass Broken(EditorExtension):\n"
                      "    plugin_name = 'Broken'\nraise RuntimeError('import failed')\n")
    PluginLoader.unload()
    try:
        assert PluginLoader.load_installed(PluginSettings(load_entry_points=False), directories=(tmp_path,)) == 0
        assert not PluginLoader.listed_plugins()
    finally:
        PluginLoader.unload()
