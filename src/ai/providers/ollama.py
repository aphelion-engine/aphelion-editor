"""Native Ollama API for local, cloud, and custom connections."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ai.providers.auth import BearerAuth
from ai.errors import ProviderResponseError, ProviderUnavailableError
from ai.providers.base import (AIProvider, ChatRequest, ChatResponse,
                               StopCallback, TokenCallback)
from ai.types import ModelInfo, ProviderCapabilities, ProviderTestResult, ToolCall, Usage


class OllamaProvider(AIProvider):
    """Ollama native chat and NDJSON streaming."""

    kind = "ollama"

    def _auth_headers(self) -> dict[str, str]:
        headers = dict(self.config.extra_headers)
        headers.update(BearerAuth(self.api_key).headers())
        return headers

    def capabilities(self, model: str | None = None) -> ProviderCapabilities:
        declared = self.config.capabilities()
        name = (model or self.config.model or "").lower()
        # Native tool support varies by model/template. Unknown models use the
        # validated structured protocol unless the user explicitly enables tools.
        tools = False
        vision = any(
            marker in name for marker in ("llava", "vision", "vl", "minicpm-v", "moondream")
        )
        return ProviderCapabilities(
            supports_tools=self.config.supports_tools if self.config.supports_tools is not None else tools,
            supports_vision=self.config.supports_vision if self.config.supports_vision is not None else vision,
            supports_json=(self.config.connection_mode != "cloud"
                           and urlsplit(self.config.base_url).hostname != "ollama.com"
                           and not name.endswith(":cloud")),
            context_window=self.config.context_length or 8192,
        )

    def list_models(self) -> tuple[ModelInfo, ...]:
        try:
            payload = self.transport.get_json(self._endpoint("api/tags"), self._auth_headers())
        except Exception:  # noqa: BLE001 - server may be down; that is not fatal
            return () if not self.config.model else (self.config.model_info(),)
        models: list[ModelInfo] = []
        entries = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("model") or entry.get("name") or "").strip()
                if not name:
                    continue
                models.append(
                    ModelInfo(
                        provider_id=self.provider_id,
                        model_id=name,
                        label=name,
                        capabilities=self.capabilities(name),
                    )
                )
        models.sort(key=lambda item: item.model_id)
        return tuple(models)

    def test_connection(self) -> ProviderTestResult:
        from ai.types import ChatMessage
        try:
            self.generate(ChatRequest(model=self.config.model,
                          messages=[ChatMessage(role="user", content="Hello!")], max_tokens=8))
        except Exception as exc:
            return ProviderTestResult(ok=False, message=str(exc))
        return ProviderTestResult(ok=True, message=f"Connected to Ollama. Model: {self.config.model}",
                                  models=(self.config.model,), capabilities=self.capabilities())

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
        self.transport.should_stop = should_stop
        if not request.model:
            raise ProviderResponseError(
                "No Ollama model is selected. Pick one in Preferences → AI."
            )
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for message in request.messages:
            if message.role == "assistant" and message.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": call.name,
                                    "arguments": call.arguments,
                                }
                            }
                            for call in message.tool_calls
                        ],
                    }
                )
                continue
            if message.role == "tool":
                messages.append(
                    {"role": "tool", "content": message.content}
                )
                continue
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.images:
                entry["images"] = [
                    image.split(",", 1)[1] if "," in image else image
                    for image in message.images
                ]
            messages.append(entry)

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "stream": bool(on_token is not None),
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.json_mode and self.capabilities(request.model).supports_json:
            payload["format"] = "json"
        if request.tools:
            payload["tools"] = [_to_ollama_tool(schema) for schema in request.tools]

        url = self._endpoint("api/chat")
        if on_token is None:
            decoded = self.transport.post_json(url, payload, self._auth_headers())
            return self._parse(decoded)
        return self._stream(url, payload, on_token, should_stop)

    def _parse(self, decoded: dict[str, Any]) -> ChatResponse:
        if decoded.get("error"):
            raise ProviderResponseError("Ollama returned an API error.")
        if not isinstance(decoded.get("message"), dict):
            raise ProviderResponseError("Ollama returned no message.")
        message = decoded.get("message") if isinstance(decoded.get("message"), dict) else {}
        calls: list[ToolCall] = []
        for index, entry in enumerate(message.get("tool_calls") or []):
            if not isinstance(entry, dict):
                continue
            function = entry.get("function") if isinstance(entry.get("function"), dict) else {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"__raw__": arguments}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(ToolCall(name=name, arguments=arguments, call_id=f"ollama_{index}"))

        prompt_tokens = int(decoded.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(decoded.get("eval_count", 0) or 0)
        done_reason = str(decoded.get("done_reason") or "")
        return ChatResponse(
            content=str(message.get("content") or ""),
            tool_calls=calls,
            finish_reason="tool_calls" if calls else (done_reason or "stop"),
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            raw=decoded,
        )

    def _stream(
        self,
        url: str,
        payload: dict[str, Any],
        on_token: TokenCallback,
        should_stop: StopCallback | None,
    ) -> ChatResponse:
        content_parts: list[str] = []
        calls: list[ToolCall] = []
        final = ChatResponse()
        complete = False
        for line in self.transport.stream_lines(url, payload, self._auth_headers()):
            if should_stop is not None and should_stop():
                from ai.errors import CancelledError
                raise CancelledError("Request cancelled.")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                raise ProviderResponseError("Ollama returned malformed NDJSON.") from None
            parsed = self._parse(event)
            if parsed.content:
                content_parts.append(parsed.content)
                on_token(parsed.content)
            for call in parsed.tool_calls:
                call.call_id = f"ollama_{len(calls)}"
                calls.append(call)
            final = parsed
            if event.get("done"):
                complete = True
                break
        if not complete:
            raise ProviderResponseError("Ollama stream ended before completion.")
        final.content = "".join(content_parts)
        final.tool_calls = calls
        return final


def _to_ollama_tool(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI tool schema to Ollama's function shape."""
    function = schema.get("function") if isinstance(schema, dict) else None
    if not isinstance(function, dict):
        return {"type": "function", "function": {"name": "", "parameters": {}}}
    return {
        "type": "function",
        "function": {
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "parameters": function.get("parameters", {}),
        },
    }
