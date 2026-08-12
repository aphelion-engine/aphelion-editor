"""Tab-activated fuzzy search palette for creating nodes."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.keybinds import KeyAction, KeybindStore
from config.theme import NODE_SEARCH_STYLE
from core.nodes import NodeInfo, global_node_registry
from ui.icons import make_dot_icon
from ui.node_graph.constants import MENU_ICON_SIZE_PX

NodeChosenCallback = Callable[[str, str], None]


class NodeSearchPalette(QFrame):
    """Floating search UI: type to filter, Enter to create, Esc to close."""

    def __init__(
        self,
        parent: QWidget,
        *,
        on_chosen: NodeChosenCallback,
        keybinds: KeybindStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_chosen = on_chosen
        self._keybinds = keybinds or KeybindStore()
        self.setObjectName("NodeSearchPalette")
        self.setStyleSheet(NODE_SEARCH_STYLE)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel(
            self._keybinds.tooltip("Add Node", KeyAction.SEARCH_NODE)
        )
        title.setObjectName("NodeSearchTitle")
        layout.addWidget(title)

        self._search = QLineEdit()
        self._search.setObjectName("NodeSearchField")
        self._search.setPlaceholderText("Search nodes…")
        self._search.textChanged.connect(self._rebuild_list)
        self._search.returnPressed.connect(self._activate_current)
        self._search.installEventFilter(self)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setObjectName("NodeSearchList")
        self._list.itemActivated.connect(self._activate_item)
        self._list.installEventFilter(self)
        layout.addWidget(self._list)

        self.hide()
        self._all_entries: list[NodeInfo] = []

    def open_palette(self) -> None:
        """Show the palette centered over the parent and focus the search field."""
        self._all_entries = sorted(
            global_node_registry.get_all_nodes().values(),
            key=lambda info: (info.category, info.name),
        )
        self._search.clear()
        self._rebuild_list("")
        self._reposition()
        self.show()
        self.raise_()
        self._search.setFocus(Qt.FocusReason.PopupFocusReason)

    def close_palette(self) -> None:
        """Hide the palette and return focus to the parent."""
        self.hide()
        parent = self.parentWidget()
        if parent is not None:
            parent.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if watched is None or event is None:
            return super().eventFilter(watched, event)
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        if not isinstance(event, QKeyEvent):
            return super().eventFilter(watched, event)

        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_palette()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate_current()
            return True
        if key == Qt.Key.Key_Down:
            row = min(self._list.currentRow() + 1, self._list.count() - 1)
            self._list.setCurrentRow(max(0, row))
            return True
        if key == Qt.Key.Key_Up:
            self._list.setCurrentRow(max(self._list.currentRow() - 1, 0))
            return True
        if key == Qt.Key.Key_Tab:
            return True
        return super().eventFilter(watched, event)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(360, max(280, parent.width() - 40))
        height = min(320, max(220, parent.height() // 2))
        self.setFixedSize(width, height)
        x = max(0, (parent.width() - width) // 2)
        y = max(0, (parent.height() - height) // 3)
        self.move(x, y)

    def _rebuild_list(self, query: str) -> None:
        self._list.clear()
        needle = query.strip().lower()
        for info in self._all_entries:
            haystack = f"{info.name} {info.category} {info.description}".lower()
            if needle and needle not in haystack:
                continue
            item = QListWidgetItem(
                make_dot_icon(
                    global_node_registry.resolve_color(info.category, info.name),
                    size=MENU_ICON_SIZE_PX,
                ),
                f"{info.name}  ·  {info.category}",
            )
            item.setData(Qt.ItemDataRole.UserRole, (info.name, info.category))
            item.setToolTip(info.description)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _activate_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        name, category = payload
        if not isinstance(name, str) or not isinstance(category, str):
            return
        self.close_palette()
        self._on_chosen(name, category)

    def _activate_current(self) -> None:
        self._activate_item(self._list.currentItem())
