# PitchFight AI V2 — Model Abstraction

## Big Idea

```
PromptBuilder
    ↓
BuiltPrompt
    ↓
ModelRouter
    ↓
ModelClient
    ↓
Provider
```

Application code never writes `if provider == "nvidia": ... elif provider == "openai": ...`. It asks `ModelRouter` for a client by logical alias (e.g. `"default"`), then calls `client.generate(request)`. Which real provider sits behind that alias is a configuration detail, not a code branch.

Today the only registered provider is `FakeModelClient` — deterministic, no network, no GPU. A later phase adds a real provider (NVIDIA Nemotron via vLLM/Modal). Nothing above this layer — `PromptBuilder`, `SimulationService`, business logic — has to change when that happens.

## ModelClient

**"How we talk to any model."**

```python
class ModelClient(ABC):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
```

One `ModelClient` instance = one already-configured provider + model. It doesn't choose between providers (that's `ModelRouter`'s job) and it doesn't know anything about pitches, judges, difficulty, rounds, deals, or scoring — only prompts in, a response out. Always async, since real inference is network-bound.

## ModelRouter

**"Which registered model client should handle this request."**

```python
router = ModelRouter(default_alias="fake")
router.register("fake", FakeModelClient())

client = router.get_client()        # uses default_alias
client = router.get_client("fake")  # explicit alias
```

Registration is explicit — no scanning `app/ai/providers/` for classes. An unknown alias raises `ModelConfigurationError`. Registering the same alias twice raises unless you pass `replace=True` — that's a deliberate act, not an accident. The router only resolves aliases to clients; it doesn't build prompts, touch Mongo/Redis, retry failed calls, or fall back to another provider on failure. Retry and fallback policy belongs to a future orchestration layer, once there's more than one real provider to decide between.

## ModelRequest

Provider-neutral — no OpenAI message IDs, no Anthropic blocks, no Nemotron chat-template tokens.

| Field | Meaning |
|---|---|
| `system_prompt`, `user_prompt` | From `BuiltPrompt` |
| `temperature`, `max_tokens`, `top_p` | Generation options (all optional; validated — e.g. `max_tokens` must be `> 0`, `top_p` in `[0, 1]`) |
| `timeout_seconds` | Advisory. A provider client decides how to honor it later — nothing enforces it yet, since there's no network provider in this phase |
| `response_format` | `TEXT` or `JSON` — "return structured JSON" is a request, not JSON-schema enforcement. The provider decides how best to satisfy it |
| `metadata` | Passthrough (e.g. `judge_config_version`, `difficulty`, `task` from `BuiltPrompt.metadata`) |

`build_model_request(built_prompt, **overrides)` (in `app/ai/model_client.py`) converts a Phase 10 `BuiltPrompt` into a `ModelRequest`. It lives outside `prompt_builder.py` on purpose — `PromptBuilder` stays completely unaware that providers or `ModelClient` exist.

## ModelResponse

| Field | Meaning |
|---|---|
| `content` | The model's raw text output |
| `provider`, `model` | e.g. `"fake"` / `"fake-model-v1"`, later `"vllm"` / `"nvidia/NVIDIA-Nemotron-..."` — enables logging, benchmarking, tracing without callers knowing implementation details |
| `usage` | `TokenUsage(input_tokens, output_tokens, total_tokens)` — any field is `None` if a provider doesn't report it. Never fabricated |
| `latency_ms`, `request_id` | Observability hooks |
| `raw_metadata` | Optional diagnostics escape hatch — never the primary way callers read output |

## FakeModelClient

Why: tests and offline development need to exercise the whole prompt → request → response path without a GPU, network access, or provider credentials.

```python
client = FakeModelClient(response_content='{"question": "Why now?"}')
response = await client.generate(request)
```

It records `last_request` and `call_count` for assertions, can simulate latency (`simulated_latency_seconds`), and can simulate a failure by raising any model-layer error you configure (`fail_with=ModelTimeoutError`, `ModelUnavailableError`, etc.) — one parameter, not three separate boolean flags.

## Why This Matters

**Today:** `ModelRouter` → `FakeModelClient` → canned response. `MODEL_DEFAULT_ALIAS=fake` in settings, no external credentials anywhere.

**Later (Phase 12):** register a real provider client (NVIDIA Nemotron via vLLM/Modal) under an alias, point `MODEL_DEFAULT_ALIAS` at it. `PromptBuilder`, `SimulationService`, and everything downstream of `ModelRequest`/`ModelResponse` doesn't change — only which `ModelClient` is behind the alias does.
