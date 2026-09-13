"""Consistent help on settings controls and their form labels."""
from PyQt6.QtWidgets import QFormLayout, QLabel, QWidget, QAbstractButton, QComboBox, QAbstractSpinBox


def apply_form_tooltips(root: QWidget) -> None:
    for form in root.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            widget = field.widget() if field else None
            label = label_item.widget() if label_item else None
            if widget is None:
                continue
            title = label.text() if isinstance(label, QLabel) else ""
            text = widget.toolTip()
            if not text and title:
                text = f"Set {title.rstrip(':').lower()}."
                if isinstance(widget, QAbstractSpinBox):
                    text += f" Allowed range: {widget.minimum()} to {widget.maximum()}{widget.suffix()}."
                elif isinstance(widget, QComboBox):
                    text += " Choose an option from the list."
            if text:
                widget.setToolTip(text)
                if label is not None:
                    label.setToolTip(text)
    for button in root.findChildren(QAbstractButton):
        if not button.toolTip() and button.text():
            button.setToolTip(button.text().replace("&", ""))
