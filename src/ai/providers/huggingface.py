"""Hugging Face provider.

Hugging Face is the accessible/on-ramp option: its inference router exposes an
OpenAI-compatible endpoint, so this class is a thin specialisation of the
generic provider with a model-id-aware capability guess and friendlier error
messages.

Nothing here assumes a particular model is free, or that a route will always
exist. Availability, rate limits, and which models can be reached change over
time; the settings UI mirrors that by treating the provider as configurable
rather than hardcoding a model id.
"""

from __future__ import annotations

from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.types import ProviderCapabilities


class HuggingFaceProvider(OpenAICompatibleProvider):
    """Hugging Face inference router (OpenAI-compatible)."""

    kind = "huggingface"

    def capabilities(self, model: str | None = None) -> ProviderCapabilities:
        declared = self.config.capabilities()
        if self.config.supports_tools is not None or self.config.supports_vision is not None:
            return declared
        return self._guess_capabilities(model or self.config.model)

    @staticmethod
    def _guess_capabilities(model: str) -> ProviderCapabilities:
        """Guess capabilities from a Hub model id.

        Many Hub models are chat templates without native tool calling. Those
        still work: the engine falls back to the strictly validated structured
        tool-call protocol, so an optimistic guess is not required here.
        """
        name = (model or "").lower()
        vision = any(
            marker in name
            for marker in ("-vl", "vision", "llava", "idefics", "pixtral",
                           "qwen2-vl", "qwen2.5-vl", "internvl", "florence",
                           "moondream", "smolvlm")
        )
        tools = any(
            marker in name
            for marker in ("hermes", "functionary", "mistral-nemo", "qwen",
                           "llama-3.1", "llama-3.2", "llama-3.3", "llama-4",
                           "deepseek", "command-r", "granite", "hammer",
                           "glm-4", "phi-4", "firefunction")
        )
        return ProviderCapabilities(
            supports_tools=tools,
            supports_vision=vision,
            supports_json=True,
            context_window=16384,
        )

    def test_connection(self):
        result = super().test_connection()
        if result.ok:
            return result
        if "rejected the API key" in result.message:
            return type(result)(
                ok=False,
                message=(
                    "Hugging Face rejected the token. Create or check a token "
                    "with inference permission at huggingface.co/settings/tokens."
                ),
                models=result.models,
            )
        return result
