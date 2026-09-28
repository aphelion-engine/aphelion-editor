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
from ai.providers.urls import endpoint, is_loopback
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never replay credentials or POST bodies to redirect targets.


class Transport:
    """Shared TLS-verifying transport with bounded, cancellable I/O."""

    def __init__(self, *, timeout=120.0, user_agent="Aphelion-AI"):
        self.timeout = timeout
        self.connect_timeout = 10.0
        self.stream_idle_timeout = 60.0
        self.user_agent = user_agent
        self.should_stop = None
        self.debug_logging = False
        self.allow_insecure_http = False
        self.opener = urllib.request.build_opener(_NoRedirect())

    def _request(self, url, payload, headers):
        from ai.providers.urls import validate_url, is_loopback
        validate_url(url)
        if headers and url.startswith("http:") and not is_loopback(url) and not self.allow_insecure_http:
            raise ProviderAuthError("This remote endpoint uses HTTP. Credentials could be transmitted without encryption. Enable the explicit HTTP warning acknowledgement in provider settings to continue.")
        merged = {"Content-Type": "application/json", "Accept": "application/json",
                  "User-Agent": self.user_agent}
        merged.update(headers)
        if self.debug_logging:
            from utils.logging_setup import get_logger
            get_logger("ai.http").debug("%s %s headers=%s stream=%s messages=%d",
                "POST" if payload is not None else "GET", url,
                {name: "[REDACTED]" for name in headers},
                (payload or {}).get("stream", False), len((payload or {}).get("messages", [])))
        return urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                      headers=merged, method="POST" if payload is not None else "GET")

    def _read(self, url, payload, headers, streaming=False):
        import queue
        import threading
        import time
        from ai.errors import CancelledError
        if self.should_stop and self.should_stop():
            raise CancelledError("Request cancelled before sending.")
        request = self._request(url, payload, headers)
        events = queue.Queue(maxsize=64)
        abandoned = threading.Event()
        active_socket = []
        def emit(item):
            while not abandoned.is_set():
                try:
                    events.put(item, timeout=0.1)
                    return
                except queue.Full:
                    pass
        def worker():
            try:
                with self.opener.open(request, timeout=min(self.connect_timeout, self.timeout)) as response:
                    # urllib uses a socket timeout; the consumer also enforces total and idle deadlines.
                    try:
                        active_socket.append(response.fp.raw._sock)
                        active_socket[-1].settimeout(self.stream_idle_timeout if streaming else self.timeout)
                    except AttributeError:
                        pass
                    if streaming:
                        for line in response:
                            if abandoned.is_set():
                                break
                            emit(("data", line))
                    else:
                        emit(("data", response.read()))
            except urllib.error.HTTPError as exc:
                emit(("error", self._http_error(exc, headers)))
            except Exception:
                emit(("error", ProviderUnavailableError("Provider network request failed or timed out.")))
            finally:
                emit(("done", None))
        threading.Thread(target=worker, daemon=True, name="ai-http").start()
        start = last = time.monotonic()
        try:
            while True:
                if self.should_stop and self.should_stop():
                    raise CancelledError("Request cancelled.")
                now = time.monotonic()
                if now - start > self.timeout or (streaming and now - last > self.stream_idle_timeout):
                    raise ProviderUnavailableError("Provider request timed out.")
                try:
                    kind, value = events.get(timeout=0.05)
                except queue.Empty:
                    continue
                last = time.monotonic()
                if kind == "error":
                    raise value from None
                if kind == "done":
                    return
                yield value
        finally:
            abandoned.set()
            for connection in active_socket:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def post_json(self, url, payload, headers=None):
        return self._json(url, payload, headers or {})

    def get_json(self, url, headers=None):
        return self._json(url, None, headers or {})

    def _json(self, url, payload, headers):
        raw = b"".join(self._read(url, payload, headers))
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProviderResponseError("Provider returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise ProviderResponseError("Provider returned an unexpected payload.")
        return result

    def stream_lines(self, url, payload, headers=None):
        for raw in self._read(url, payload, headers or {}, streaming=True):
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                yield line

    @staticmethod
    def _http_error(exc, headers=None):
        detail = ""
        try:
            detail = _extract_message(json.loads(exc.read(8192)))
        except Exception:
            pass
        for value in (headers or {}).values():
            for secret in (value, value.removeprefix("Bearer ")):
                if secret:
                    detail = detail.replace(secret, "[REDACTED]")
        detail = detail[:400]
        status = exc.code
        message = f"Provider returned HTTP {status}." + (f" {detail}" if detail else "")
        if status in (401, 403):
            return ProviderAuthError(message + " Verify this profile's API key.")
        if status == 429:
            return ProviderRateLimitError(message)
        if status in (400, 413, 422) and _looks_like_overflow(detail):
            return ContextOverflowError("Request exceeded the model context window.")
        if status >= 500 or status == 408:
            return ProviderUnavailableError(message)
        return ProviderResponseError(message)


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
        self.transport.allow_insecure_http = config.allow_insecure_http
        self.transport.connect_timeout = max(1, config.connect_timeout)
        self.transport.stream_idle_timeout = max(1, config.stream_idle_timeout)

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
        return self.config.scope == "LOCAL"

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
        """Adapters select their own authentication scheme."""
        return {}

    def _endpoint(self, suffix: str) -> str:
        return endpoint(self.config.base_url, suffix)

    def diagnostics(self) -> dict[str, Any]:
        return {"provider": self.label, "mode": self.config.connection_mode,
                "base_url": self.config.base_url, "model": self.config.model,
                "authentication": "configured" if self.api_key else "none"}
