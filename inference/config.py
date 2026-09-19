"""Centralized configuration for PitchFight's standalone Modal + vLLM
inference deployment (Phase 12A).

Deliberately isolated from backend/ — inference dependencies (vLLM, CUDA,
Modal) never get installed into the backend virtualenv, and nothing in
backend/app/ imports from here yet. Backend integration is Phase 12B.
"""

# --- Modal app -------------------------------------------------------------

APP_NAME = "pitchfight-nemotron-inference"

# --- Model -------------------------------------------------------------------

MODEL_ID = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"

# TODO: pin an exact commit sha once the deployment is confirmed stable.
# "main" is used for this first deployment: a commit hash resolved during
# planning came back through an AI-summarized web fetch and could not be
# independently verified byte-for-byte, so it wasn't trusted for a paid
# GPU deployment. See inference/PHASE_12A_RESULTS.md.
MODEL_REVISION = "main"

SERVED_MODEL_NAME = "pitchfight-nemotron"

# The official NVIDIA/vLLM day-0 recipe image for this exact model + vLLM
# version — not a from-scratch pip install. This model's hybrid Mamba+MoE
# architecture depends on kernel libraries (Humming, FlashInfer) whose
# versions are tightly matched to this tag; building our own image risks a
# subtle version mismatch for a "stable baseline first" goal.
# https://vllm.ai/blog/2026-08-10-nemotron-3-5-lightning-vllm
# https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4
VLLM_IMAGE_TAG = "vllm/vllm-openai:v0.27.1"

# --- Context / concurrency — product decisions, not NVIDIA's defaults ------

# The model supports up to ~1M tokens of context. PitchFight doesn't need
# anywhere close to that for a pitch simulation — 32768 keeps KV-cache
# memory small and GPU headroom large for this first deployment.
MAX_MODEL_LEN = 32768

# NVIDIA's published max-throughput recipe uses max-num-seqs=256, tuned for
# batch throughput. PitchFight needs interactive latency, not batch
# throughput — start much lower and tune up later from real benchmark data.
MAX_NUM_SEQS = 32

# Kept from the official recipe's batched-token budget. Safe to leave as-is
# since MAX_MODEL_LEN here is already far smaller than the recipe's context.
MAX_NUM_BATCHED_TOKENS = 16384

# --- GPU / infra -------------------------------------------------------------

GPU = "H100"  # exactly one GPU — no tensor parallelism, no multi-replica.
VLLM_PORT = 8000

HF_SECRET_NAME = "huggingface-secret"  # Modal Secret NAME only — never the value.

HF_CACHE_VOLUME_NAME = "pitchfight-hf-cache"
VLLM_CACHE_VOLUME_NAME = "pitchfight-vllm-cache"

HF_CACHE_MOUNT_PATH = "/root/.cache/huggingface"
VLLM_CACHE_MOUNT_PATH = "/root/.cache/vllm"

# First cold boot downloads ~20+ GB of weights, then loads/compiles them —
# budget generously so a slow download doesn't get killed mid-way.
STARTUP_TIMEOUT_SECONDS = 20 * 60

# Development deployment: scale to zero after this long with no requests.
SCALEDOWN_WINDOW_SECONDS = 10 * 60

# Kept off for this phase — see inference/PHASE_12A_RESULTS.md. Benchmark
# and reconsider later if warm latency needs to improve.
SPECULATIVE_DECODING_ENABLED = False
