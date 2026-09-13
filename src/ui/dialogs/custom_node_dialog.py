"""Dialogs for creating and editing reusable custom (subgraph) nodes."""

from __future__ import annotations

from config.keybinds import KeybindStore
from core.custom_node_store import global_custom_node_store
from core.history import AddNodeCommand, HistoryStack, RemoveNodesCommand
from core.nodes.base import NodeSocketType
from core.nodes.custom_nodes import (DEFAULT_CUSTOM_COLOR, PORT_SOCKET_TYPES,
                                     SUBGRAPH_INPUT_TYPE, SUBGRAPH_OUTPUT_TYPE,
                                     CustomNodeDefinition, CustomProperty,
                                     SubgraphInputNode, SubgraphOutputNode,
                                     bindable_property_targets,
                                     build_node_from_blob,
                                     custom_property_from_target,
                                     definition_from_project,
                                     format_property_value,
                                     parse_property_value, sanitize_port_name,
                                     sanitize_property_key, unique_port_name,
                                     unique_property_key)
from core.nodes.property_link import sockets_compatible
from core.nodes.viewer import ViewerNode
from core.project import Project
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QDialog,
                             QDialogButtonBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMenu,
                             QMessageBox, QPushButton, QScrollArea, QSlider,
                             QSplitter, QTabWidget, QToolButton, QVBoxLayout,
                             QWidget)
