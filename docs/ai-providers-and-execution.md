# AI providers and execution

Provider settings belong to the user, outside project documents and agent tools.
Each profile has its own endpoint, model, credential reference, optional environment
variable, capability overrides, and connection timeouts. A saved secure credential
takes precedence over that profile's explicitly named environment variable. No
environment variable is implicitly shared between profiles.

## Connections

- **Ollama Cloud:** choose Ollama / Cloud, `https://ollama.com`, a hosted model such
  as `gemma4:31b`, and a secure API key or the environment variable `OLLAMA_API_KEY`.
  The adapter posts to `/api/chat` with `Authorization: Bearer …`.
- **Ollama Local:** `http://localhost:11434`, without a required key. Custom secured
  Ollama proxies can also use a Bearer key. Custom mode preserves the supplied URL.
- **OpenAI-compatible:** OpenAI, OpenRouter, LM Studio, vLLM, and compatible company
  gateways use chat completions. A bare host receives `/v1`; an existing API path is
  preserved. Custom authentication header names use the same secure key storage.
- **Anthropic:** native `/v1/messages`, `x-api-key`, version header, typed content
  blocks, and its own SSE parser.
- **Hugging Face:** the dedicated adapter targets the inference router's documented
  OpenAI-compatible chat API at `https://router.huggingface.co/v1`.
- **Google:** the dedicated compatibility adapter uses
  `https://generativelanguage.googleapis.com/v1beta/openai`.

Model discovery is optional. Manual model names are always usable. Test Connection
performs an actual completion against the selected profile, on a background worker.
Refresh Models also runs in the background. Diagnostics never display credentials.
Native tool names are encoded for APIs that prohibit dots, then decoded back to the
editor's registry names before execution.

Unknown Ollama and Hugging Face models conservatively use the validated JSON tool
protocol. Users can explicitly enable native tools for a supporting model. Ollama
Cloud does not receive the local API's structured-output `format` option.

The shared transport verifies TLS, uses system proxy configuration, blocks redirects,
checks cancellation, and bounds connection, request, and stream-idle waits. Remote
HTTP with credentials requires an explicit acknowledgement in settings. Verbose
HTTP logging includes routing metadata and redacted header values, not message bodies.
Windows credential encryption fails closed if DPAPI cannot protect a new vault key.

## Execution contract

The session owns an `AgentTask` across turns. It records the objective, intent,
status, discovery results, planned steps, successful edits, failures, and completion
reason. Discovery caching covers immutable node-type queries; it is invalidated
when the live node registry changes. Graph inspections are not cached.

Planning or future-tense narration cannot finish a run. Edit requests require actual
transaction commands and successful graph validation. Known requirements such as
creation, configuration, and insertion connections are checked by the host. The
`task.plan` control tool records remaining operations, which only successful tool
calls can complete. `task.request_input` pauses for essential missing information.
Follow-ups retain discoveries, proposals, and the last affected nodes.

The host does not prove every natural-language objective mathematically. Intent
classification and operation matching are conservative heuristics; tests use scripted
model replies to verify runtime behavior independently of a particular model's quality.
No model's declaration of success substitutes for successful commands and validation.

All changes in one run form one undo transaction. Provider errors, invalid protocol,
unrepaired validation, cancellation, and exhausted limits roll back incomplete work.
Existing Assist/Agent permissions and approval policies remain enforced. Final text
appears after transaction resolution; activity cards show live authoritative tool
results. Double-click a card to focus its affected nodes. Retry uses the original
user request and conversation snapshot, including when the provider changes.

The default run budget is 48 model steps, with 192 tool calls and a ten-minute task
budget. There are at most four unsuccessful prose-only continuation attempts.
Developer diagnostics report intent, steps, tools, successful edits, validation,
pending work, and the completion reason.

## Verification

Run `python -m pytest tests/test_ai_execution.py tests/test_ai_providers.py tests/test_ai_ui.py`.
Set `QT_QPA_PLATFORM=offscreen` for headless UI tests. Provider tests mock HTTP;
live hosted credentials and model availability are checked using Test Connection.

Protocol references: [Ollama authentication](https://docs.ollama.com/api/authentication),
[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[Anthropic streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
[Hugging Face chat](https://huggingface.co/docs/inference-providers/main/en/tasks/chat-completion),
[Google compatibility](https://ai.google.dev/gemini-api/docs/openai).
