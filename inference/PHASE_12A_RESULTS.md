# Phase 12A Results — Standalone Model Serving

Status: **deployment validated successfully.**

## Architecture

```
Modal (1x H100)  ->  vLLM 0.27.1  ->  Nemotron 3.5 Lightning  ->  OpenAI-compatible HTTP API
```

Standalone only — nothing in `backend/app/ai/` talks to this server yet. That integration is Phase 12B, which has not started.

## Configuration

| | |
|---|---|
| Model | `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` |
| Served name | `pitchfight-nemotron` |
| GPU | 1 × H100 |
| vLLM | 0.27.1 (official `vllm/vllm-openai:v0.27.1` image) |
| max_model_len | 32768 |
| max_num_seqs | 32 |
| Speculative decoding | OFF |

No deployment configuration changed to produce these results — see `config.py` and `modal_app.py` for the full flag set.

## Deployment

**Success.** The Modal H100 container started, vLLM loaded Nemotron successfully, and the model was reachable through the OpenAI-compatible API.

## Smoke test

| Check | Result |
|---|---|
| `GET /v1/models` | PASS |
| Basic chat completion | PASS |
| JSON structured output | PASS |
| Skeptical VC persona sanity | PASS |
| Technical Judge persona sanity | PASS |
| Hackathon Judge persona sanity | PASS |

All required and optional Phase 12A checks passed.

## JSON test

Nemotron reliably returned a single parseable JSON object with the expected fields (`question`, `attack_tag`, `is_follow_up`) for the simple structured-output prompt, using plain instruction-following (no constrained/guided decoding). This is consistent with how Phase 10's `PromptBuilder` currently asks for structured output.

## Persona sanity results

All three locked personas (Skeptical VC, Technical Judge, Hackathon Judge) produced coherent, on-persona, single-question output against the tiny mock pitch prompt in `smoke_test.py`. This used simple inline system prompts, not the full `PromptBuilder`/prompt system — it only confirms basic model behavior, not production prompt quality.

## Important serving discovery: thinking mode

**Nemotron 3.5 has "thinking" (reasoning) enabled by default.** With a small `max_tokens` budget, the reasoning channel consumed the entire budget before any final content was produced, so responses came back with `finish_reason="length"` and **empty content** — across the basic chat test, the JSON test, and all three persona checks.

Fix: every normal Phase 12A interactive request explicitly disables thinking via vLLM's chat-template passthrough:

```python
extra_body={
    "chat_template_kwargs": {
        "enable_thinking": False
    }
}
```

This is now applied in `smoke_test.py` (3 call sites: basic chat, JSON test, persona loop) and `benchmark.py` (1 call site, covering both the warmup and every measured request). Without it, PitchFight's small, interactive judge-turn output budgets would silently produce empty responses.

## Benchmark (warm latency only)

Cold-start (container boot + model load) is a **separate, one-time cost** and is intentionally **not** part of these numbers — see "Cold start vs. warm latency" below.

| Metric | Value |
|---|---|
| Warmup latency (excluded from stats) | 1.30s |
| Requests measured | 5/5 succeeded |
| Average latency | 0.39s |
| Min latency | 0.36s |
| Max latency | 0.41s |
| Aggregate output throughput | ~58.2 tokens/sec |

`max_num_seqs=32` (vs. NVIDIA's throughput-tuned 256) has not shown any latency problems at this request volume — no further tuning was needed for Phase 12A's purposes.

## Cold start vs. warm latency

These are two different numbers and are not mixed together anywhere in this document:

- **Cold start** = time for a fresh container to boot, download/load the model, and begin accepting requests. This can take several minutes, especially before the cache volumes (`pitchfight-hf-cache`, `pitchfight-vllm-cache`) are warm. `startup_timeout` is configured generously (20 minutes) to accommodate this.
- **Warm latency** = the benchmark numbers above — time for a single request against an already-running server, with the model already loaded.

## Known follow-ups (not part of Phase 12A)

- `MODEL_REVISION` is still `main`, not pinned to a commit sha (see `config.py` — the resolved hash during planning came from an AI-summarized fetch and wasn't trusted for a paid GPU deployment).
- No errors or issues were observed during this validation pass beyond the thinking-mode discovery above, which has been fixed in both test scripts.
