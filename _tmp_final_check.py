"""Final headless end-to-end check: editor -> create -> edit (params/preview)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from app_io.node_loader import NodeLoader
from core.custom_node_store import global_custom_node_store
from core.nodes.color_effects import ExposureContrastNode
from core.nodes.custom_nodes import CustomNode
from core.nodes.filter_effects import GaussianBlurNode
from core.nodes.generator_nodes import SolidColorNode
from core.nodes.viewer import ViewerNode
from core.project import Project
from PyQt6.QtWidgets import QApplication, QDialog


def main() -> int:
    app = QApplication(sys.argv)
    NodeLoader.load_defaults()
    global_custom_node_store._path = Path(tempfile.mkdtemp()) / "custom_nodes.json"
    global_custom_node_store.load()

    project = Project("Flow")
    project.add_node(SolidColorNode(), node_id="s1")
    project.add_node(ExposureContrastNode(), node_id="e1")
    project.add_node(GaussianBlurNode(), node_id="b1")
    project.add_node(ViewerNode(), node_id="v1")
    project.connect_nodes("s1", "frame", "e1", "frame")
    project.connect_nodes("e1", "frame", "b1", "frame")
    project.connect_nodes("b1", "frame", "v1", "frame")
    project.set_preview_width_override(48)

    from ui.dialogs import custom_node_dialog as cnd
    from ui.windows.editor import Editor

    editor = Editor(project)
    view = editor.node_graph

    preview_seen: list[bool] = []

    def fake_create_exec(self) -> int:
        self._name_edit.setText("Flow Param")
        return QDialog.DialogCode.Accepted

    def fake_edit_exec(self) -> int:
        # Preview viewer must exist and be the active viewer while editing.
        vid = self._preview_viewer_id
        preview_seen.append(
            bool(vid) and vid in self._project.nodes
            and self._project.active_viewer == vid
        )
        assert self._tabs.count() == 3
        self._create_parameter("e1", "exposure")
        self._custom_properties[0].name = "amount"
        self._properties_panel.set_node("b1")
        self._on_save()
        return QDialog.DialogCode.Accepted

    cnd.CustomNodeCreateDialog.exec = fake_create_exec  # type: ignore[method-assign]
    cnd.CustomNodeEditorDialog.exec = fake_edit_exec  # type: ignore[method-assign]

    view.scene.clearSelection()
    for node_id in ("e1", "b1"):
        view.node_items[node_id].setSelected(True)
    custom_id = view.create_custom_node_from_selection()
    assert custom_id is not None

    assert view.edit_custom_node(custom_id)
    node = project.nodes[custom_id]
    assert isinstance(node, CustomNode)
    print("preview seen while editing:", preview_seen)
    assert preview_seen == [True], preview_seen
    print("ports:", list(node.inputs), list(node.outputs))
    print("params:", {k: (p.input_type.name, p.value) for k, p in node.properties.items()})
    assert "amount" in node.properties

    # Parameter drives the inner exposure node.
    node.set_property("amount", 200.0)
    project.invalidate_cache(custom_id)
    result = project.evaluate_node("v1", 0, "frame")
    inner = node.embedded_project().nodes["e1"]
    print("result:", result.shape, "inner exposure:", inner.properties["exposure"].value)
    assert result.shape == (27, 48, 3), result.shape
    assert inner.properties["exposure"].value == 200.0

    # Definition saved to disk, no Viewer leaked.
    saved = global_custom_node_store.get("Flow Param")
    assert saved is not None
    assert not any(b.get("node_type") == "Viewer" for b in saved.nodes.values())
    assert [p.name for p in saved.properties] == ["amount"]

    editor.close()
    app.processEvents()
    print("FINAL FLOW OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
