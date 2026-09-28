"""AI settings page.

Used both as the standalone "AI Settings…" dialog body and as the AI tab in
Preferences. Everything here writes to :class:`~ai.settings.AISettingsStore`
and :class:`~ai.credentials.CredentialStore`; API keys are never displayed and
never leave the credential vault.
"""

from __future__ import annotations

from typing import Any

from ai.credentials import CredentialStore, mask_secret
from ai.providers.registry import KIND_LABELS, supported_kinds
from ai.settings import AISettings, AISettingsStore, ProviderConfig
from ai.types import (ALL_PERMISSIONS, PERMISSION_LABELS, AgentMode, EditPolicy,
                      Permission)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton,
                             QScrollArea, QSpinBox, QVBoxLayout, QWidget)


class AISettingsWidget(QWidget):
    """Editable view over the AI settings document."""

    settings_changed = pyqtSignal()

    def __init__(
        self,
        settings_store: AISettingsStore,
        credentials: CredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = settings_store
        self._credentials = credentials or CredentialStore()
        self._settings: AISettings = settings_store.settings
        self._current_provider: ProviderConfig | None = None
        self._suppress = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_enable_group())
        layout.addWidget(self._build_defaults_group())
        layout.addWidget(self._build_providers_group())
        layout.addWidget(self._build_permissions_group())
        layout.addWidget(self._build_advanced_group())
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._reload()
        self._suppress = False

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def _build_enable_group(self) -> QGroupBox:
        group = QGroupBox("AI Assistant")
        layout = QVBoxLayout(group)
        self._enabled = QCheckBox("Enable the AI assistant")
        self._enabled.setToolTip(
            "Off by default. Nothing about your project is read, sent, or "
            "logged until you enable the assistant and use a provider."
        )
        self._enabled.toggled.connect(self._on_enabled_toggled)
        layout.addWidget(self._enabled)

        self._privacy = QLabel(
            "Aphelion never sends project data anywhere on its own. Data leaves "
            "this machine only when you use a cloud provider, and only the "
            "context permitted below."
        )
        self._privacy.setWordWrap(True)
        self._privacy.setObjectName("AIHint")
        layout.addWidget(self._privacy)
        return group

    def _build_defaults_group(self) -> QGroupBox:
        group = QGroupBox("Agent behaviour")
        form = QFormLayout(group)

        self._provider_combo = QComboBox()
        self._provider_combo.currentIndexChanged.connect(self._on_default_provider)
        form.addRow("Default provider", self._provider_combo)

        model_row = QHBoxLayout()
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("Model id, e.g. meta-llama/Llama-3.1-8B-Instruct")
        self._model_edit.editingFinished.connect(self._on_model_edited)
        model_row.addWidget(self._model_edit, 1)
        self._test_button = QPushButton("Test Connection")
        self._test_button.clicked.connect(self._on_test_connection)
        model_row.addWidget(self._test_button)
        form.addRow("Default model", _wrap(model_row))

        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._test_result.setObjectName("AIHint")
        form.addRow("", self._test_result)

        self._mode_combo = QComboBox()
        for mode in AgentMode:
            self._mode_combo.addItem(
                {
                    AgentMode.ASK: "Ask — inspect and answer only",
                    AgentMode.ASSIST: "Assist — propose edits, confirm first",
                    AgentMode.AGENT: "Agent — apply edits directly",
                }[mode],
                mode.value,
            )
        self._mode_combo.currentIndexChanged.connect(
            lambda _index: self._touch(self._settings.__setattr__("agent_mode", self._selected_mode()))
        )
        form.addRow("Agent mode", self._mode_combo)

        self._policy_combo = QComboBox()
        for policy in EditPolicy:
            self._policy_combo.addItem(policy.label, policy.value)
        self._policy_combo.currentIndexChanged.connect(
            lambda _index: self._touch(self._settings.__setattr__("edit_policy", self._selected_policy()))
        )
        form.addRow("Agent edit mode", self._policy_combo)

        self._highlight = QCheckBox("Highlight nodes the assistant changes")
        self._highlight.toggled.connect(
            lambda value: self._touch(self._settings.__setattr__("highlight_changes", bool(value)))
        )
        form.addRow(self._highlight)
        return group

    def _build_providers_group(self) -> QGroupBox:
        group = QGroupBox("Providers")
        layout = QHBoxLayout(group)

        left = QVBoxLayout()
        self._provider_list = QListWidget()
        self._provider_list.setMaximumWidth(220)
        self._provider_list.currentRowChanged.connect(self._on_provider_selected)
        left.addWidget(self._provider_list, 1)
        buttons = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._on_add_provider)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._on_remove_provider)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        left.addLayout(buttons)
        layout.addLayout(left)

        right = QGroupBox("Configuration")
        form = QFormLayout(right)

        self._p_label = QLineEdit()
        self._p_label.editingFinished.connect(self._on_provider_field_changed)
        form.addRow("Name", self._p_label)

        self._p_kind = QComboBox()
        for kind in supported_kinds():
            self._p_kind.addItem(KIND_LABELS.get(kind, kind), kind)
        self._p_kind.currentIndexChanged.connect(self._on_provider_field_changed)
        form.addRow("API type", self._p_kind)

        self._p_base = QLineEdit()
        self._p_base.setPlaceholderText("https://api.example.com/v1")
        self._p_base.editingFinished.connect(self._on_provider_field_changed)
        form.addRow("Base URL", self._p_base)

        key_row = QHBoxLayout()
        self._p_key = QLineEdit()
        self._p_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._p_key.setPlaceholderText("(not set)")
        self._p_key.editingFinished.connect(self._on_provider_field_changed)
        key_row.addWidget(self._p_key, 1)
        clear_key = QPushButton("Clear")
        clear_key.setToolTip("Delete the stored key for this provider.")
        clear_key.clicked.connect(self._on_clear_key)
        key_row.addWidget(clear_key)
        form.addRow("API key", _wrap(key_row))

        self._p_key_state = QLabel("")
        self._p_key_state.setObjectName("AIHint")
        form.addRow("", self._p_key_state)

        self._p_model = QLineEdit()
        self._p_model.editingFinished.connect(self._on_provider_field_changed)
        form.addRow("Model", self._p_model)

        self._p_context = QSpinBox()
        self._p_context.setRange(0, 2_000_000)
        self._p_context.setSingleStep(1024)
        self._p_context.setSpecialValueText("Auto")
        self._p_context.valueChanged.connect(self._on_provider_field_changed)
        form.addRow("Context length", self._p_context)

        self._p_tools = QComboBox()
        self._p_tools.addItem("Auto-detect", None)
        self._p_tools.addItem("Yes", True)
        self._p_tools.addItem("No", False)
        self._p_tools.currentIndexChanged.connect(self._on_provider_field_changed)
        form.addRow("Supports tools", self._p_tools)

        self._p_vision = QComboBox()
        self._p_vision.addItem("Auto-detect", None)
        self._p_vision.addItem("Yes", True)
        self._p_vision.addItem("No", False)
        self._p_vision.currentIndexChanged.connect(self._on_provider_field_changed)
        form.addRow("Supports vision", self._p_vision)

        self._p_local = QCheckBox("Runs locally (no data leaves this machine)")
        self._p_local.toggled.connect(self._on_provider_field_changed)
        form.addRow(self._p_local)

        self._p_enabled = QCheckBox("Enabled")
        self._p_enabled.toggled.connect(self._on_provider_field_changed)
        form.addRow(self._p_enabled)

        self._p_note = QLabel("")
        self._p_note.setWordWrap(True)
        self._p_note.setObjectName("AIHint")
        form.addRow("", self._p_note)

        layout.addWidget(right, 1)
        return group

    def _build_permissions_group(self) -> QGroupBox:
        group = QGroupBox("Context permissions")
        layout = QVBoxLayout(group)
        hint = QLabel(
            "Choose what the assistant may read. Anything unchecked is refused "
            "by the tool layer, and the assistant is told why."
        )
        hint.setWordWrap(True)
        hint.setObjectName("AIHint")
        layout.addWidget(hint)

        self._permission_boxes: dict[Permission, QCheckBox] = {}
        for permission in ALL_PERMISSIONS:
            box = QCheckBox(PERMISSION_LABELS[permission])
            box.toggled.connect(
                lambda value, perm=permission: self._on_permission_toggled(perm, value)
            )
            layout.addWidget(box)
            self._permission_boxes[permission] = box
        return group

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("Advanced")
        form = QFormLayout(group)

        self._steps = QSpinBox()
        self._steps.setRange(1, 64)
        self._steps.valueChanged.connect(
            lambda value: self._touch(self._settings.__setattr__("max_agent_steps", int(value)))
        )
        form.addRow("Maximum agent steps", self._steps)

        self._timeout = QSpinBox()
        self._timeout.setRange(5, 900)
        self._timeout.setSuffix(" s")
        self._timeout.valueChanged.connect(
            lambda value: self._touch(
                self._settings.__setattr__("request_timeout_seconds", float(value))
            )
        )
        form.addRow("Request timeout", self._timeout)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(128, 32768)
        self._max_tokens.setSingleStep(256)
        self._max_tokens.valueChanged.connect(
            lambda value: self._touch(self._settings.__setattr__("max_output_tokens", int(value)))
        )
        form.addRow("Maximum reply tokens", self._max_tokens)

        self._stream = QCheckBox("Stream responses")
        self._stream.toggled.connect(
            lambda value: self._touch(self._settings.__setattr__("stream", bool(value)))
        )
        form.addRow(self._stream)

        self._save_convos = QCheckBox("Save AI conversations with the project")
        self._save_convos.setToolTip(
            "Conversations are stored outside the .aph file, under userdata, so "
            "project saves stay small."
        )
        self._save_convos.toggled.connect(
            lambda value: self._touch(self._settings.__setattr__("save_conversations", bool(value)))
        )
        form.addRow(self._save_convos)

        self._verbose = QCheckBox("Verbose AI logging")
        self._verbose.setToolTip(
            "Log provider, model, duration, tool names, and status to the "
            "application log. API keys are never logged."
        )
        self._verbose.toggled.connect(
            lambda value: self._touch(self._settings.__setattr__("verbose_logging", bool(value)))
        )
        form.addRow(self._verbose)

        self._vault_state = QLabel("")
        self._vault_state.setWordWrap(True)
        self._vault_state.setObjectName("AIHint")
        form.addRow("", self._vault_state)
        return group

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        self._suppress = True
        settings = self._settings
        self._enabled.setChecked(settings.enabled)

        self._provider_combo.clear()
        self._provider_combo.addItem("— none —", "")
        for config in settings.providers:
            suffix = " [LOCAL]" if config.is_local else ""
            self._provider_combo.addItem(f"{config.label}{suffix}", config.provider_id)
        index = self._provider_combo.findData(settings.default_provider_id)
        self._provider_combo.setCurrentIndex(max(0, index))

        active = settings.active_provider()
        self._model_edit.setText(active.model if active else "")

        mode_index = self._mode_combo.findData(settings.agent_mode.value)
        self._mode_combo.setCurrentIndex(max(0, mode_index))
        policy_index = self._policy_combo.findData(settings.edit_policy.value)
        self._policy_combo.setCurrentIndex(max(0, policy_index))
        self._highlight.setChecked(settings.highlight_changes)

        self._steps.setValue(int(settings.max_agent_steps))
        self._timeout.setValue(int(settings.request_timeout_seconds))
        self._max_tokens.setValue(int(settings.max_output_tokens))
        self._stream.setChecked(settings.stream)
        self._save_convos.setChecked(settings.save_conversations)
        self._verbose.setChecked(settings.verbose_logging)

        for permission, box in self._permission_boxes.items():
            box.setChecked(settings.permissions.allows(permission))

        self._reload_provider_list()
        self._vault_state.setText(
            "Credentials are encrypted at rest"
            + (" and bound to your Windows user account."
               if self._credentials.usable() else "; secure storage is unavailable on this system.")
        )
        self._suppress = False
        self._update_enabled_state()

    def _reload_provider_list(self) -> None:
        self._provider_list.blockSignals(True)
        self._provider_list.clear()
        for config in self._settings.providers:
            scope = "LOCAL" if config.is_local else "CLOUD"
            item = QListWidgetItem(f"{config.label}  ·  {scope}")
            item.setData(Qt.ItemDataRole.UserRole, config.provider_id)
            self._provider_list.addItem(item)
        self._provider_list.blockSignals(False)
        if self._provider_list.count():
            self._provider_list.setCurrentRow(0)
        else:
            self._current_provider = None
            self._set_provider_form_enabled(False)

    def _update_enabled_state(self) -> None:
        enabled = self._enabled.isChecked()
        for widget in (
            self._provider_combo,
            self._model_edit,
            self._test_button,
            self._mode_combo,
            self._policy_combo,
            self._provider_list,
            self._steps,
            self._timeout,
            self._max_tokens,
        ):
            widget.setEnabled(enabled)
        self._privacy.setVisible(not enabled)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _touch(self, *_args: Any) -> None:
        if self._suppress:
            return
        self.settings_changed.emit()

    def _selected_mode(self) -> AgentMode:
        value = self._mode_combo.currentData()
        try:
            return AgentMode(value)
        except (ValueError, TypeError):
            return AgentMode.ASSIST

    def _selected_policy(self) -> EditPolicy:
        value = self._policy_combo.currentData()
        try:
            return EditPolicy(value)
        except (ValueError, TypeError):
            return EditPolicy.ASK_BEFORE_CHANGES

    def _on_enabled_toggled(self, checked: bool) -> None:
        self._settings.enabled = bool(checked)
        self._update_enabled_state()
        self._touch()

    def _on_default_provider(self, _index: int) -> None:
        if self._suppress:
            return
        self._settings.default_provider_id = str(self._provider_combo.currentData() or "")
        active = self._settings.active_provider()
        self._model_edit.setText(active.model if active else "")
        self._touch()

    def _on_model_edited(self) -> None:
        if self._suppress:
            return
        config = self._settings.active_provider()
        if config is None:
            return
        config.model = self._model_edit.text().strip()
        self._touch()
        self._reload_provider_list()

    def _on_permission_toggled(self, permission: Permission, value: bool) -> None:
        if self._suppress:
            return
        self._settings.permissions = self._settings.permissions.with_permission(
            permission, bool(value)
        )
        self._touch()

    # -- provider list ---------------------------------------------------

    def _on_provider_selected(self, row: int) -> None:
        item = self._provider_list.item(row) if row >= 0 else None
        provider_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        config = self._settings.provider(str(provider_id)) if provider_id else None
        self._current_provider = config
        if config is None:
            self._set_provider_form_enabled(False)
            return
        self._set_provider_form_enabled(True)
        self._suppress = True
        self._p_label.setText(config.label)
        kind_index = self._p_kind.findData(config.kind)
        self._p_kind.setCurrentIndex(max(0, kind_index))
        self._p_base.setText(config.base_url)
        self._p_model.setText(config.model)
        self._p_context.setValue(int(config.context_length))
        self._p_tools.setCurrentIndex(
            0 if config.supports_tools is None else (1 if config.supports_tools else 2)
        )
        self._p_vision.setCurrentIndex(
            0 if config.supports_vision is None else (1 if config.supports_vision else 2)
        )
        self._p_local.setChecked(config.is_local)
        self._p_enabled.setChecked(config.enabled)
        self._p_note.setText(config.note)
        self._p_key.clear()
        self._p_key.setPlaceholderText(
            self._credentials.describe(config.credential_key)
            if config.credential_key
            else "(not required)"
        )
        self._p_key_state.setText(
            f"Stored: {self._credentials.describe(config.credential_key)}"
            if config.credential_key and self._credentials.has(config.credential_key)
            else "No key stored for this provider."
        )
        self._suppress = False

    def _set_provider_form_enabled(self, enabled: bool) -> None:
        for widget in (
            self._p_label,
            self._p_kind,
            self._p_base,
            self._p_key,
            self._p_model,
            self._p_context,
            self._p_tools,
            self._p_vision,
            self._p_local,
            self._p_enabled,
        ):
            widget.setEnabled(enabled)

    def _on_provider_field_changed(self, *_args: Any) -> None:
        if self._suppress or self._current_provider is None:
            return
        config = self._current_provider
        config.label = self._p_label.text().strip() or config.label
        config.kind = str(self._p_kind.currentData() or config.kind)
        config.base_url = self._p_base.text().strip()
        config.model = self._p_model.text().strip()
        config.context_length = int(self._p_context.value())
        config.supports_tools = self._p_tools.currentData()
        config.supports_vision = self._p_vision.currentData()
        config.is_local = self._p_local.isChecked()
        config.enabled = self._p_enabled.isChecked()
        secret = self._p_key.text()
        if secret:
            # Store immediately; the field is cleared so the secret is never
            # held in a widget longer than necessary.
            self._credentials.set(config.credential_key, secret)
            self._p_key.clear()
            self._p_key_state.setText(
                f"Stored: {self._credentials.describe(config.credential_key)}"
            )
        self._touch()

    def _on_clear_key(self) -> None:
        if self._current_provider is None:
            return
        self._credentials.delete(self._current_provider.credential_key)
        self._p_key_state.setText("Key deleted.")
        self._p_key.setPlaceholderText("(not set)")

    def _on_add_provider(self) -> None:
        existing = {config.provider_id for config in self._settings.providers}
        index = 1
        while f"custom{index}" in existing:
            index += 1
        provider_id = f"custom{index}" if index > 1 else "custom"
        config = ProviderConfig(
            provider_id=provider_id,
            label=f"Custom provider {index}",
            kind="openai_compatible",
            base_url="",
            model="",
            credential_ref=f"ai.{provider_id}",
        )
        self._settings.providers.append(config)
        self._reload_provider_list()
        for row in range(self._provider_list.count()):
            item = self._provider_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == provider_id:
                self._provider_list.setCurrentRow(row)
                break
        self._touch()

    def _on_remove_provider(self) -> None:
        if self._current_provider is None:
            return
        provider_id = self._current_provider.provider_id
        if len(self._settings.providers) <= 1:
            QMessageBox.information(
                self, "AI Providers", "At least one provider entry must remain."
            )
            return
        self._settings.remove_provider(provider_id)
        self._current_provider = None
        self._reload_provider_list()
        self._touch()

    def _on_test_connection(self) -> None:
        config = self._settings.active_provider()
        if config is None:
            self._test_result.setText("No provider is enabled.")
            return
        self._test_result.setText("Testing…")
        self.commit(save=False)
        from ai.providers.registry import create_provider

        try:
            provider = create_provider(
                config,
                credentials=self._credentials,
                timeout=min(30.0, float(self._settings.request_timeout_seconds)),
            )
            result = provider.test_connection()
        except Exception as exc:  # noqa: BLE001 - a test must never crash the UI
            self._test_result.setText(f"✕ {type(exc).__name__}: {exc}")
            return
        prefix = "✓" if result.ok else "✕"
        self._test_result.setText(f"{prefix} {result.message}")

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def commit(self, *, save: bool = True) -> None:
        """Push the in-memory settings into the store (and optionally to disk)."""
        self._store.settings = self._settings
        if save:
            try:
                self._store.save()
            except OSError as exc:  # pragma: no cover - filesystem dependent
                QMessageBox.warning(
                    self, "AI Settings", f"Could not save AI settings: {exc}"
                )
        self.settings_changed.emit()

    def settings(self) -> AISettings:
        return self._settings


def _wrap(layout: Any) -> QWidget:
    widget = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    widget.setLayout(layout)
    return widget


__all__ = ["AISettingsWidget", "mask_secret"]
