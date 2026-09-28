import io
import json
import threading
import time
import urllib.error
from unittest.mock import Mock
import pytest
from ai.providers.registry import create_provider
from ai.providers.base import ChatRequest, Transport, _NoRedirect
from ai.providers.urls import validate_url
from ai.settings import ProviderConfig
from ai.types import ChatMessage
from ai.errors import ProviderAuthError, ProviderError, CancelledError


@pytest.mark.parametrize("base,expected", [
    ("https://ollama.com", "https://ollama.com/api/chat"),
    ("https://ollama.com/", "https://ollama.com/api/chat"),
    ("https://ollama.com/api", "https://ollama.com/api/chat"),
    ("https://example.internal/ollama/", "https://example.internal/ollama/api/chat")])
def test_ollama_exact_regression(base, expected):
    config = ProviderConfig("cloud", "Ollama Cloud", kind="ollama", base_url=base, model="gemma4:31b")
    provider = create_provider(config, credentials=Mock(get=Mock(return_value="TEST_API_KEY")))
    provider.transport.post_json = Mock(return_value={"message": {"content": "Hello!"}, "done": True})
    provider.generate(ChatRequest(model=config.model, messages=[ChatMessage(role="user", content="Hello!")]))
    url, body, headers = provider.transport.post_json.call_args.args
    assert url == expected
    assert headers == {"Authorization": "Bearer TEST_API_KEY"}
    assert body["model"] == "gemma4:31b" and body["stream"] is False
    assert body["messages"] == [{"role": "user", "content": "Hello!"}]
    assert "TEST_API_KEY" not in json.dumps(body)


def test_local_key_optional_and_custom_key_allowed():
    provider = create_provider(ProviderConfig("local", "Local", kind="ollama", base_url="http://localhost:11434", is_local=True))
    assert provider._auth_headers() == {} and provider.is_local
    provider.api_key = "proxy-key"
    assert provider._auth_headers()["Authorization"] == "Bearer proxy-key"


@pytest.mark.parametrize("kind,base,url,header", [
    ("openai_compatible", "http://localhost:1234", "http://localhost:1234/v1/chat/completions", "Authorization"),
    ("openai_compatible", "http://localhost:1234/v1/", "http://localhost:1234/v1/chat/completions", "Authorization"),
    ("huggingface", "https://router.huggingface.co/v1", "https://router.huggingface.co/v1/chat/completions", "Authorization"),
    ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "Authorization"),
    ("anthropic", "https://api.anthropic.com/v1", "https://api.anthropic.com/v1/messages", "x-api-key"),
    ("openai_compatible", "https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions", "Authorization")])
