"""UI widgets attached to plugins (panels and popups). Qt-free."""

from core.widgets.registry import (
    WidgetRegistration,
    WidgetRegistry,
    attached_widget_classes,
    global_widget_registry,
    registration_from_widget,
    widget_registry_key,
)

__all__ = [
    "WidgetRegistration",
    "WidgetRegistry",
    "attached_widget_classes",
    "global_widget_registry",
    "registration_from_widget",
    "widget_registry_key",
]
