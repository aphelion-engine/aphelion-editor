"""Editor-backed ``WidgetHost`` that binds widgets to their parent plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING
from copy import deepcopy

from aphelion_sdk.widgets.host import WidgetContext, WidgetView
from core.history.commands import SetPropertyCommand
from ui.widgets.plugin_view import QtPluginView

if TYPE_CHECKING:
    from ui.windows.editor import Editor


class EditorWidgetHost:
    """Implements ``WidgetHost`` using the live editor, project, and history."""

    def __init__(self, editor: Editor, context: WidgetContext) -> None:
        self._editor: Editor = editor
        self._context: WidgetContext = context

    def create_view(self) -> WidgetView:
        """Return an empty Qt-backed view."""
        return QtPluginView(self._editor)

    def context(self) -> WidgetContext:
        """Return the parent plugin / node binding."""
        return self._context

    def qt_parent(self) -> object:
        """Return the editor window as the PyQt6 parent for custom widgets."""
        return self._editor

    def open_dialog(self, widget_id: str) -> bool:
        """Open a dialog widget attached to the bound parent plugin."""
        return self._editor.open_plugin_dialog(widget_id, context=self._context)

    def get_property_value(self, key: str) -> object | None:
        """Read a property on the bound node."""
        node_id: str | None = self._context.node_id
        if node_id is None:
            return None
        node = self._editor.project.nodes.get(node_id)
        if node is None:
            return None
        prop = node.get_property(key)
        if prop is None:
            return None
        return deepcopy(prop.value)

    def set_property_value(self, key: str, value: object) -> None:
        """Write a property on the bound node through undo history."""
        node_id: str | None = self._context.node_id
        if node_id is None:
            return
        node = self._editor.project.nodes.get(node_id)
        if node is None:
            return
        prop = node.get_property(key)
        if prop is None:
            return
        self.set_node_property(node_id, key, value)

    def available_nodes(self) -> tuple[tuple[str, str], ...]:
        from core.nodes.registry import global_node_registry
        return tuple((info.category, info.name) for info in global_node_registry.get_all_nodes().values())

    def list_nodes(self) -> tuple[str, ...]:
        return tuple(self._editor.project.nodes)

    def create_node(self, category: str, name: str, *, x: float = 0, y: float = 0) -> str:
        from core.nodes.registry import global_node_registry
        from core.history.commands import AddNodeCommand
        info = global_node_registry.get_node_info(category, name)
        if info is None:
            raise KeyError((category, name))
        node = info.create_instance()
        node.x, node.y = x, y
        command = AddNodeCommand(node)
        if not self._editor.history.push(command) or command.node_id is None:
            raise RuntimeError("Editor could not create node")
        return command.node_id

    def remove_node(self, node_id: str) -> bool:
        from core.history.commands import RemoveNodesCommand
        return self._editor.history.push(RemoveNodesCommand([node_id]))

    def connect_nodes(self, output_node_id: str, output_slot: str,
                      input_node_id: str, input_slot: str) -> bool:
        from core.history.commands import ConnectCommand
        return self._editor.history.push(ConnectCommand(output_node_id, output_slot, input_node_id, input_slot))

    def get_node_property(self, node_id: str, key: str) -> object:
        node = self._editor.project.nodes[node_id]
        return deepcopy(node.properties[key].value)

    def set_node_property(self, node_id: str, key: str, value: object) -> None:
        node = self._editor.project.nodes[node_id]
        prop = node.properties[key]
        self._editor.history.push(SetPropertyCommand(node_id, key, deepcopy(value), old_value=deepcopy(prop.value)))

    def set_node_properties(self, node_id: str, values: dict[str, object],
                            label: str = "Plugin properties") -> bool:
        from core.history.commands import CompositeCommand
        node = self._editor.project.nodes[node_id]
        commands = [SetPropertyCommand(node_id, key, deepcopy(value), old_value=deepcopy(node.properties[key].value))
                    for key, value in values.items()]
        return bool(commands) and self._editor.history.push(CompositeCommand(commands, label))
