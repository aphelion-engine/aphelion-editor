"""Generic OpenAI-compatible provider.

This one class covers the widest possible range of backends:

* OpenAI, OpenRouter, Groq, Together, and any third-party API
* Anthropic and Google via their OpenAI-compatible endpoints
* LM Studio, llama.cpp server, vLLM, and custom local servers

Because it speaks only the documented chat-completions wire format, adding a
provider to Aphelion is a base URL and a model name — not a new integration.
"""

from __future__ import annotations

import json
from typing import Any

from ai.errors import ProviderResponseError
from ai.providers.base import (AIProvider, ChatRequest, ChatResponse,
                               TokenCallback, StopCallback, Transport)
from ai.types import ModelInfo, ProviderCapabilities, ProviderTestResult, ToolCall, Usage


class OpenAICompatibleProvider(AIProvider):
    """Chat-completions provider driven entirely by configuration."""

    kind = "openai_compatible"

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def list_models(self) -> tuple[ModelInfo, ...]:
        models: list[ModelInfo] = []
        try:
            payload = self.transport.get_json(
                self._endpoint("models"), self._auth_headers()
            )
        except Exception:  # noqa: BLE001 - listing is optional everywhere
            payload = {}
        entries = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                model_id = str(entry.get("id", "")).strip()
                if model_id:
                    models.append(
                        ModelInfo(
                            provider_id=self.provider_id,
                            model_id=model_id,
                            label=model_id,
                            capabilities=self._guess_capabilities(model_id),
                        )
                    )
        if not models and self.config.model:
            models.append(self.config.model_info())
        models.sort(key=lambda item: item.model_id)
        return tuple(models)

    def test_connection(self) -> ProviderTestResult:
        model = self.config.model or ""
        self._require_key()
        if not model:
            available = self.list_models()
            if available:
                return ProviderTestResult(
                    ok=False,
                    message="Connected, but no model is selected. Choose one of: "
                    + ", ".join(item.model_id for item in available[:8]),
                    models=tuple(item.model_id for item in available[:20]),
                )
            return ProviderTestResult(
                ok=False, message="No model configured and none could be listed."
            )
        try:
            response = self.generate(
                ChatRequest(
                    model=model,
                    messages=[],
                    system="Reply with the single word: ok",
                    max_tokens=8,
                    temperature=0.0,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the message is the result
            return ProviderTestResult(ok=False, message=str(exc))
        capabilities = self.capabilities(model)
        return ProviderTestResult(
            ok=True,
            message=(
                "Connected. Model available. "
                f"Tool calling {'supported' if capabilities.supports_tools else 'unknown/unsupported'}. "
                f"Vision {'supported' if capabilities.supports_vision else 'unknown/unsupported'}."
            ),
            models=(model,),
            capabilities=capabilities,
        )

    # ------------------------------------------------------------------
    # Capability guessing
    # ------------------------------------------------------------------

    def capabilities(self, model: str | None = None) -> ProviderCapabilities:
        """Prefer explicit config, then a conservative name-based guess."""
        declared = self.config.capabilities()
        if self.config.supports_tools is not None or self.config.supports_vision is not None:
            return declared
        return self._guess_capabilities(model or self.config.model)

    @staticmethod
    def _guess_capabilities(model: str) -> ProviderCapabilities:
        """Heuristic capability detection for an unlisted model.

        Deliberately conservative for tool calling: a wrong ``True`` makes the
        model emit tool calls it cannot, whereas a wrong ``False`` merely
        routes through the strictly-validated JSON protocol, which always
        works.
        """
        name = (model or "").lower()
        vision = any(
            marker in name
            for marker in ("vision", "-vl", "llava", "gpt-4o", "gpt-4.1", "o4",
                           "claude-3", "claude-4", "gemini", "qwen2.5-vl",
                           "internvl", "pixtral", "moondream")
        )
        tools = False
        if any(
            marker in name
            for marker in ("gpt-4", "gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4",
                           "claude-3", "claude-4", "gemini", "qwen", "llama-3",
                           "llama3", "mistral", "mixtral", "deepseek", "command-r",
                           "firefunction", "hermes", "functionary", "granite")
        ):
            tools = True
        if _model_looks_local(name) and tools:
            # Local servers vary wildly in tool-call fidelity; prefer the
            # strictly-validated structured protocol unless the user declares
            # tool support explicitly in settings.
            tools = False
        return ProviderCapabilities(
            supports_tools=tools,
            supports_vision=vision,
            supports_json=True,
            context_window=8192,
        )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.to_openai_messages(),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.config.extra_headers:
            # Extra headers are transport-level, handled by the caller.
            pass
        return payload

    def _request_headers(self) -> dict[str, str]:
        headers = self._auth_headers()
        headers.update(self.config.extra_headers or {})
        return headers

    def generate(
        self,
        request: ChatRequest,
        *,
        on_token: TokenCallback | None = None,
        should_stop: StopCallback | None = None,
    ) -> ChatResponse:
        self._require_key()
        if not request.model:
            raise ProviderResponseError(
                "No model is selected for this provider. Pick one in "
                "Preferences → AI, or use Test Connection to list models."
            )
        url = self._endpoint("chat/completions")
        headers = self._request_headers()
        stream = bool(on_token is not None)
        payload = self.build_payload(request, stream=stream)

        if not stream:
            decoded = self.transport.post_json(url, payload, headers)
            return self._parse_response(decoded)

        return self._stream(url, payload, headers, on_token, should_stop)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_response(self, decoded: dict[str, Any]) -> ChatResponse:
        choices = decoded.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError(
                "The provider did not return any completion choices."
            )
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = _as_text(message.get("content"))
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=_parse_usage(decoded.get("usage")),
            raw=decoded if isinstance(decoded, dict) else {},
        )

    def _stream(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        on_token: TokenCallback,
        should_stop: StopCallback | None,
    ) -> ChatResponse:
        content_parts: list[str] = []
        tool_fragments: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        usage = Usage()

        for line in self.transport.stream_lines(url, payload, headers):
            if should_stop is not None and should_stop():
                finish_reason = finish_reason or "cancelled"
                break
            if line.startswith("data:"):
                data = line[5:].strip()
            elif line.startswith("{"):
                data = line
            else:
                continue
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            if isinstance(event.get("usage"), dict):
                usage = _parse_usage(event.get("usage"))
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            text = _as_text(delta.get("content"))
            if text:
                content_parts.append(text)
                on_token(text)
            reasoning = _as_text(delta.get("reasoning_content") or delta.get("reasoning"))
            if reasoning:
                on_token("")  # keep the stream alive; reasoning is surfaced separately
            _accumulate_tool_fragments(tool_fragments, delta.get("tool_calls"))

        return ChatResponse(
            content="".join(content_parts),
            tool_calls=_finalise_tool_calls(tool_fragments),
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _parse_tool_calls(raw: Any) -> list[ToolCall]:
        calls: list[ToolCall] = []
        if not isinstance(raw, list):
            return calls
        for index, entry in enumerate(raw):
            if not isinstance(entry, dict):
                continue
            function = entry.get("function") if isinstance(entry.get("function"), dict) else {}
            name = str(function.get("name") or entry.get("name") or "").strip()
            if not name:
                continue
            raw_arguments = _as_text(function.get("arguments"))
            calls.append(
                ToolCall(
                    name=name,
                    arguments=_parse_tool_arguments(raw_arguments),
                    call_id=str(entry.get("id") or f"call_{index}"),
                    raw_arguments=raw_arguments,
                )
            )
        return calls


def _model_looks_local(model: str) -> bool:
    """Whether a model name looks like a locally hosted model."""
    return any(
        marker in model
        for marker in ("llama", "mistral", "qwen", "phi", "gemma", "deepseek",
                       "codellama", "vicuna", "nous", "yi-", "smollm")
    )


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(value)


def _parse_tool_arguments(raw: str) -> dict[str, Any]:
    """Decode tool arguments, tolerating partial or empty JSON."""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {"__raw__": text}
    if isinstance(decoded, dict):
        return decoded
    return {"__raw__": text}


def _accumulate_tool_fragments(
    fragments: dict[int, dict[str, Any]],
    raw: Any,
) -> None:
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        index = int(entry.get("index", len(fragments)))
        slot = fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if entry.get("id"):
            slot["id"] = str(entry["id"])
        function = entry.get("function")
        if isinstance(function, dict):
            if function.get("name"):
                slot["name"] = str(function["name"])
            if function.get("arguments"):
                slot["arguments"] += str(function["arguments"])


def _finalise_tool_calls(fragments: dict[int, dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for index in sorted(fragments):
        slot = fragments[index]
        name = str(slot.get("name") or "").strip()
        if not name:
            continue
        raw_arguments = str(slot.get("arguments") or "")
        calls.append(
            ToolCall(
                name=name,
                arguments=_parse_tool_arguments(raw_arguments),
                call_id=str(slot.get("id") or f"call_{index}"),
                raw_arguments=raw_arguments,
            )
        )
    return calls


def _parse_usage(raw: Any) -> Usage:
    if not isinstance(raw, dict):
        return Usage()
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens", 0) or 0),
        completion_tokens=int(raw.get("completion_tokens", 0) or 0),
        total_tokens=int(raw.get("total_tokens", 0) or 0),
    )
