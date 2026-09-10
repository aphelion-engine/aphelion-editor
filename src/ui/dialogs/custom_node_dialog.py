"""Dialogs for creating and editing reusable custom (subgraph) nodes."""

from __future__ import annotations

from config.keybinds import KeybindStore
from core.custom_node_store import global_custom_node_store
from core.history import AddNodeCommand, HistoryStack, RemoveNodesCommand
from core.nodes.base import NodeSocketType
from core.nodes.custom_nodes import (DEFAULT_CUSTOM_COLOR, PORT_SOCKET_TYPES,
                                     SUBGRAPH_INPUT_TYPE, SUBGRAPH_OUTPUT_TYPE,
                                     CustomNodeDefinition, SubgraphInputNode,
                                     SubgraphOutputNode, build_node_from_blob,
                                     definition_from_project,
                                     sanitize_port_name, unique_port_name)
from core.nodes.property_link import sockets_compatible
from core.project import Project
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QDialog,
                             QDialogButtonBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QScrollArea, QToolButton,
                             QVBoxLayout, QWidget)
from ui.node_graph.custom_node_ops import build_custom_node_definition
from ui.node_graph.view import NodeGraphView

CUSTOM_NODE_DIALOG_STYLE = """
    QDialog#CustomNodeDialog {
        background-color: #1a1a1e;
        color: #e6e6e6;
    }
    QDialog#CustomNodeDialog QLabel {
        color: #c8c8d0;
        font-size: 12px;
    }
    QDialog#CustomNodeDialog QLabel#CustomNodeTitle {
        color: #f0f0f4;
        font-size: 16px;
        font-weight: 600;
    }
    QDialog#CustomNodeDialog QLabel#CustomNodeSubtitle {
        color: #9a9aa4;
        font-size: 12px;
    }
    QDialog#CustomNodeDialog QGroupBox {
        color: #c8c8d0;
        border: 1px solid #34343c;
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 12px;
        font-size: 11px;
        font-weight: 600;
    }
    QDialog#CustomNodeDialog QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }
    QDialog#CustomNodeDialog QLineEdit,
    QDialog#CustomNodeDialog QComboBox {
        background-color: #222228;
        color: #e6e6e6;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 22px;
    }
    QDialog#CustomNodeDialog QToolButton {
        background-color: #2a2a32;
        color: #e6e6e6;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 2px 8px;
    }
    QDialog#CustomNodeDialog QToolButton:hover {
        background-color: #3a3a44;
    }
    QDialog#CustomNodeDialog QPushButton {
        background-color: #2a2a32;
        color: #e6e6e6;
        border: 1px solid #3a3a44;
        border-radius: 4px;
        padding: 5px 12px;
        min-height: 24px;
    }
    QDialog#CustomNodeDialog QPushButton:hover {
        background-color: #3a3a44;
    }
    QDialog#CustomNodeDialog QScrollArea {
        background: transparent;
        border: none;
    }
"""


# ============================================================================
# Create dialog
# ============================================================================


