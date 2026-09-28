"""AI settings: provider configuration, agent defaults, and persistence.

These live in their own ``userdata/ai_settings.json`` rather than inside the
editor preferences document, because the shape is more volatile than editor
preferences and because a user who never enables the assistant should never
have an AI section written to their preferences file.

Secrets are *not* here. :class:`ProviderConfig` only references a credential
by name; :mod:`ai.credentials` owns the encrypted values.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai import AI_SETTINGS_VERSION
from ai.permissions import PermissionPolicy
from ai.types import (AgentMode, EditPolicy, ModelInfo, ProviderCapabilities)
from utils.logging_setup import get_logger
from utils.paths import app_data_path, ensure_directory

_LOG = get_logger("ai.settings")

AI_SETTINGS_FILENAME: str = "ai_settings.json"


#: Provider implementation kinds understood by :mod:`ai.providers.registry`.
KIND_HUGGINGFACE = "huggingface"
KIND_OPENAI_COMPATIBLE = "openai_compatible"
KIND_OLLAMA = "ollama"
KIND_ANTHROPIC = "anthropic"
KIND_GOOGLE = "google"


@dataclass
class ProviderConfig:
    """One configured provider entry."""

    provider_id: str
    label: str
    kind: str = KIND_OPENAI_COMPATIBLE
    base_url: str = ""
    model: str = ""
    #: Credential reference (never the secret itself).
    credential_ref: str = ""
    is_local: bool = False
    enabled: bool = False
    #: ``None`` means "ask the provider"; ``True``/``False`` override detection.
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    context_length: int = 0
    extra_headers: dict[str, str] = field(default_factory=dict)
    #: Free-form notes shown in settings (e.g. "run `ollama serve` first").
    note: str = ""

    # ------------------------------------------------------------------
    # Derived
    # ------------------------------------------------------------------

    @property
    def scope(self) -> str:
        """``LOCAL`` or ``CLOUD`` for the UI badge."""
        return "LOCAL" if self.is_local else "CLOUD"

    @property
    def credential_key(self) -> str:
        return self.credential_ref or f"ai.{self.provider_id}"

    def capabilities(self) -> ProviderCapabilities:
        """Return declared capabilities, using conservative defaults."""
        return ProviderCapabilities(
            supports_tools=bool(self.supports_tools),
            supports_vision=bool(self.supports_vision),
            supports_json=True,
            context_window=int(self.context_length or 8192),
        )

    def model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_id=self.provider_id,
            model_id=self.model,
            label=self.model or self.label,
            capabilities=self.capabilities(),
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "credential_ref": self.credential_ref,
            "is_local": self.is_local,
            "enabled": self.enabled,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "context_length": self.context_length,
            "extra_headers": dict(self.extra_headers),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderConfig:
        return cls(
            provider_id=str(data.get("provider_id", "")).strip(),
            label=str(data.get("label", "")).strip() or "Provider",
            kind=str(data.get("kind", KIND_OPENAI_COMPATIBLE)),
            base_url=str(data.get("base_url", "")),
            model=str(data.get("model", "")),
            credential_ref=str(data.get("credential_ref", "")),
            is_local=bool(data.get("is_local", False)),
            enabled=bool(data.get("enabled", False)),
            supports_tools=_optional_bool(data.get("supports_tools")),
            supports_vision=_optional_bool(data.get("supports_vision")),
            context_length=int(data.get("context_length", 0) or 0),
            extra_headers={
                str(k): str(v)
                for k, v in (data.get("extra_headers") or {}).items()
            },
            note=str(data.get("note", "")),
        )


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def default_providers() -> list[ProviderConfig]:
    """Ship the accessible defaults, all disabled until the user opts in.

    Hugging Face is the free/on-ramp path where its inference router offers an
    OpenAI-compatible endpoint. Ollama is the fully local path. A generic
    OpenAI-compatible entry covers everything else (LM Studio, llama.cpp,
    vLLM, and any third-party API).
    """
    return [
        ProviderConfig(
            provider_id="huggingface",
            label="Hugging Face",
            kind=KIND_HUGGINGFACE,
            base_url="https://router.huggingface.co/v1",
            model="",
            credential_ref="ai.huggingface",
            is_local=False,
            enabled=False,
            note=(
                "Free-tier availability, rate limits, and model routing change "
                "over time. A token is required for most models; check the "
                "model's page for whether it supports tool calling."
            ),
        ),
        ProviderConfig(
            provider_id="ollama",
            label="Ollama (local)",
            kind=KIND_OLLAMA,
            base_url="http://127.0.0.1:11434",
            model="",
            credential_ref="",
            is_local=True,
            enabled=False,
            note="Requires a local Ollama server. Nothing leaves this machine.",
        ),
        ProviderConfig(
            provider_id="lmstudio",
            label="LM Studio (local)",
            kind=KIND_OPENAI_COMPATIBLE,
            base_url="http://127.0.0.1:1234/v1",
            model="",
            credential_ref="",
            is_local=True,
            enabled=False,
            note="LM Studio's local OpenAI-compatible server. Key is optional.",
        ),
        ProviderConfig(
            provider_id="openai",
            label="OpenAI",
            kind=KIND_OPENAI_COMPATIBLE,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            credential_ref="ai.openai",
            supports_tools=True,
            supports_vision=True,
            context_length=128000,
            enabled=False,
        ),
        ProviderConfig(
            provider_id="anthropic",
            label="Anthropic",
            kind=KIND_ANTHROPIC,
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-haiku-latest",
            credential_ref="ai.anthropic",
            supports_tools=True,
            supports_vision=True,
            context_length=200000,
            enabled=False,
        ),
        ProviderConfig(
            provider_id="openrouter",
            label="OpenRouter",
            kind=KIND_OPENAI_COMPATIBLE,
            base_url="https://openrouter.ai/api/v1",
            model="",
            credential_ref="ai.openrouter",
            supports_tools=True,
            enabled=False,
        ),
        ProviderConfig(
            provider_id="custom",
            label="Custom OpenAI-Compatible",
            kind=KIND_OPENAI_COMPATIBLE,
            base_url="",
            model="",
            credential_ref="ai.custom",
            enabled=False,
            note="Any server speaking the OpenAI chat-completions API.",
        ),
    ]


@dataclass
class AISettings:
    """Everything the assistant needs to know about user intent."""

    enabled: bool = False
    agent_mode: AgentMode = AgentMode.ASSIST
    edit_policy: EditPolicy = EditPolicy.ASK_BEFORE_CHANGES
    permissions: PermissionPolicy = field(default_factory=PermissionPolicy)
    providers: list[ProviderConfig] = field(default_factory=default_providers)
    default_provider_id: str = ""
    max_agent_steps: int = 14
    request_timeout_seconds: float = 120.0
    stream: bool = True
    temperature: float = 0.2
    max_output_tokens: int = 2048
    #: Persist conversations next to the project (opt-in, off by default).
    save_conversations: bool = False
    #: Verbose developer logging (still never logs secrets).
    verbose_logging: bool = False
    #: Show the AI-created highlight animation on changed nodes.
    highlight_changes: bool = True

    # ------------------------------------------------------------------
    # Provider helpers
    # ------------------------------------------------------------------

    def provider(self, provider_id: str) -> ProviderConfig | None:
        for config in self.providers:
            if config.provider_id == provider_id:
                return config
        return None

    def active_provider(self) -> ProviderConfig | None:
        """Return the configured default, else the first enabled provider."""
        if self.default_provider_id:
            config = self.provider(self.default_provider_id)
            if config is not None and config.enabled:
                return config
        for config in self.providers:
            if config.enabled:
                return config
        return None

    def enabled_providers(self) -> list[ProviderConfig]:
        return [config for config in self.providers if config.enabled]

    def set_provider(self, config: ProviderConfig) -> None:
        for index, existing in enumerate(self.providers):
            if existing.provider_id == config.provider_id:
                self.providers[index] = config
                return
        self.providers.append(config)

    def remove_provider(self, provider_id: str) -> bool:
        for index, existing in enumerate(self.providers):
            if existing.provider_id == provider_id:
                del self.providers[index]
                if self.default_provider_id == provider_id:
                    self.default_provider_id = ""
                return True
        return False

    def is_ready(self) -> bool:
        """Whether the assistant can actually start a conversation."""
        if not self.enabled:
            return False
        config = self.active_provider()
        return bool(config and config.model)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": AI_SETTINGS_VERSION,
            "enabled": self.enabled,
            "agent_mode": self.agent_mode.value,
            "edit_policy": self.edit_policy.value,
            "permissions": self.permissions.to_dict(),
            "providers": [config.to_dict() for config in self.providers],
            "default_provider_id": self.default_provider_id,
            "max_agent_steps": self.max_agent_steps,
            "request_timeout_seconds": self.request_timeout_seconds,
            "stream": self.stream,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "save_conversations": self.save_conversations,
            "verbose_logging": self.verbose_logging,
            "highlight_changes": self.highlight_changes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AISettings:
        providers_raw = data.get("providers")
        providers: list[ProviderConfig] = []
        if isinstance(providers_raw, list):
            for entry in providers_raw:
                if isinstance(entry, dict):
                    config = ProviderConfig.from_dict(entry)
                    if config.provider_id:
                        providers.append(config)
        if not providers:
            providers = default_providers()

        # Merge in any built-in preset the file does not mention, so a document
        # written by an older build still shows the current provider list.
        known = {config.provider_id for config in providers}
        for preset in default_providers():
            if preset.provider_id not in known:
                providers.append(preset)

        return cls(
            enabled=bool(data.get("enabled", False)),
            agent_mode=_enum(AgentMode, data.get("agent_mode"), AgentMode.ASSIST),
            edit_policy=_enum(
                EditPolicy, data.get("edit_policy"), EditPolicy.ASK_BEFORE_CHANGES
            ),
            permissions=PermissionPolicy.from_dict(data.get("permissions")),
            providers=providers,
            default_provider_id=str(data.get("default_provider_id", "")),
            max_agent_steps=max(
                1, min(64, int(data.get("max_agent_steps", 14) or 14))
            ),
            request_timeout_seconds=max(
                5.0,
                min(900.0, float(data.get("request_timeout_seconds", 120.0) or 120.0)),
            ),
            stream=bool(data.get("stream", True)),
            temperature=max(0.0, min(2.0, float(data.get("temperature", 0.2) or 0.0))),
            max_output_tokens=max(
                128, min(32768, int(data.get("max_output_tokens", 2048) or 2048))
            ),
            save_conversations=bool(data.get("save_conversations", False)),
            verbose_logging=bool(data.get("verbose_logging", False)),
            highlight_changes=bool(data.get("highlight_changes", True)),
        )


def _enum(enum_type: Any, value: Any, default: Any) -> Any:
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        return default


class AISettingsStore:
    """Atomic JSON persistence for :class:`AISettings`."""

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path or app_data_path("userdata", AI_SETTINGS_FILENAME)
        self.settings: AISettings = AISettings()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AISettings:
        """Load settings, falling back to defaults on any problem."""
        if not self._path.is_file():
            self.settings = AISettings()
            return self.settings
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("AI settings unreadable (%s); using defaults", type(exc).__name__)
            self.settings = AISettings()
            return self.settings
        if not isinstance(raw, dict):
            self.settings = AISettings()
            return self.settings
        self.settings = AISettings.from_dict(raw)
        return self.settings

    def save(self) -> None:
        """Write settings atomically. Never writes secrets."""
        path = self._path
        ensure_directory(path.parent)
        payload = self.settings.to_dict()
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