from ui.node_graph.custom_node_ops import build_custom_node_definition
from ui.node_graph.view import NodeGraphView
from ui.widgets.properties import PropertiesPanel
from ui.widgets.viewport import ViewportWidget

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
    QDialog#CustomNodeDialog QTabWidget::pane {
        border: 1px solid #34343c;
        border-radius: 6px;
        top: -1px;
    }
    QDialog#CustomNodeDialog QTabBar::tab {
        background-color: #222228;
        color: #b8b8c0;
        border: 1px solid #34343c;
        border-bottom: none;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
        padding: 5px 12px;
        margin-right: 2px;
    }
    QDialog#CustomNodeDialog QTabBar::tab:selected {
        background-color: #2e2e36;
        color: #f0f0f4;
    }
    QDialog#CustomNodeDialog QSlider::groove:horizontal {
        height: 4px;
        background: #2e2e36;
        border-radius: 2px;
    }
    QDialog#CustomNodeDialog QSlider::handle:horizontal {
        background: #8ab4d8;
        width: 10px;
        margin: -5px 0;
        border-radius: 5px;
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
            "Ports and adjustable parameters can be refined after creating."
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
        self.resize(1280, 780)

        self._source = definition.copy()
        self._color: tuple[int, int, int] = self._source.color
        self._result: CustomNodeDefinition | None = None
        self._custom_properties: list[CustomProperty] = [
            spec.copy() for spec in self._source.properties
        ]
        self._preview_viewer_id: str = ""
        self._parameter_rows_dirty: bool = False

        self._project = _project_from_definition(self._source)
        self._history = HistoryStack(self._project)
        self._view = NodeGraphView(
            self._project,
            self._history,
            keybinds or KeybindStore(),
        )
        self._preview_viewer_id = self._add_preview_viewer()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"Custom Node — {self._source.name}")
        title.setObjectName("CustomNodeTitle")
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([820, 420])
        root.addWidget(splitter, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._project.subscribe(self._on_project_changed)
        self._view.scene.selectionChanged.connect(self._on_selection_changed)
        self._rebuild_port_rows()
        self._rebuild_parameter_rows()
        self._refresh_color_button()
        self._refresh_frame_label()

    # -- results -----------------------------------------------------------

    @property
    def definition(self) -> CustomNodeDefinition | None:
        return self._result

    # -- preview -----------------------------------------------------------

    def _add_preview_viewer(self) -> str:
        """Add a temporary Viewer so the inner graph can be previewed."""
        xs = [float(node.x) for node in self._project.nodes.values()]
        ys = [float(node.y) for node in self._project.nodes.values()]
        widths = [float(node.width) for node in self._project.nodes.values()]
        x = (max(
            (xs[index] + widths[index] for index in range(len(xs))),
            default=600.0,
        ) + 180.0)
        y = min(ys) if ys else 120.0

        viewer = ViewerNode()
        viewer.name = "Preview"
        viewer.x = x
        viewer.y = y
        node_id = "preview_viewer"
        while node_id in self._project.nodes:
            node_id = f"{node_id}_"
        self._project.add_node(viewer, node_id=node_id)
        self._project.set_active_viewer(node_id)
        return node_id

    def _on_preview_frame(self, value: int) -> None:
        self._project.set_frame(int(value))
        self._refresh_frame_label()

    def _refresh_frame_label(self) -> None:
        if not hasattr(self, "_frame_label"):
            return
        self._frame_label.setText(
            f"Frame {int(self._project.current_frame)} / {self._project.max_frame}"
        )

    # -- layout ------------------------------------------------------------

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._view, 3)

        preview = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(6, 4, 6, 6)
        preview_layout.setSpacing(4)

        self._viewport = ViewportWidget(self._project, self._history)
        self._viewport.setMinimumHeight(190)
        preview_layout.addWidget(self._viewport, 1)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self._frame_label = QLabel("Frame 0 / 0")
        self._frame_label.setMinimumWidth(110)
        controls.addWidget(self._frame_label)

        self._frame_slider = QSlider(Qt.Orientation.Horizontal)
        self._frame_slider.setRange(0, max(0, int(self._project.max_frame)))
        self._frame_slider.setValue(int(self._project.current_frame))
        self._frame_slider.valueChanged.connect(self._on_preview_frame)
        controls.addWidget(self._frame_slider, 1)

        refresh = QToolButton()
        refresh.setText("Refresh")
        refresh.clicked.connect(self._viewport.request_update)
        controls.addWidget(refresh)
        preview_layout.addLayout(controls)

        hint = QLabel(
            "A temporary Viewer node previews the inner graph. Wire any node "
            "into it while editing; Viewer nodes are preview-only and are "
            "never saved with the custom node."
        )
        hint.setStyleSheet("color: #7a7a84; font-size: 11px;")
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)

        layout.addWidget(preview, 2)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(360)
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

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_ports_tab(), "Ports")
        self._tabs.addTab(self._build_parameters_tab(), "Parameters")
        self._properties_panel = PropertiesPanel(self._project, self._history)
        self._tabs.addTab(self._properties_panel, "Node Properties")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)
        return panel

    def _build_ports_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)
        self._inputs_box = self._build_port_group(
            layout, "Inputs", lambda: self._add_terminal("in")
        )
        self._outputs_box = self._build_port_group(
            layout, "Outputs", lambda: self._add_terminal("out")
        )
        layout.addStretch(1)
        return page

    def _build_parameters_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        hint = QLabel(
            "Parameters are adjustable values on the custom node that drive a "
            "chosen property of an inner node. Edit them on the node itself "
            "after saving."
        )
        hint.setStyleSheet("color: #7a7a84; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._parameters_box = QVBoxLayout(content)
        self._parameters_box.setContentsMargins(0, 0, 0, 0)
        self._parameters_box.setSpacing(6)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        add_button = QPushButton("Add Parameter…")
        add_button.clicked.connect(self._add_parameter)
        layout.addWidget(add_button)
        self._parameters_page = page
        return page

    def _build_port_group(self, parent_layout: QVBoxLayout, title: str, on_add) -> QVBoxLayout:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(8, 4, 8, 8)
        group_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(110)
        scroll.setMaximumHeight(170)
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

    # -- selection / tabs --------------------------------------------------

    def _on_selection_changed(self) -> None:
        for item in self._view.scene.selectedItems():
            node_id = getattr(item, "node_id", None)
            if isinstance(node_id, str) and node_id in self._project.nodes:
                self._properties_panel.set_node(node_id)
                return

    def _on_tab_changed(self, index: int) -> None:
        if (
            self._tabs.widget(index) is getattr(self, "_parameters_page", None)
            and self._parameter_rows_dirty
        ):
            self._rebuild_parameter_rows()

    # -- parameters --------------------------------------------------------

    def _bindable_targets(self) -> list[tuple[str, str, object, object]]:
        """Return ``(node_id, key, node, prop)`` for bindable inner properties."""
        results: list[tuple[str, str, object, object]] = []
        for node_id, node in self._project.nodes.items():
            if node.node_type in (SUBGRAPH_INPUT_TYPE, SUBGRAPH_OUTPUT_TYPE):
                continue
            if node_id == self._preview_viewer_id:
                continue
            for key, prop in bindable_property_targets(node):
                results.append((str(node_id), key, node, prop))
        # type: ignore[attr-defined]
        results.sort(key=lambda item: (item[2].name, item[1]))
        return results

    def _other_parameter_keys(self, index: int) -> set[str]:
        return {
            spec.name
            for other, spec in enumerate(self._custom_properties)
            if other != index
        }

    def _rebuild_parameter_rows(self) -> None:
        self._parameter_rows_dirty = False
        _clear_layout(self._parameters_box)
        if not self._custom_properties:
            empty = QLabel("No parameters yet")
            empty.setStyleSheet("color: #6a6a74; font-size: 11px;")
            self._parameters_box.addWidget(empty)
            self._parameters_box.addStretch(1)
            return
        for index, spec in enumerate(self._custom_properties):
            self._parameters_box.addWidget(
                self._make_parameter_row(index, spec))
        self._parameters_box.addStretch(1)

    def _make_parameter_row(self, index: int, spec: CustomProperty) -> QWidget:
        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(4)
        name_edit = QLineEdit(spec.name)
        name_edit.setMinimumWidth(90)
        name_edit.setToolTip("Parameter key used on the custom node node")
        name_edit.editingFinished.connect(
            lambda i=index, edit=name_edit: self._on_parameter_rename(i, edit)
        )
        top.addWidget(name_edit, 1)
        remove = QToolButton()
        remove.setText("✕")
        remove.setToolTip("Remove this parameter")
        remove.clicked.connect(
            lambda _checked=False, i=index: self._remove_parameter(i)
        )
        top.addWidget(remove)
        outer.addLayout(top)

        combo = QComboBox()
        combo.addItem("(not bound)", None)
        for node_id, key, node, prop in self._bindable_targets():
            label = prop.label or key.replace(
                "_", " ").title()  # type: ignore[attr-defined]
            # type: ignore[attr-defined]
            combo.addItem(f"{node.name} · {label}", (node_id, key))
        combo.setCurrentIndex(
            max(0, _combo_index_for(combo, (spec.target_node_id, spec.target_key)))
        )
        combo.setToolTip("Inner node property this parameter drives")
        combo.currentIndexChanged.connect(
            lambda _i, box=combo, idx=index: self._on_parameter_target(
                idx, box)
        )
        outer.addWidget(combo)

        default_edit = QLineEdit(format_property_value(spec))
        default_edit.setToolTip(
            "Default value. Colors: 'R, G, B'. Toggles: true/false."
        )
        default_edit.editingFinished.connect(
            lambda i=index, edit=default_edit: self._on_parameter_default(
                i, edit)
        )
        outer.addWidget(default_edit)
        return row

    def _on_parameter_rename(self, index: int, edit: QLineEdit) -> None:
        if not (0 <= index < len(self._custom_properties)):
            return
        spec = self._custom_properties[index]
        key = sanitize_property_key(edit.text(), "parameter")
        unique = unique_property_key(key, self._other_parameter_keys(index))
        if unique != edit.text():
            edit.setText(unique)
        spec.name = unique

    def _on_parameter_target(self, index: int, combo: QComboBox) -> None:
        if not (0 <= index < len(self._custom_properties)):
            return
        data = combo.currentData()
        spec = self._custom_properties[index]
        if not (isinstance(data, tuple) and len(data) == 2):
            spec.target_node_id = ""
            spec.target_key = ""
            return
        node_id, key = str(data[0]), str(data[1])
        node = self._project.nodes.get(node_id)
        if node is None:
            return
        derived = custom_property_from_target(
            node, node_id, key, name=spec.name)
        if derived is None:
            return
        if not spec.name:
            derived.name = unique_property_key(
                derived.name, self._other_parameter_keys(index)
            )
        self._custom_properties[index] = derived
        # Rebuild on the next event-loop turn: the combo that emitted this
        # signal is about to be destroyed.
        QTimer.singleShot(0, self._rebuild_parameter_rows)

    def _on_parameter_default(self, index: int, edit: QLineEdit) -> None:
        if not (0 <= index < len(self._custom_properties)):
            return
        spec = self._custom_properties[index]
        spec.default = parse_property_value(spec, edit.text())
        edit.setText(format_property_value(spec))

    def _remove_parameter(self, index: int) -> None:
        if not (0 <= index < len(self._custom_properties)):
            return
        del self._custom_properties[index]
        self._rebuild_parameter_rows()

    def _add_parameter(self) -> None:
        targets = self._bindable_targets()
        if not targets:
            QMessageBox.information(
                self,
                "Add Parameter",
                "Add some nodes with editable properties to the custom node "
                "first, then bind a parameter to one of them.",
            )
            return
        menu = QMenu(self)
        for node_id, key, node, prop in targets:
            label = prop.label or key.replace(
                "_", " ").title()  # type: ignore[attr-defined]
            # type: ignore[attr-defined]
            action = menu.addAction(f"{node.name} · {label}")
            action.triggered.connect(
                lambda _checked=False, nid=node_id, k=key: self._create_parameter(
                    nid, k)
            )
        menu.exec(QCursor.pos())

    def _create_parameter(self, node_id: str, key: str) -> None:
        node = self._project.nodes.get(node_id)
        if node is None:
            return
        spec = custom_property_from_target(node, node_id, key)
        if spec is None:
            return
        spec.name = unique_property_key(
            spec.name, {item.name for item in self._custom_properties}
        )
        self._custom_properties.append(spec)
        self._rebuild_parameter_rows()

    # -- project observer --------------------------------------------------

    def _on_project_changed(self, event: object, data: object) -> None:
        from core.events import ObserverEvent

        if event in (ObserverEvent.NodeAdded, ObserverEvent.NodeRemoved):
            self._rebuild_port_rows()
            self._parameter_rows_dirty = True
            self._refresh_frame_label()
            if self._tabs.currentWidget() is getattr(self, "_parameters_page", None):
                self._rebuild_parameter_rows()

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
        # Viewer nodes are preview aids only: a Viewer is a screen endpoint,
        # so it can never be part of a reusable definition.
        self._strip_viewers()
        # Drop parameters whose target node/socket disappeared while editing.
        self._custom_properties = [
            spec
            for spec in self._custom_properties
            if spec.target_node_id in self._project.nodes
            and spec.target_key
            in self._project.nodes[spec.target_node_id].properties
        ]
        self._result = definition_from_project(
            self._project,
            self._name_edit.text().strip() or self._source.name,
            description=self._desc_edit.text().strip(),
            color=self._color,
            properties=self._custom_properties,
        )
        self.accept()

    def _strip_viewers(self) -> None:
        for node_id, node in list(self._project.nodes.items()):
            if node.node_type == "Viewer":
                self._project.remove_node(node_id)
        self._project.set_active_viewer(None)
        self._preview_viewer_id = ""

    def _normalize_terminal_names(self) -> None:
        taken: set[str] = set()
        for terminal_id, node in self._terminals("in") + self._terminals("out"):
            name = unique_port_name(sanitize_port_name(
                str(node.name), "Port"), taken)
            taken.add(name)
            node.name = name
            self._refresh_item(terminal_id)

    # -- teardown ----------------------------------------------------------

    def done(self, result: int) -> None:
        # The graph view, viewport, and properties panel all subscribe to the
        # project; detach every observer so the dialog's widgets can be
        # garbage collected. The viewport also owns a worker thread.
        try:
            self._project.unsubscribe(self._on_project_changed)
            self._view.project.unsubscribe(self._view.on_project_changed)
            self._viewport.project.unsubscribe(
                self._viewport.on_project_changed)
            self._properties_panel.project.unsubscribe(
                self._properties_panel.on_project_changed
            )
            self._viewport.shutdown()
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


def _combo_index_for(combo: QComboBox, data: object) -> int:
    """Return the index of the combo entry whose user data equals ``data``."""
    for index in range(combo.count()):
        if combo.itemData(index) == data:
            return index
    return -1


__all__ = ["CustomNodeCreateDialog", "CustomNodeEditorDialog"]
