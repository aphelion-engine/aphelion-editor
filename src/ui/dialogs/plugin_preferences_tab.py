"""Preferences tab for discovering, enabling, and reloading plugins."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app_io.plugin_loader import PluginLoader, PluginRecord, plugin_directories
from core.preferences.models import PluginSettings
from utils.paths import ensure_directory


class PluginPreferencesPage(QWidget):
    """Discovery flags, enablement list, folder shortcuts, and reload."""

    plugins_reloaded = pyqtSignal(int)

    def __init__(
        self,
        settings: PluginSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._checkboxes: dict[str, QCheckBox] = {}
        self.did_reload = False
        self._status = QLabel()
        self._status.setObjectName("PreferencesStatus")
        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._build()
        self._rebuild_list()

    def collect_settings(self) -> PluginSettings:
        """Return discovery flags and disabled keys from the current controls."""
        disabled: list[str] = []
        for key, checkbox in self._checkboxes.items():
            if not checkbox.isChecked():
                disabled.append(key)
        return PluginSettings(
            load_bundled=self._load_bundled.isChecked(),
            load_user=self._load_user.isChecked(),
            load_entry_points=self._load_entry_points.isChecked(),
            disabled_plugin_keys=sorted(disabled),
        )

    def _build(self) -> None:
        """Assemble discovery, list, and folder groups."""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._build_discovery_group())
        root.addWidget(self._build_installed_group(), 1)
        root.addWidget(self._build_folders_group())

    def _build_discovery_group(self) -> QGroupBox:
        """Return checkboxes that control which plugin origins are imported."""
        group = QGroupBox("Discovery")
        group.setObjectName("PreferencesGroup")
        layout = QVBoxLayout(group)
        self._load_bundled = QCheckBox("Load bundled plugins")
        self._load_bundled.setChecked(self._settings.load_bundled)
        self._load_user = QCheckBox("Load user plugins")
        self._load_user.setChecked(self._settings.load_user)
        self._load_entry_points = QCheckBox("Load installed packages (entry points)")
        self._load_entry_points.setChecked(self._settings.load_entry_points)
        layout.addWidget(self._load_bundled)
        layout.addWidget(self._load_user)
        layout.addWidget(self._load_entry_points)
        hint = QLabel("Changes apply when you reload plugins or click Apply.")
        hint.setObjectName("PreferencesHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return group

    def _build_installed_group(self) -> QGroupBox:
        """Return the scrollable enable/disable list."""
        group = QGroupBox("Installed")
        group.setObjectName("PreferencesGroup")
        layout = QVBoxLayout(group)
        layout.addWidget(self._status)
        scroll = QScrollArea()
        scroll.setObjectName("PreferencesScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._list_host)
        layout.addWidget(scroll, 1)
        hint = QLabel(
            "Unchecked plugins stay discovered but are omitted from Add Node. "
            "Reload applies to new nodes; reopen the project to refresh "
            "existing plugin nodes."
        )
        hint.setObjectName("PreferencesHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return group

    def _build_folders_group(self) -> QGroupBox:
        """Return folder paths and reload / open-folder actions."""
        group = QGroupBox("Folders")
        group.setObjectName("PreferencesGroup")
        layout = QVBoxLayout(group)
        bundled, user = plugin_directories()
        layout.addWidget(self._path_label("Bundled", bundled))
        layout.addWidget(self._path_label("User", user))
        layout.addLayout(self._folder_buttons(bundled, user))
        reload_btn = QPushButton("Reload plugins")
        reload_btn.setObjectName("PreferencesPrimaryButton")
        reload_btn.clicked.connect(self._on_reload)
        layout.addWidget(reload_btn)
        return group

    def _path_label(self, title: str, path: Path) -> QLabel:
        """Return a muted path caption."""
        label = QLabel(f"{title}: {path}")
        label.setObjectName("PreferencesPath")
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        return label

    def _folder_buttons(self, bundled: Path, user: Path) -> QHBoxLayout:
        """Return Open bundled / Open user folder buttons."""
        row = QHBoxLayout()
        bundled_btn = QPushButton("Open bundled folder")
        bundled_btn.setObjectName("PreferencesSecondaryButton")
        bundled_btn.clicked.connect(lambda: _open_directory(bundled))
        user_btn = QPushButton("Open user folder")
        user_btn.setObjectName("PreferencesSecondaryButton")
        user_btn.clicked.connect(lambda: _open_directory(user))
        row.addWidget(bundled_btn)
        row.addWidget(user_btn)
        row.addStretch(1)
        return row

    def _on_reload(self) -> None:
        """Re-import plugin files using the current checkbox state."""
        settings = self.collect_settings()
        self._settings = settings
        self.did_reload = True
        count = PluginLoader.reload(settings)
        self._rebuild_list()
        self.plugins_reloaded.emit(count)

    def _rebuild_list(self) -> None:
        """Refresh the enablement list from ``PluginLoader.listed_plugins``."""
        _clear_layout(self._list_layout)
        self._checkboxes = {}
        records = PluginLoader.listed_plugins()
        if not records:
            empty = QLabel("No plugins discovered.")
            empty.setObjectName("PreferencesHint")
            self._list_layout.addWidget(empty)
        for record in records:
            self._list_layout.addWidget(self._record_row(record))
        self._list_layout.addStretch(1)
        self._update_status(records)

    def _record_row(self, record: PluginRecord) -> QFrame:
        """Return one checkable plugin row."""
        row = QFrame()
        row.setObjectName("PreferencesRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        checkbox = QCheckBox(record.name)
        checkbox.setChecked(record.enabled)
        checkbox.setToolTip(record.description or record.name)
        self._checkboxes[record.key] = checkbox
        meta = QLabel(
            f"{record.kind}  ·  {record.category}  ·  {record.source}"
            + (f"  ·  {record.author}" if record.author else "")
        )
        meta.setObjectName("PreferencesHint")
        meta.setWordWrap(True)
        layout.addWidget(checkbox)
        layout.addWidget(meta)
        if record.description:
            desc = QLabel(record.description)
            desc.setObjectName("PreferencesHint")
            desc.setWordWrap(True)
            layout.addWidget(desc)
        return row

    def _update_status(self, records: tuple[PluginRecord, ...]) -> None:
        """Show loaded vs disabled counts."""
        loaded = sum(1 for record in records if record.enabled)
        disabled = len(records) - loaded
        self._status.setText(
            f"{loaded} plugin(s) loaded, {disabled} disabled, "
            f"{len(records)} discovered."
        )


def _open_directory(path: Path) -> None:
    """Open ``path`` in the system file manager, creating it if needed."""
    ensure_directory(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _clear_layout(layout: QVBoxLayout) -> None:
    """Delete every widget currently in ``layout``."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
