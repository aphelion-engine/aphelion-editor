"""Provider abstraction and HTTP transport.

The transport uses only the standard library (``urllib``) so enabling the
assistant never adds a runtime dependency or import cost. Streaming is plain
SSE / NDJSON line reading, which works against every endpoint we support.

Transport failures are mapped onto the :mod:`ai.errors` hierarchy so the
engine can distinguish "the user's key is wrong" from "the network blipped"
from "the model's context is full", and never crash the editor for any of them.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from ai.errors import (ContextOverflowError, ProviderAuthError, ProviderError,
                       ProviderRateLimitError, ProviderResponseError,
                       ProviderUnavailableError)
from ai.settings import ProviderConfig
from ai.types import ChatMessage, ModelInfo, ProviderCapabilities, ProviderTestResult, ToolCall, Usage

#: Called with each streamed text fragment.
TokenCallback = Callable[[str], None]
#: Returns ``True`` when the user has asked to stop.
StopCallback = Callable[[], bool]


@dataclass
class ChatRequest:
    """One provider-neutral completion request."""

    model: str
    messages: list[ChatMessage]
    system: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 2048
    json_mode: bool = False
    tool_choice: str = "auto"

    def to_openai_messages(self) -> list[dict[str, Any]]:
        """Flatten to the OpenAI chat-completions message array."""
        payload: list[dict[str, Any]] = []
        if self.system:
            payload.append({"role": "system", "content": self.system})
        for message in self.messages:
            if message.role == "assistant" and message.tool_calls:
                payload.append(
                    {
                        "role": "assistant",
                        "content": message.content or None,
                        "tool_calls": [
                            {
                                "id": call.call_id or f"call_{index}",
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments),
                                },
                            }
                            for index, call in enumerate(message.tool_calls)
                        ],
                    }
                )
                continue
            if message.role == "tool":
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                )
                continue
            if message.images:
                parts: list[dict[str, Any]] = []
                if message.content:
                    parts.append({"type": "text", "text": message.content})
                for image in message.images:
                    parts.append({"type": "image_url", "image_url": {"url": image}})
                payload.append({"role": message.role, "content": parts})
                continue
            payload.append({"role": message.role, "content": message.content})
        return payload


@dataclass
class ChatResponse:
    """One provider reply."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ======================================================================
# Transport
# ======================================================================


class Transport:
    """Minimal JSON / SSE client with consistent error mapping."""

    def __init__(self, *, timeout: float = 120.0, user_agent: str = "Aphelion-AI") -> None:
        self.timeout = float(timeout)
        self.user_agent = user_agent

    # -- helpers ---------------------------------------------------------

    def _request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> urllib.request.Request:
        body = json.dumps(payload).encode("utf-8")
        merged = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        merged.update(headers)
        return urllib.request.Request(url, data=body, headers=merged, method="POST")

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST a JSON body and decode the JSON reply."""
        request = self._request(url, payload, headers or {})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"Could not reach the provider: {_network_message(exc)}"
            ) from exc
        if not raw:
            raise ProviderResponseError("The provider returned an empty response.")
        try:
            decoded = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "The provider returned a non-JSON response."
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderResponseError("The provider returned an unexpected payload.")
        return decoded

    def stream_lines(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Iterator[str]:
        """POST and yield response lines (SSE or NDJSON) as they arrive."""
        request = self._request(url, payload, headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"Could not reach the provider: {_network_message(exc)}"
            ) from exc

        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    yield line
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"The provider stream failed: {_network_message(exc)}"
            ) from exc
        finally:
            response.close()

    def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> Any:
        merged = {"Accept": "application/json", "User-Agent": self.user_agent}
        merged.update(headers or {})
        request = urllib.request.Request(url, headers=merged, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"Could not reach the provider: {_network_message(exc)}"
            ) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ProviderResponseError("The provider returned a non-JSON response.") from exc

    # -- error mapping ---------------------------------------------------

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> ProviderError:
        detail = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            detail = _extract_message(parsed) or body[:400]
        except Exception:  # noqa: BLE001 - the body is best-effort context
            detail = ""

        status = exc.code
        if status in (401, 403):
            return ProviderAuthError(
                "The provider rejected the API key." + (f" {detail}" if detail else "")
            )
        if status == 429:
            return ProviderRateLimitError(
                "The provider is rate limiting requests."
                + (f" {detail}" if detail else "")
            )
        if status in (400, 413, 422) and _looks_like_overflow(detail):
            return ContextOverflowError(
                "The request exceeded the model's context window."
            )
        if status >= 500:
            return ProviderUnavailableError(
                f"The provider is unavailable (HTTP {status})."
                + (f" {detail}" if detail else "")
            )
        return ProviderResponseError(
            f"The provider returned HTTP {status}." + (f" {detail}" if detail else "")
        )


def _network_message(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        return f"{type(reason).__name__}: {reason}"
    return f"{type(exc).__name__}: {exc}"


def _extract_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or "")
    if isinstance(error, str):
        return error
    return str(payload.get("message") or payload.get("detail") or "")


_OVERFLOW_MARKERS = (
    "context length",
    "context window",
    "maximum context",
    "too many tokens",
    "reduce the length",
    "prompt is too long",
)


def _looks_like_overflow(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _OVERFLOW_MARKERS)


# ======================================================================
# Provider interface
# ======================================================================


class AIProvider:
    """Base class for every model backend."""

    #: Registry kind handled by this class.
    kind: str = "base"

    def __init__(self, config: ProviderConfig, *, api_key: str = "") -> None:
        self.config = config
        self.api_key = api_key or ""
        self.transport = Transport(timeout=120.0)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def provider_id(self) -> str:
        return self.config.provider_id

    @property
    def label(self) -> str:
        return self.config.label

    @property
    def is_local(self) -> bool:
        return bool(self.config.is_local)

    @property
    def scope(self) -> str:
        return "LOCAL" if self.is_local else "CLOUD"

    def capabilities(self, model: str | None = None) -> ProviderCapabilities:
        """Declared capabilities for ``model`` (conservative by default)."""
        return self.config.capabilities()

    def supports_tools(self, model: str | None = None) -> bool:
        return self.capabilities(model).supports_tools

    def supports_vision(self, model: str | None = None) -> bool:
        return self.capabilities(model).supports_vision

    def list_models(self) -> tuple[ModelInfo, ...]:
        """Return selectable models. Overridden where the API can list them."""
        if self.config.model:
            return (self.config.model_info(),)
        return ()

    def test_connection(self) -> ProviderTestResult:
        """Perform a cheap round-trip and report capabilities."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        request: ChatRequest,
        *,
        on_token: TokenCallback | None = None,
        should_stop: StopCallback | None = None,
    ) -> ChatResponse:
        """Run one completion, optionally streaming tokens."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _require_key(self) -> None:
        if self.config.is_local:
            return
        if not self.api_key:
            raise ProviderAuthError(
                f"{self.label} needs an API key. Add one in Preferences → AI."
            )

    def _endpoint(self, suffix: str) -> str:
        base = (self.config.base_url or "").rstrip("/")
        return f"{base}/{suffix.lstrip('/')}"
