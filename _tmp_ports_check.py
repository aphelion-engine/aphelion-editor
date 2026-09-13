"""Temporary: inspect the custom node editor dialog against saved definitions."""
from __future__ import annotations

import sys

from app_io.node_loader import NodeLoader
from core.custom_node_store import global_custom_node_store
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
NodeLoader.load_defaults()
global_custom_node_store.load()

from ui.dialogs.custom_node_dialog import CustomNodeEditorDialog

for name in global_custom_node_store.names():
    definition = global_custom_node_store.get(name)
    print("=" * 60)
    print("definition:", name, "in:", [p.name for p in definition.inputs], "out:", [p.name for p in definition.outputs])
    dialog = CustomNodeEditorDialog(definition)
    print("  dialog terminals in:", [n.name for _, n in dialog._terminals("in")])
    print("  dialog terminals out:", [n.name for _, n in dialog._terminals("out")])
    print("  input rows:", dialog._inputs_box.count(), "output rows:", dialog._outputs_box.count())
    print("  project nodes:", [(nid, n.node_type) for nid, n in dialog._project.nodes.items()])
    print("  custom props:", [p.name for p in dialog._custom_properties])
    dialog.done(0)
