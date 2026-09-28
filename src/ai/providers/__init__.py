"""Provider implementations.

Providers are independent of the agent engine: the engine only knows the
:class:`~ai.providers.base.AIProvider` interface. Adding a new backend means
adding one subclass, not touching tools, context, or the UI.
"""

from __future__ import annotations

from ai.providers.base import (AIProvider, ChatRequest, ChatResponse,
                               Transport)

__all__ = ["AIProvider", "ChatRequest", "ChatResponse", "Transport"]
