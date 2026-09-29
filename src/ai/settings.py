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
from ai.source.limits import SourceLimits
from ai.types import (AgentMode, CloudSourceSharing, EditPolicy, ModelInfo,
                      ProviderCapabilities, SourceAccess)
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
    connection_mode: str = "custom"
    credential_env: str = ""
    auth_header: str = ""
    allow_insecure_http: bool = False
    connect_timeout: float = 10.0
    stream_idle_timeout: float = 60.0
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
        from ai.providers.urls import is_loopback
        cloud_model = self.kind == KIND_OLLAMA and self.model.lower().endswith(":cloud")
        return "LOCAL" if self.is_local and is_loopback(self.base_url) and self.connection_mode != "cloud" and not cloud_model else "CLOUD"

    @property
    def credential_key(self) -> str:
        return self.credential_ref or f"ai.{self.provider_id}"

    def capabilities(self, model: str | None = None) -> ProviderCapabilities:
        """Return declared capabilities for an optional model name.

        ``ProviderConfig`` is data, not a provider implementation.  The model
        argument is accepted so configuration and provider capability lookups
        share one stable signature; provider-specific detection remains in the
        live adapter.
        """
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

    def validate(self) -> None:
        import re
        from ai.providers.urls import validate_url
        validate_url(self.base_url)
        if not self.model.strip():
            raise ValueError(f"{self.label}: enter a model name (discovery is optional).")
        if self.connection_mode not in ("local", "cloud", "custom"):
            raise ValueError("Unknown provider connection mode.")
        if self.auth_header and not re.fullmatch(r"[A-Za-z0-9-]+", self.auth_header):
            raise ValueError("Authentication header must be a valid HTTP header name.")
        if self.credential_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.credential_env):
            raise ValueError("Enter an environment variable name, not its value.")

    def to_dict(self) -> dict[str, Any]:
        import re
        if any(re.search(r"authorization|api.?key|token|secret|cookie", key, re.I) for key in self.extra_headers):
            raise ValueError("Store credentials in the secure API key field, not extra headers. Use the authentication header name option for custom headers.")
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "credential_ref": self.credential_ref,
            "connection_mode": self.connection_mode,
            "credential_env": self.credential_env,
            "auth_header": self.auth_header,
            "allow_insecure_http": self.allow_insecure_http,
            "connect_timeout": self.connect_timeout,
            "stream_idle_timeout": self.stream_idle_timeout,
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
            connection_mode=str(data.get("connection_mode", "custom")),
            credential_env=str(data.get("credential_env", "")),
            auth_header=str(data.get("auth_header", "")),
            allow_insecure_http=bool(data.get("allow_insecure_http", False)),
            connect_timeout=float(data.get("connect_timeout", 10)),
            stream_idle_timeout=float(data.get("stream_idle_timeout", 60)),
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
        ProviderConfig(provider_id="ollama-cloud", label="Ollama Cloud", kind=KIND_OLLAMA,
                       base_url="https://ollama.com", connection_mode="cloud",
                       credential_env="OLLAMA_API_KEY", model="gemma4:31b"),
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
            base_url="http://localhost:11434",
            connection_mode="local",
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
    max_agent_steps: int = 48
    request_timeout_seconds: float = 120.0
    stream: bool = True
    temperature: float = 0.2
    max_output_tokens: int = 2048
    max_tool_calls: int = -1
    #: Persist conversations next to the project (opt-in, off by default).
    save_conversations: bool = False
    #: Verbose developer logging (still never logs secrets).
    verbose_logging: bool = False
    #: Show the AI-created highlight animation on changed nodes.
    highlight_changes: bool = True
    #: System prompt injected into the agent's context.
    system_prompt: str = ""

    # -- read-only source intelligence (opt-in, off by default) ---------

    #: How much of the Aphelion source tree the assistant may read.
    source_access: SourceAccess = SourceAccess.OFF
    #: Whether retrieved source may be sent to a remote provider.
    cloud_source_sharing: CloudSourceSharing = CloudSourceSharing.NEVER
    #: Optional explicit checkout to index. Empty means "detect automatically".
    source_root: str = ""
    #: Retrieval budgets that bound how much source one run may pull in.
    source_limits: SourceLimits = field(default_factory=SourceLimits)

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
            "max_tool_calls": self.max_tool_calls,
            "save_conversations": self.save_conversations,
            "verbose_logging": self.verbose_logging,
            "highlight_changes": self.highlight_changes,
            "source_access": self.source_access.value,
            "cloud_source_sharing": self.cloud_source_sharing.value,
            "source_root": self.source_root,
            "source_limits": self.source_limits.to_dict(),
            "system_prompt": self.system_prompt,
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
                1, min(64, int(data.get("max_agent_steps", 48) or 48))
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
            max_tool_calls=int(
                data.get("max_tool_calls", -1)
            ),
            save_conversations=bool(data.get("save_conversations", False)),
            verbose_logging=bool(data.get("verbose_logging", False)),
            highlight_changes=bool(data.get("highlight_changes", True)),
            system_prompt=str(data.get("system_prompt", "") or ""),
            source_access=_enum(SourceAccess, data.get("source_access"), SourceAccess.OFF),
            cloud_source_sharing=_enum(
                CloudSourceSharing,
                data.get("cloud_source_sharing"),
                CloudSourceSharing.NEVER,
            ),
            source_root=str(data.get("source_root", "") or ""),
            source_limits=SourceLimits.from_dict(data.get("source_limits")),
        )


def _enum(enum_type: Any, value: Any, default: Any) -> Any:
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        return default


_STORE: AISettingsStore | None = None


def ai_settings_store() -> AISettingsStore:
    """Return the process-wide AI settings store, loading it on first use.

    Deliberately lazy: the editor never touches AI settings during startup, so
    a user who never opens the assistant pays nothing for its existence.
    """
    global _STORE
    if _STORE is None:
        _STORE = AISettingsStore()
        _STORE.load()
    return _STORE


def reset_ai_settings_store_for_tests(path: Path | None = None) -> AISettingsStore:
    """Replace the module singleton (tests only)."""
    global _STORE
    _STORE = AISettingsStore(path)
    _STORE.load()
    return _STORE


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
        """Write settings atomically. Never writes secrets.

        The document deliberately contains only provider *references* and
        capabilities; :mod:`ai.credentials` owns the encrypted values.
        """
        path = self._path
        ensure_directory(path.parent)
        for provider in self.settings.enabled_providers():
            provider.validate()
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
