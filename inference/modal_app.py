"""Standalone Modal + vLLM inference server for PitchFight's first real
model (Phase 12A).

    Modal H100
        v
    vLLM (official vllm/vllm-openai:v0.27.1 image)
        v
    nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4
        v
    OpenAI-compatible HTTP API (/v1/models, /v1/chat/completions)

Deliberately standalone: nothing in backend/ talks to this yet. Phase 12B
adds a VLLMModelClient behind backend/app/ai/model_client.py once this
server is proven to work on its own.

Deploy:
    modal deploy inference/modal_app.py

Logs:
    modal app logs pitchfight-nemotron-inference

Stop (scale down / tear down the deployment):
    modal app stop pitchfight-nemotron-inference

See inference/README.md for the full command reference and how to
authenticate a client against this server (Modal proxy auth stays ON —
see the `unauthenticated` note below).
"""

import subprocess

import modal

from config import (
    APP_NAME,
    GPU,
    HF_CACHE_MOUNT_PATH,
    HF_CACHE_VOLUME_NAME,
    HF_SECRET_NAME,
    MAX_MODEL_LEN,
    MAX_NUM_BATCHED_TOKENS,
    MAX_NUM_SEQS,
    MODEL_ID,
    MODEL_REVISION,
    SCALEDOWN_WINDOW_SECONDS,
    SERVED_MODEL_NAME,
    STARTUP_TIMEOUT_SECONDS,
    VLLM_CACHE_MOUNT_PATH,
    VLLM_CACHE_VOLUME_NAME,
    VLLM_IMAGE_TAG,
    VLLM_PORT,
)

# ---------------------------------------------------------------------------
# Container image — the official NVIDIA/vLLM-validated image for this exact
# model + vLLM version (see config.py for why). Its own ENTRYPOINT is
# cleared so Modal can run its container lifecycle (@modal.enter/@modal.exit)
# instead of the image immediately launching vLLM itself.
# ---------------------------------------------------------------------------

vllm_image = (
    modal.Image.from_registry(VLLM_IMAGE_TAG)
    .entrypoint([])
    .run_commands("ln -sf $(which python3) /usr/bin/python")
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",  # faster weight downloads into the cache volume
            # Required for this model's Humming MoE kernels.
            # https://docs.vllm.ai/en/latest/configuration/env_vars/
            "VLLM_HUMMING_MOE_GEMM_TYPE": "indexed",
        }
    )
    # Modal only auto-mounts modal_app.py itself into the remote container,
    # not sibling local modules — without this, `from config import ...`
    # below fails remotely with ModuleNotFoundError even though it imports
    # fine locally. This mounts inference/config.py onto the container's
    # PYTHONPATH at /root/config.py so the existing import works unchanged.
    .add_local_python_source("config")
)

# ---------------------------------------------------------------------------
# Persistent caches — first cold boot downloads weights into these; later
# containers reuse them instead of re-downloading ~20+ GB every start.
# ---------------------------------------------------------------------------

hf_cache_volume = modal.Volume.from_name(HF_CACHE_VOLUME_NAME, create_if_missing=True)
vllm_cache_volume = modal.Volume.from_name(VLLM_CACHE_VOLUME_NAME, create_if_missing=True)

app = modal.App(APP_NAME)


@app.server(
    image=vllm_image,
    gpu=GPU,
    secrets=[modal.Secret.from_name(HF_SECRET_NAME)],  # injects HF_TOKEN only — value never touches our code
    volumes={
        HF_CACHE_MOUNT_PATH: hf_cache_volume,
        VLLM_CACHE_MOUNT_PATH: vllm_cache_volume,
    },
    port=VLLM_PORT,
    startup_timeout=STARTUP_TIMEOUT_SECONDS,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    # Cost safety: min_containers is left unset (defaults to 0 — true
    # scale-to-zero when idle) and max_containers is capped at exactly 1,
    # so this can never accidentally scale out to a second H100 replica.
    max_containers=1,
    # unauthenticated defaults to False — Modal proxy authentication stays
    # required. See inference/README.md for how smoke_test.py/benchmark.py
    # authenticate against it.
)
class Server:
    @modal.enter()
    def start(self) -> None:
        cmd = [
            "vllm",
            "serve",
            MODEL_ID,
            "--revision",
            MODEL_REVISION,
            "--served-model-name",
            SERVED_MODEL_NAME,
            "--host",
            "0.0.0.0",
            "--port",
            str(VLLM_PORT),
            "--tensor-parallel-size",
            "1",
            "--max-model-len",
            str(MAX_MODEL_LEN),
            "--max-num-seqs",
            str(MAX_NUM_SEQS),
            "--max-num-batched-tokens",
            str(MAX_NUM_BATCHED_TOKENS),
            "--enable-prefix-caching",
            # NVIDIA-recommended H100 serving path for this model's hybrid
            # Mamba+MoE architecture. See inference/PHASE_12A_RESULTS.md
            # for the sources these flags were verified against.
            "--mamba-backend",
            "flashinfer",
            "--moe-backend",
            "humming",
            "--linear-backend",
            "humming",
            "--mamba-ssu-algorithm",
            "horizontal",
            "--mamba-cache-mode",
            "align",
            "--mamba-ssm-cache-dtype",
            "float16",
            "--enable-mamba-cache-stochastic-rounding",
            "--mamba-cache-philox-rounds",
            "5",
            "--reasoning-parser",
            "nemotron_v3",
            # Deliberately NOT included:
            #   --enable-auto-tool-choice / --tool-call-parser
            #       (PitchFight doesn't need tool calling yet)
            #   --speculative-config / DSpark / DFlash / MTP
            #       (stable baseline first — see config.py)
        ]
        print("Starting vLLM:", " ".join(cmd))
        self.process = subprocess.Popen(cmd)

    @modal.exit()
    def stop(self) -> None:
        self.process.terminate()
