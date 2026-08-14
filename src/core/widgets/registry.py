"""Qt-free registry of widgets attached to loaded plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aphelion_sdk.widgets.base import PluginWidget
from aphelion_sdk.widgets.kinds import (
    DEFAULT_DIALOG_HEIGHT_PX,
    DEFAULT_DIALOG_WIDTH_PX,
    DEFAULT_DOCK_AREA,
    WIDGET_KIND_DIALOG,
    WIDGET_KIND_PANEL,
)


@dataclass(frozen=True, slots=True)
class WidgetRegistration:
    """One widget class owned by an enabled parent plugin.

    Attributes:
        key: ``plugin_key/widget_id``.
        plugin_key: Parent plugin registry key (``category.name``).
        widget_id: Widget id on that plugin.
        widget_class: ``PanelWidget`` or ``DialogWidget`` subclass.
        kind: ``panel`` or ``dialog``.
        title: Dock or window title.
        plugin_name: Parent plugin display name.
        default_visible: Initial dock visibility for panel widgets.
        dock_area: Initial dock area hint.
        show_in_menu: When True, dialogs appear under Plugin Windows.
        dialog_modal: Whether popups block the editor.
        dialog_width: Initial popup width in pixels.
        dialog_height: Initial popup height in pixels.
    """

    key: str
    plugin_key: str
    widget_id: str
    widget_class: type[PluginWidget]
    kind: str
    title: str
    plugin_name: str
    default_visible: bool
    dock_area: str
    show_in_menu: bool
    dialog_modal: bool
    dialog_width: int
    dialog_height: int


class WidgetRegistry:
    """Catalog of widgets harvested from registered plugins."""

    def __init__(self) -> None:
        self._by_key: dict[str, WidgetRegistration] = {}

    def register(self, registration: WidgetRegistration) -> None:
        """Add or replace the registration for ``registration.key``."""
        self._by_key[registration.key] = registration

    def clear(self) -> None:
        """Drop every registration."""
        self._by_key.clear()

    def get(self, key: str) -> WidgetRegistration | None:
        """Return the registration for ``key``, if any."""
        return self._by_key.get(key)

    def resolve(
        self,
        widget_id: str,
        *,
        plugin_key: str = "",
    ) -> WidgetRegistration | None:
        """Look up a widget on ``plugin_key``, then by unique ``widget_id``."""
        if plugin_key:
            attached = self._by_key.get(widget_registry_key(plugin_key, widget_id))
            if attached is not None:
                return attached
        return self._unique_widget_id(widget_id)

    def all(self) -> tuple[WidgetRegistration, ...]:
        """Return every registration in insertion order."""
        return tuple(self._by_key.values())

    def panels(self) -> tuple[WidgetRegistration, ...]:
        """Return dockable panel widgets."""
        return tuple(
            item for item in self._by_key.values() if item.kind == WIDGET_KIND_PANEL
        )

    def dialogs(self, *, menu_only: bool = False) -> tuple[WidgetRegistration, ...]:
        """Return popup dialog widgets.

        Parameters:
            menu_only: When True, skip dialogs with ``show_in_menu`` False.
        """
        items: list[WidgetRegistration] = [
            item for item in self._by_key.values() if item.kind == WIDGET_KIND_DIALOG
        ]
        if menu_only:
            items = [item for item in items if item.show_in_menu]
        return tuple(items)

    def _unique_widget_id(self, widget_id: str) -> WidgetRegistration | None:
        """Return the widget if exactly one registration uses ``widget_id``."""
        matches: list[WidgetRegistration] = [
            item for item in self._by_key.values() if item.widget_id == widget_id
        ]
        if len(matches) == 1:
            return matches[0]
        return None


def widget_registry_key(plugin_key: str, widget_id: str) -> str:
    """Return the composite key for a widget attached to ``plugin_key``."""
    return f"{plugin_key}/{widget_id}"


def registration_from_widget(
    widget_class: type[PluginWidget],
    plugin_key: str,
    plugin_name: str,
) -> WidgetRegistration:
    """Build a registration for ``widget_class`` owned by ``plugin_key``."""
    widget_id: str = widget_class.resolved_id()
    return WidgetRegistration(
        key=widget_registry_key(plugin_key, widget_id),
        plugin_key=plugin_key,
        widget_id=widget_id,
        widget_class=widget_class,
        kind=str(getattr(widget_class, "widget_kind", WIDGET_KIND_PANEL)),
        title=widget_class.resolved_title(),
        plugin_name=plugin_name,
        default_visible=bool(getattr(widget_class, "widget_default_visible", False)),
        dock_area=str(getattr(widget_class, "widget_dock_area", DEFAULT_DOCK_AREA)),
        show_in_menu=bool(getattr(widget_class, "widget_show_in_menu", True)),
        dialog_modal=bool(getattr(widget_class, "widget_modal", True)),
        dialog_width=int(
            getattr(widget_class, "widget_width", DEFAULT_DIALOG_WIDTH_PX)
        ),
        dialog_height=int(
            getattr(widget_class, "widget_height", DEFAULT_DIALOG_HEIGHT_PX)
        ),
    )


def attached_widget_classes(plugin_class: type[Any]) -> tuple[type[PluginWidget], ...]:
    """Return ``PluginWidget`` classes listed on ``plugin_class.widgets``."""
    raw: object = getattr(plugin_class, "widgets", ())
    if not isinstance(raw, tuple):
        return ()
    attached: list[type[PluginWidget]] = []
    for item in raw:
        if isinstance(item, type) and issubclass(item, PluginWidget):
            attached.append(item)
    return tuple(attached)


global_widget_registry: WidgetRegistry = WidgetRegistry()
