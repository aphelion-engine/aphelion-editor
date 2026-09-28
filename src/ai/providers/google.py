"""Google's explicitly documented OpenAI compatibility protocol."""
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.providers.urls import endpoint


class GoogleProvider(OpenAICompatibleProvider):
    kind = "google"

    def _endpoint(self, suffix):
        base = self.config.base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
        return endpoint(base, suffix)