class CustomNodeCreateDialog(QDialog):
    """Name and describe a custom node collapsed from the selection."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        project: Project,
        node_ids: list[str],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CustomNodeDialog")
        self.setWindowTitle("Create Custom Node")
        self.setStyleSheet(CUSTOM_NODE_DIALOG_STYLE)
        self.setModal(True)
        self.resize(420, 300)

        self._project = project
        self._node_ids = list(node_ids)
        self._color: tuple[int, int, int] = DEFAULT_CUSTOM_COLOR
        self.edit_after: bool = False

        build = build_custom_node_definition(
            project,
            self._node_ids,
            name="Custom Node",
            color=self._color,
        )
        self._port_summary = (
            (
                len(build.definition.inputs),
                len(build.definition.outputs),
            )
            if build is not None
            else (0, 0)
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel("Create Custom Node")
        title.setObjectName("CustomNodeTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Collapse the selected nodes into a reusable chip. It is saved "
            "to your custom node library and appears under the Custom "
            "category in every project."
        )
        subtitle.setObjectName("CustomNodeSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(8)
        self._name_edit = QLineEdit("Custom Node")
        self._name_edit.selectAll()
        form.addRow("Name", self._name_edit)
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Optional description")
        form.addRow("Description", self._desc_edit)

        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self._color_button = QPushButton()
        self._color_button.setFixedWidth(90)
        self._color_button.clicked.connect(self._pick_color)
        color_layout.addWidget(self._color_button)
        color_layout.addStretch(1)
        form.addRow("Color", color_row)
        root.addLayout(form)

        self._ports_label = QLabel()
        root.addWidget(self._ports_label)

        self._overwrite_warning = QLabel()
        self._overwrite_warning.setStyleSheet("color: #e0a458; font-size: 11px;")
        self._overwrite_warning.setWordWrap(True)
        self._overwrite_warning.hide()
        root.addWidget(self._overwrite_warning)

        root.addStretch(1)

        buttons = QDialogButtonBox()
        self._create_button = buttons.addButton(
            "Create", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._create_edit_button = buttons.addButton(
            "Create && Edit…", QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self._create_edit_button.clicked.connect(self._accept_and_edit)
        root.addWidget(buttons)

        self._name_edit.textChanged.connect(self._refresh_state)
        self._refresh_color_button()
        self._refresh_state()

    # -- results -----------------------------------------------------------

    @property
    def node_name(self) -> str:
        return self._name_edit.text().strip() or "Custom Node"

    @property
    def description(self) -> str:
        return self._desc_edit.text().strip()

    @property
    def color(self) -> tuple[int, int, int]:
        return self._color

    @property
    def overwrite(self) -> bool:
        return global_custom_node_store.has(self.node_name)

    # -- internals ---------------------------------------------------------

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(*self._color),
            self,
            "Custom Node Color",
        )
        if chosen.isValid():
            self._color = (chosen.red(), chosen.green(), chosen.blue())
            self._refresh_color_button()

    def _refresh_color_button(self) -> None:
        r, g, b = self._color
        self._color_button.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: #ffffff;"
            "border: 1px solid #3a3a44; border-radius: 4px;"
        )
        self._color_button.setText(f"#{r:02X}{g:02X}{b:02X}")

    def _refresh_state(self) -> None:
        inputs, outputs = self._port_summary
        self._ports_label.setText(
            f"Will expose {inputs} input port(s) and {outputs} output port(s). "
            "You can adjust them after creating."
        )
        name = self.node_name
        exists = global_custom_node_store.has(name)
        if exists:
            self._overwrite_warning.setText(
                f"A custom node named “{name}” already exists. Creating it "
                "will overwrite the saved definition."
            )
            self._overwrite_warning.show()
        else:
            self._overwrite_warning.hide()

    def _accept(self) -> None:
        if self.overwrite and not self._confirm_overwrite():
            return
        self.edit_after = False
        self.accept()

    def _accept_and_edit(self) -> None:
        if self.overwrite and not self._confirm_overwrite():
            return
        self.edit_after = True
        self.accept()

    def _confirm_overwrite(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Overwrite Custom Node",
            f"Overwrite the saved definition for “{self.node_name}”?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


# ============================================================================
# Editor dialog
# ============================================================================


class CustomNodeEditorDialog(QDialog):
    """Edit a custom node's inner graph, ports, and metadata."""

    def __init__(
        self,
        definition: CustomNodeDefinition,
        parent: QWidget | None = None,
        *,
        keybinds: KeybindStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CustomNodeDialog")
        self.setWindowTitle(f"Edit Custom Node — {definition.name}")
        self.setStyleSheet(CUSTOM_NODE_DIALOG_STYLE)
        self.setModal(True)
        self.resize(1040, 660)

        self._source = definition.copy()
        self._color: tuple[int, int, int] = self._source.color
        self._result: CustomNodeDefinition | None = None

        self._project = _project_from_definition(self._source)
        self._history = HistoryStack(self._project)
        self._view = NodeGraphView(
            self._project,
            self._history,
            keybinds or KeybindStore(),
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"Custom Node — {self._source.name}")
        title.setObjectName("CustomNodeTitle")
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._view, 1)
        body.addWidget(self._build_side_panel(), 0)
        root.addLayout(body, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._project.subscribe(self._on_project_changed)
        self._rebuild_port_rows()
        self._refresh_color_button()

    # -- results -----------------------------------------------------------

    @property
    def definition(self) -> CustomNodeDefinition | None:
        return self._result

    # -- layout ------------------------------------------------------------

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        meta = QGroupBox("Definition")
        meta_form = QFormLayout(meta)
        meta_form.setSpacing(6)
        self._name_edit = QLineEdit(self._source.name)
        meta_form.addRow("Name", self._name_edit)
        self._desc_edit = QLineEdit(self._source.description)
        self._desc_edit.setPlaceholderText("Optional description")
        meta_form.addRow("Description", self._desc_edit)
        self._color_button = QPushButton()
        self._color_button.setFixedWidth(90)
        self._color_button.clicked.connect(self._pick_color)
        meta_form.addRow("Color", self._color_button)
        layout.addWidget(meta)

        self._inputs_box = self._build_port_group(
            layout, "Inputs", lambda: self._add_terminal("in")
        )
        self._outputs_box = self._build_port_group(
            layout, "Outputs", lambda: self._add_terminal("out")
        )
        layout.addStretch(1)
        return panel

    def _build_port_group(self, parent_layout: QVBoxLayout, title: str, on_add) -> QVBoxLayout:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(8, 4, 8, 8)
        group_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(190)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        scroll.setWidget(content)
        group_layout.addWidget(scroll)

        add_button = QPushButton(f"Add {title[:-1]}")
        add_button.clicked.connect(on_add)
        group_layout.addWidget(add_button)

        parent_layout.addWidget(group)
        return rows

    # -- port rows ---------------------------------------------------------

    def _terminals(self, kind: str) -> list[tuple[str, object]]:
        wanted = SUBGRAPH_INPUT_TYPE if kind == "in" else SUBGRAPH_OUTPUT_TYPE
        items = [
            (node_id, node)
            for node_id, node in self._project.nodes.items()
            if node.node_type == wanted
        ]
        items.sort(key=lambda item: (float(item[1].y), float(item[1].x)))
        return items

    def _rebuild_port_rows(self) -> None:
        for kind, box in (("in", self._inputs_box), ("out", self._outputs_box)):
            _clear_layout(box)
            terminals = self._terminals(kind)
            if not terminals:
                empty = QLabel("None exposed")
                empty.setStyleSheet("color: #6a6a74; font-size: 11px;")
                box.addWidget(empty)
                continue
            for terminal_id, node in terminals:
                box.addWidget(self._make_port_row(kind, terminal_id, node))

    def _make_port_row(self, kind: str, terminal_id: str, node: object) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        name_edit = QLineEdit(str(node.name))
        name_edit.setMinimumWidth(110)
        name_edit.editingFinished.connect(
            lambda tid=terminal_id, edit=name_edit: self._on_rename(tid, edit)
        )
        layout.addWidget(name_edit, 1)

        combo = QComboBox()
        for socket_type in PORT_SOCKET_TYPES:
            combo.addItem(socket_type.name, socket_type)
        current = getattr(node, "socket_type", NodeSocketType.Frame)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _index, tid=terminal_id, box=combo: self._on_type_change(tid, box)
        )
        layout.addWidget(combo)

        remove = QToolButton()
        remove.setText("✕")
        remove.setToolTip("Remove this port")
        remove.clicked.connect(
            lambda _checked=False, tid=terminal_id: self._remove_terminal(tid)
        )
        layout.addWidget(remove)
        return row

    def _on_rename(self, terminal_id: str, edit: QLineEdit) -> None:
        node = self._project.nodes.get(terminal_id)
        if node is None:
            return
        taken = {
            str(other.name)
            for other_id, other in (
                self._terminals("in") + self._terminals("out")
            )
            if other_id != terminal_id
        }
        base = sanitize_port_name(edit.text(), "Port")
        unique = unique_port_name(base, taken)
        if unique != edit.text():
            edit.setText(unique)
        if node.name == unique:
            return
        node.name = unique
        self._refresh_item(terminal_id)

    def _on_type_change(self, terminal_id: str, combo: QComboBox) -> None:
        node = self._project.nodes.get(terminal_id)
        if node is None:
            return
        socket_type = combo.currentData()
        if not isinstance(socket_type, NodeSocketType):
            return
        node.set_socket_type(socket_type)  # type: ignore[attr-defined]
        self._prune_incompatible(terminal_id)
        self._refresh_item(terminal_id)

    def _add_terminal(self, kind: str) -> None:
        taken = {
            str(node.name)
            for _, node in (self._terminals("in") + self._terminals("out"))
        }
        base = "Input" if kind == "in" else "Output"
        name = unique_port_name(base, taken)
        node = (
            SubgraphInputNode(name)
            if kind == "in"
            else SubgraphOutputNode(name)
        )
        center = self._view.view_center_scene_pos()
        node.x = center.x()
        node.y = center.y()
        command = AddNodeCommand(node)
        if not self._history.push(command):
            return
        node_id = command.node_id
        if node_id is not None:
            self._view.scene.clearSelection()
            item = self._view.node_items.get(node_id)
            if item is not None:
                item.setSelected(True)

    def _remove_terminal(self, terminal_id: str) -> None:
        if terminal_id not in self._project.nodes:
            return
        self._history.push(RemoveNodesCommand([terminal_id]))

    def _prune_incompatible(self, terminal_id: str) -> None:
        for conn in list(self._project.connections):
            if (
                conn.output_node_id != terminal_id
                and conn.input_node_id != terminal_id
            ):
                continue
            out_node = self._project.nodes.get(conn.output_node_id)
            in_node = self._project.nodes.get(conn.input_node_id)
            if out_node is None or in_node is None:
                continue
            out_sock = out_node.outputs.get(conn.output_slot)
            in_sock = in_node.inputs.get(conn.input_slot)
            if (
                out_sock is None
                or in_sock is None
                or not sockets_compatible(out_sock.socket_type, in_sock.socket_type)
            ):
                self._project.disconnect_nodes(conn)

    def _refresh_item(self, node_id: str) -> None:
        item = self._view.node_items.get(node_id)
        if item is None:
            return
        item.relayout_from_content()
        self._view.refresh_connections_for_node(node_id)
        item.update()

    # -- project observer --------------------------------------------------

    def _on_project_changed(self, event: object, data: object) -> None:
        from core.events import ObserverEvent

        if event in (ObserverEvent.NodeAdded, ObserverEvent.NodeRemoved):
            self._rebuild_port_rows()

    # -- color -------------------------------------------------------------

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(*self._color),
            self,
            "Custom Node Color",
        )
        if chosen.isValid():
            self._color = (chosen.red(), chosen.green(), chosen.blue())
            self._refresh_color_button()

    def _refresh_color_button(self) -> None:
        r, g, b = self._color
        self._color_button.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: #ffffff;"
            "border: 1px solid #3a3a44; border-radius: 4px;"
        )
        self._color_button.setText(f"#{r:02X}{g:02X}{b:02X}")

    # -- save --------------------------------------------------------------

    def _on_save(self) -> None:
        self._normalize_terminal_names()
        definition = definition_from_project(
            self._project,
            self._name_edit.text().strip() or self._source.name,
            description=self._desc_edit.text().strip(),
            color=self._color,
        )
        self._result = definition
        self.accept()

    def _normalize_terminal_names(self) -> None:
        taken: set[str] = set()
        for terminal_id, node in self._terminals("in") + self._terminals("out"):
            name = unique_port_name(sanitize_port_name(str(node.name), "Port"), taken)
            taken.add(name)
            node.name = name
            self._refresh_item(terminal_id)

    # -- teardown ----------------------------------------------------------

    def done(self, result: int) -> None:
        # The graph view subscribes to the project; detach both observers so
        # the dialog's widgets can be garbage collected.
        try:
            self._project.unsubscribe(self._on_project_changed)
            self._view.project.unsubscribe(self._view.on_project_changed)
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass
        super().done(result)


# ============================================================================
# Helpers
# ============================================================================


def _project_from_definition(definition: CustomNodeDefinition) -> Project:
    """Build a scratch project for editing ``definition``."""
    project = Project(definition.name)
    for node_id, blob in definition.nodes.items():
        node = build_node_from_blob(blob)
        if node is None:
            continue
        project.add_node(node, node_id=str(node_id))
    for conn in definition.connections:
        project.connect_nodes(
            str(conn.get("output_node_id", "")),
            str(conn.get("output_slot", "value")),
            str(conn.get("input_node_id", "")),
            str(conn.get("input_slot", "value")),
        )
    return project


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


__all__ = ["CustomNodeCreateDialog", "CustomNodeEditorDialog"]
