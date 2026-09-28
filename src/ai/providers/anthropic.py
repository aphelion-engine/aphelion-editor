"""Anthropic Messages protocol, including typed SSE content blocks."""
import json
from ai.providers.auth import ApiKeyHeaderAuth
from ai.providers.base import AIProvider, ChatRequest, ChatResponse
from ai.providers.urls import endpoint
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.errors import ProviderResponseError
from ai.types import ToolCall, Usage, ModelInfo


class AnthropicProvider(AIProvider):
    kind = "anthropic"

    def _auth_headers(self):
        headers = dict(self.config.extra_headers)
        headers["anthropic-version"] = "2023-06-01"
        headers.update(ApiKeyHeaderAuth("x-api-key", self.api_key).headers())
        return headers

    def _endpoint(self, suffix):
        return endpoint(self.config.base_url, "v1/" + suffix)

    test_connection = OpenAICompatibleProvider.test_connection
    _require_key = OpenAICompatibleProvider._require_key

    def list_models(self):
        try:
            data = self.transport.get_json(self._endpoint("models"), self._auth_headers())
            return tuple(ModelInfo(provider_id=self.provider_id, model_id=x["id"],
                                   label=x.get("display_name", x["id"]), capabilities=self.capabilities(x["id"]))
                         for x in data.get("data", []))
        except Exception:
            return super().list_models()

    def build_payload(self, request, *, stream):
        messages = []
        for msg in request.messages:
            blocks = []
            if msg.role == "tool":
                blocks.append({"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content})
            else:
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for image in msg.images:
                    if image.startswith("data:"):
                        mime, data = image.split(",", 1)
                        source = {"type": "base64", "media_type": mime[5:].split(";")[0], "data": data}
                    else:
                        source = {"type": "url", "url": image}
                    blocks.append({"type": "image", "source": source})
                for call in msg.tool_calls:
                    blocks.append({"type": "tool_use", "id": call.call_id, "name": call.name, "input": call.arguments})
            role = "assistant" if msg.role == "assistant" else "user"
            if blocks:
                if messages and messages[-1]["role"] == role:
                    messages[-1]["content"].extend(blocks)
                else:
                    messages.append({"role": role, "content": blocks})
        if not messages:
            messages = [{"role": "user", "content": "Hello!"}]
        payload = {"model": request.model, "messages": messages, "max_tokens": request.max_tokens,
                   "temperature": request.temperature, "stream": stream}
        if request.system:
            payload["system"] = request.system
        if request.tools:
            payload["tools"] = [{"name": t["function"]["name"],
                                 "description": t["function"].get("description", ""),
                                 "input_schema": t["function"].get("parameters", {})} for t in request.tools]
        return payload

    def _parse(self, data):
        if data.get("type") == "error" or not isinstance(data.get("content"), list):
            raise ProviderResponseError("Anthropic returned an invalid message or API error.")
        calls = [ToolCall(name=b["name"], arguments=b["input"], call_id=b["id"])
                 for b in data["content"] if b.get("type") == "tool_use"]
        usage = data.get("usage", {})
        prompt, output = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        return ChatResponse(content="".join(b.get("text", "") for b in data["content"] if b.get("type") == "text"),
                            tool_calls=calls, finish_reason=data.get("stop_reason", ""),
                            usage=Usage(prompt_tokens=prompt, completion_tokens=output, total_tokens=prompt+output))

    def generate(self, request, *, on_token=None, should_stop=None):
        self.transport.should_stop = should_stop
        if not request.model:
            raise ProviderResponseError("Select a model first.")
        payload = self.build_payload(request, stream=on_token is not None)
        url, headers = self._endpoint("messages"), self._auth_headers()
        if on_token is None:
            return self._parse(self.transport.post_json(url, payload, headers))
        blocks, fragments = {}, {}
        data = {"content": [], "usage": {}}
        complete = False
        for line in self.transport.stream_lines(url, payload, headers):
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:])
            except ValueError:
                raise ProviderResponseError("Malformed Anthropic stream.") from None
            kind = event.get("type")
            index = event.get("index", 0)
            if kind == "error":
                raise ProviderResponseError("Anthropic stream returned an API error.")
            if kind == "message_start":
                data["usage"].update(event["message"].get("usage", {}))
            elif kind == "content_block_start":
                blocks[index] = event["content_block"]
            elif kind == "content_block_delta":
                delta = event["delta"]
                if delta["type"] == "text_delta":
                    text = delta["text"]
                    blocks[index]["text"] = blocks[index].get("text", "") + text
                    on_token(text)
                elif delta["type"] == "input_json_delta":
                    fragments[index] = fragments.get(index, "") + delta["partial_json"]
            elif kind == "message_delta":
                data.update(event.get("delta", {}))
                data["usage"].update(event.get("usage", {}))
            elif kind == "message_stop":
                complete = True
                break
        if not complete:
            raise ProviderResponseError("Anthropic stream ended before completion.")
        for index, raw in fragments.items():
            try:
                blocks[index]["input"] = json.loads(raw)
            except ValueError:
                raise ProviderResponseError("Invalid Anthropic tool arguments.") from None
        data["content"] = [blocks[i] for i in sorted(blocks)]
        return self._parse(data)
