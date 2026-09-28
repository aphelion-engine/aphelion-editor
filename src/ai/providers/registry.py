"""Provider factory.

``create_provider`` is the only place that maps a configured kind onto an
implementation class. Adding a backend never requires changing the engine, the
tools, or the UI.
"""

from __future__ import annotations

from typing import Any
import os

from ai.errors import ProviderError
from ai.providers.base import AIProvider
from ai.providers.anthropic import AnthropicProvider
from ai.providers.google import GoogleProvider
from ai.providers.huggingface import HuggingFaceProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.settings import (KIND_ANTHROPIC, KIND_GOOGLE, KIND_HUGGINGFACE,
                         KIND_OLLAMA, KIND_OPENAI_COMPATIBLE, ProviderConfig)

#: kind â†’ implementation.
KIND_CLASSES: dict[str, type[AIProvider]] = {
    KIND_OPENAI_COMPATIBLE: OpenAICompatibleProvider,
    KIND_HUGGINGFACE: HuggingFaceProvider,
    KIND_OLLAMA: OllamaProvider,
    KIND_ANTHROPIC: AnthropicProvider,
    KIND_GOOGLE: GoogleProvider,
}

#: Friendly descriptions shown in settings.
KIND_LABELS: dict[str, str] = {
    KIND_OPENAI_COMPATIBLE: "OpenAI-compatible API",
    KIND_HUGGINGFACE: "Hugging Face inference",
    KIND_OLLAMA: "Ollama (local / cloud / custom)",
    KIND_ANTHROPIC: "Anthropic Messages API",
    KIND_GOOGLE: "Google Gemini (OpenAI-compatible endpoint)",
}


def create_provider(
    config: ProviderConfig,
    *,
    credentials: Any = None,
    timeout: float = 120.0,
) -> AIProvider:
    """Build the provider implementation for ``config``.

    Raises:
        ProviderError: when the kind is unknown or the config is incomplete.
    """
    implementation = KIND_CLASSES.get(config.kind)
    if implementation is None:
        raise ProviderError(
            f"Unknown provider kind '{config.kind}'. Supported: "
            + ", ".join(sorted(KIND_CLASSES))
        )

    api_key = credentials.get(config.credential_key) or "" if credentials is not None else ""
    if not api_key and config.credential_env:
        api_key = os.environ.get(config.credential_env, "")

    provider = implementation(config, api_key=api_key)
    provider.transport.timeout = max(5.0, float(timeout))
    return provider


def provider_kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def supported_kinds() -> list[str]:
    return sorted(KIND_CLASSES)
