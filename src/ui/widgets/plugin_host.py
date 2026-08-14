"""Editor-backed ``WidgetHost`` that binds widgets to their parent plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
        return prop.value

    def set_property_value(self, key: str, value: object) -> None:
        """Write a property on the bound node through undo history."""
        node_id: str | None = self._context.node_id
        if node_id is None:
            return
        node = self._editor.project.nodes.get(node_id)
        if node is None:
            return
        prop = node.get_property(key)
        if prop is None or prop.value == value:
            return
        self._editor.history.push(
            SetPropertyCommand(node_id, key, value, old_value=prop.value)
        )