def test_all_provider_wire_formats(kind, base, url, header):
    provider = create_provider(ProviderConfig(kind, kind, kind=kind, base_url=base), credentials=Mock(get=Mock(return_value="test-key")))
    reply = {"content": [{"type": "text", "text": "ok"}]} if kind == "anthropic" else {"choices": [{"message": {"content": "ok"}}]}
    provider.transport.post_json = Mock(return_value=reply)
    response = provider.generate(ChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")]))
    args = provider.transport.post_json.call_args.args
    assert args[0] == url and header in args[2] and response.content == "ok"
    if kind == "anthropic":
        assert "Authorization" not in args[2]
        assert args[2]["anthropic-version"] == "2023-06-01"
        assert args[1]["messages"][0]["content"] == [{"type": "text", "text": "hi"}]


def test_ollama_stream_retains_early_tool_calls():
    provider = create_provider(ProviderConfig("o", "O", kind="ollama", base_url="https://ollama.com"))
    provider.transport.stream_lines = Mock(return_value=iter([
        json.dumps({"message": {"content": "Hi", "tool_calls": [{"function": {"name": "node.create", "arguments": {"type": "Color Grading"}}}]}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "eval_count": 3})]))
    result = provider.generate(ChatRequest(model="test", messages=[]), on_token=lambda text: None)
    assert result.tool_calls[0].name == "node.create" and result.content == "Hi"
    assert result.usage.completion_tokens == 3


def test_connection_failure_cannot_be_masked_by_manual_model():
    provider = create_provider(ProviderConfig("o", "O", kind="ollama", base_url="https://ollama.com", model="manual"))
    provider.transport.post_json = Mock(side_effect=ProviderAuthError("HTTP 401"))
    assert not provider.test_connection().ok
    assert "401" in provider.test_connection().message


def test_environment_precedence_is_profile_specific(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "env-key")
    config = ProviderConfig("a", "A", kind="ollama", credential_env="OLLAMA_API_KEY")
    assert create_provider(config).api_key == "env-key"
    assert create_provider(config, credentials=Mock(get=Mock(return_value="stored"))).api_key == "stored"
    assert create_provider(ProviderConfig("b", "B", kind="ollama")).api_key == ""
    assert "env-key" not in json.dumps(config.to_dict())


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://key@example.com", "https://example.com?key=secret", "https://example.com/#secret", "https://example.com:bad"])
def test_reject_unsafe_urls(url):
    with pytest.raises(ProviderError):
        validate_url(url)


def test_remote_http_guard_and_redirect():
    with pytest.raises(ProviderAuthError):
        Transport()._request("http://remote.example/api/chat", {}, {"Authorization": "Bearer test-key"})
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example") is None


def test_http_errors_redact_provider_echoes():
    error = urllib.error.HTTPError("https://test", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad TEST_SECRET"}'))
    result = Transport._http_error(error, {"Authorization": "Bearer TEST_SECRET"})
    assert "401" in str(result) and "TEST_SECRET" not in str(result)


def test_cancel_pending_network_request():
    transport = Transport()
    release = threading.Event()
    def open_request(*args, **kwargs):
        release.wait(2)
        raise OSError()
    transport.opener.open = open_request
    transport.should_stop = lambda: True
    start = time.monotonic()
    try:
        with pytest.raises(CancelledError):
            transport.post_json("https://test.example", {})
        assert time.monotonic() - start < .5
    finally:
        release.set()


@pytest.mark.parametrize("kind", ["openai_compatible", "huggingface", "google"])
def test_compatible_sse_tool_argument_fragments(kind):
    provider = create_provider(ProviderConfig("test", "Test", kind=kind, base_url="https://example.com/v1"))
    events = [
        {"choices": [{"delta": {"content": "Hi", "tool_calls": [{"index": 0, "id": "c1", "function": {"name": "node.create", "arguments": '{"type":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"Color Grading"}'}}]}, "finish_reason": "tool_calls"}]},
    ]
    provider.transport.stream_lines = Mock(return_value=iter(["data: " + json.dumps(e) for e in events] + ["data: [DONE]"]))
    response = provider.generate(ChatRequest(model="test", messages=[]), on_token=lambda _: None)
    assert response.content == "Hi"
    assert response.tool_calls[0].arguments == {"type": "Color Grading"}


def test_anthropic_stream_text_tools_and_usage():
    provider = create_provider(ProviderConfig("test", "Test", kind="anthropic", base_url="https://api.anthropic.com/v1"))
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "c1", "name": "node.create", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"type":"Color Grading"}'}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    provider.transport.stream_lines = Mock(return_value=iter("data: " + json.dumps(e) for e in events))
    response = provider.generate(ChatRequest(model="test", messages=[]), on_token=lambda _: None)
    assert response.content == "Hi" and response.usage.total_tokens == 15
    assert response.tool_calls[0].arguments == {"type": "Color Grading"}


@pytest.mark.parametrize("kind", ["ollama", "anthropic", "openai_compatible", "google", "huggingface"])
def test_truncated_stream_never_returns_partial_success(kind):
    from ai.errors import ProviderResponseError
    provider = create_provider(ProviderConfig("test", "Test", kind=kind, base_url="https://example.com"))
    provider.transport.stream_lines = Mock(return_value=iter([]))
    with pytest.raises(ProviderResponseError):
        provider.generate(ChatRequest(model="test", messages=[]), on_token=lambda _: None)


def test_secure_storage_and_custom_auth_isolation(tmp_path):
    from ai.credentials import CredentialStore
    store = CredentialStore(tmp_path)
    store.set("ai.a", "TEST_PRIVATE_SECRET")
    a = ProviderConfig("a", "A", auth_header="X-API-Key")
    b = ProviderConfig("b", "B")
    assert create_provider(a, credentials=store)._auth_headers() == {"X-API-Key": "TEST_PRIVATE_SECRET"}
    assert create_provider(b, credentials=store)._auth_headers() == {}
    assert "TEST_PRIVATE_SECRET" not in json.dumps(a.to_dict())
    for file in tmp_path.iterdir():
        assert b"TEST_PRIVATE_SECRET" not in file.read_bytes()


def test_no_secret_headers_can_be_serialized():
    config = ProviderConfig("a", "A", extra_headers={"Authorization": "Bearer private"})
    with pytest.raises(ValueError, match="secure"):
        config.to_dict()


def test_remote_ollama_cannot_be_marked_local():
    config = ProviderConfig("a", "A", kind="ollama", base_url="https://ollama.com", is_local=True)
    assert config.scope == "CLOUD" and not create_provider(config).is_local


@pytest.mark.parametrize("kind", ["anthropic", "openai_compatible", "huggingface", "google"])
def test_native_tool_names_roundtrip_without_changing_registry_names(kind):
    provider = create_provider(ProviderConfig("test", "Test", kind=kind, base_url="https://example.com/v1"))
    schema = {"type": "function", "function": {"name": "node.create", "parameters": {"type": "object", "properties": {}}}}
    if kind == "anthropic":
        reply = {"content": [{"type": "tool_use", "id": "c1", "name": "node__create", "input": {"type": "Color Grading"}}]}
    else:
        reply = {"choices": [{"message": {"tool_calls": [{"id": "c1", "function": {"name": "node__create", "arguments": '{"type":"Color Grading"}'}}]}}]}
    provider.transport.post_json = Mock(return_value=reply)
    response = provider.generate(ChatRequest(model="test", messages=[], tools=[schema]))
    assert response.tool_calls[0].name == "node.create"
    assert schema["function"]["name"] == "node.create"
    body = provider.transport.post_json.call_args.args[1]
    wire_name = body["tools"][0]["name"] if kind == "anthropic" else body["tools"][0]["function"]["name"]
    assert wire_name == "node__create"


def test_ollama_cloud_fallback_does_not_send_unsupported_format():
    provider = create_provider(ProviderConfig("cloud", "Cloud", kind="ollama", base_url="https://ollama.com"))
    provider.transport.post_json = Mock(return_value={"message": {"content": '{"type":"final","text":"ok"}'}})
    provider.generate(ChatRequest(model="gemma4:31b", messages=[], json_mode=True))
    assert "format" not in provider.transport.post_json.call_args.args[1]
    assert not provider.capabilities().supports_json
