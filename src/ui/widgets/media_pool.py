"""Media pool panel listing project video sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.theme import MEDIA_POOL_STYLE
from core.events import ObserverEvent
from core.nodes.video_input import VideoInputNode
from core.project import Project


class MediaPoolWidget(QWidget):
    """Lists ``Video Input`` nodes and focuses them in the graph on selection."""

    media_selected = pyqtSignal(str)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.setObjectName("MediaPoolWidget")
        self.setStyleSheet(MEDIA_POOL_STYLE)
        self.project = project
        self._build_ui()
        self.project.subscribe(self._on_project_changed)
        self.refresh()

    def set_project(self, project: Project) -> None:
        """Retarget the pool at a newly loaded document."""
        self.project.unsubscribe(self._on_project_changed)
        self.project = project
        self.project.subscribe(self._on_project_changed)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Sources")
        title.setObjectName("MediaPoolTitle")
        header.addWidget(title)
        header.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("MediaPoolRefreshButton")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)

        self._empty_label = QLabel("No media sources in this project.")
        self._empty_label.setObjectName("MediaPoolEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty_label)

        self._list = QListWidget()
        self._list.setObjectName("MediaPoolList")
        self._list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self._list, 1)

    def refresh(self) -> None:
        """Rebuild the media list from current ``Video Input`` nodes."""
        self._list.clear()
        entries: list[tuple[str, str, str]] = []
        for node_id, node in self.project.nodes.items():
            if not isinstance(node, VideoInputNode):
                continue
            prop = node.get_property("file_path")
            file_path = str(prop.value if prop is not None else "")
            label = node.name
            detail = Path(file_path).name if file_path else "No file"
            entries.append((node_id, label, detail))

        has_items = bool(entries)
        self._empty_label.setVisible(not has_items)
        self._list.setVisible(has_items)

        for node_id, label, detail in sorted(entries, key=lambda row: row[1].lower()):
            item = QListWidgetItem(f"{label}\n{detail}")
            item.setData(Qt.ItemDataRole.UserRole, node_id)
            item.setToolTip(detail)
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(node_id, str):
            self.media_selected.emit(node_id)

    def _on_project_changed(self, event: ObserverEvent, _data: Any) -> None:
        if event in {
            ObserverEvent.NodeAdded,
            ObserverEvent.NodeRemoved,
            ObserverEvent.NodeModified,
        }:
            self.refresh()

    def shutdown(self) -> None:
        """Unsubscribe from project events."""
        self.project.unsubscribe(self._on_project_changed)
