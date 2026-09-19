# Inference — Standalone Model Serving (Phase 12A)

## Architecture

```
FastAPI backend (later, Phase 12B)
        v
      Modal
        v
      vLLM
        v
    Nemotron
```

**Phase 12A only tests the bottom three layers, standalone:**

```
Modal (H100)  ->  vLLM  ->  Nemotron  ->  OpenAI-compatible HTTP API
```

Nothing in `backend/app/ai/` talks to this yet. That integration is Phase 12B, after this server is proven to work on its own.

## Model

| | |
|---|---|
| Model | `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` |
| Revision | `main` (not yet pinned to a commit sha — see [PHASE_12A_RESULTS.md](./PHASE_12A_RESULTS.md)) |
| Served name | `pitchfight-nemotron` |
| GPU | 1 × H100 (no tensor parallelism, no multi-replica) |
| vLLM | `vllm/vllm-openai:v0.27.1` (official NVIDIA/vLLM day-0 recipe image) |
| Context length | 32768 tokens (product decision — the model supports up to ~1M; PitchFight doesn't need it, and a smaller context means less KV-cache memory and more GPU headroom) |
| Max concurrent sequences | 32 (NVIDIA's published recipe uses 256, tuned for batch throughput; PitchFight needs interactive latency, not batch throughput — see [PHASE_12A_RESULTS.md](./PHASE_12A_RESULTS.md) for benchmark-informed tuning) |
| Speculative decoding | OFF (stable baseline first) |

All of the above is centralized in `config.py` — no magic strings scattered across files.

## Cache volumes

- `pitchfight-hf-cache` → `/root/.cache/huggingface` (downloaded model weights)
- `pitchfight-vllm-cache` → `/root/.cache/vllm` (vLLM JIT/compile artifacts)

First cold boot downloads ~20+ GB of weights into these. Every later container reuses them instead of re-downloading.

## Secret

The server uses the existing Modal secret **`huggingface-secret`** (name only — never its value) to inject `HF_TOKEN` into the container. Nothing in this codebase prints, logs, or stores that token.

## Security

This server does **not** set `unauthenticated=True`. Modal's proxy authentication stays on, so requests need a **Proxy Auth Token**. Generate one for your workspace:

```bash
modal workspace proxy-tokens create
```

This prints a `wk-...` / `ws-...` pair. Export them before running the test scripts (never commit or print them elsewhere):

```bash
export MODAL_KEY=wk-...
export MODAL_SECRET=ws-...
```

`smoke_test.py` and `benchmark.py` send these as the `Modal-Key` / `Modal-Secret` request headers.

## Developer commands

All commands assume the Modal CLI is installed and authenticated (`modal profile current` should show your workspace).

```bash
# Deploy (starts consuming GPU credits once a request arrives — scale-to-zero when idle)
modal deploy inference/modal_app.py

# Tail logs
modal app logs pitchfight-nemotron-inference

# Stop / tear down the deployment
modal app stop pitchfight-nemotron-inference

# After deploying, run the smoke test against the printed URL
python inference/smoke_test.py https://<your-workspace>--pitchfight-nemotron-inference-server.modal.run

# Then a small latency benchmark (5 requests by default)
python inference/benchmark.py https://<your-workspace>--pitchfight-nemotron-inference-server.modal.run 5
```

Install script dependencies locally (isolated from the backend venv):

```bash
pip install -r inference/requirements.txt
```

## Cold start vs. warm latency

These are two very different numbers — don't mix them up:

- **Cold start** = time for a fresh container to boot, download/load the model, and start accepting requests. Can be several minutes, especially the very first deploy before the cache volumes are warm. This is why `startup_timeout` is set to 20 minutes, not 30 seconds.
- **Warm latency** = time for one request against an already-running server. This is what `benchmark.py` measures. It explicitly excludes the warmup request and never conflates the two.

## Scope of Phase 12A

This directory implements **only** standalone model serving: the Modal app, the vLLM server configuration, cache volumes, a smoke test, and a benchmark script. It does **not**:

- connect to PitchFight's `ModelClient`/`ModelRouter` (that's `backend/app/ai/`, untouched)
- implement scoring, the AI orchestrator, or any simulation logic
- require Postgres, MongoDB, or Redis
- download any weights onto your local machine, or require a local GPU

See [PHASE_12A_RESULTS.md](./PHASE_12A_RESULTS.md) for deployment/benchmark results once the server has been deployed and tested.
