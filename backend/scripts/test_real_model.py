"""Manual, one-off live smoke test for the real Modal/vLLM/Nemotron model.

Sends exactly ONE real request through PitchFight's actual backend model
abstraction (ModelRouter -> VLLMModelClient) — not a bespoke HTTP call.
This is deliberately separate from inference/smoke_test.py (Phase 12A,
which tests the Modal endpoint standalone): this script instead proves
that the *backend's* Phase 12B integration works end to end.

MANUAL ONLY.
- Never runs during pytest (lives outside backend/tests/, and pytest.ini's
  testpaths = tests means it would be skipped even if it were discovered).
- Makes a real, billed call to the Modal-hosted GPU endpoint.
- Never prints MODAL_KEY or MODAL_SECRET.

Usage:
    python backend/scripts/test_real_model.py

Requires MODEL_NEMOTRON_BASE_URL, MODEL_NEMOTRON_NAME, MODAL_KEY, and
MODAL_SECRET to be set — via .env or already-exported environment
variables (pydantic-settings reads real env vars regardless of .env
contents, so exporting them in your shell is enough).
"""

import asyncio
import sys
import time

from app.ai.model_client import ModelClient
from app.ai.model_errors import ModelConfigurationError, ModelError
from app.ai.model_router import ModelRouter
from app.ai.providers import VLLMModelClient
from app.ai.schemas import ModelRequest
from app.core.config import settings

SYSTEM_PROMPT = "You are a concise startup pitch judge."
USER_PROMPT = "Ask one sharp question to a founder building an AI study planner."
MAX_TOKENS = 100


def _build_router() -> ModelRouter:
    if not (settings.MODEL_NEMOTRON_BASE_URL and settings.MODAL_KEY and settings.MODAL_SECRET):
        raise ModelConfigurationError(
            "MODEL_NEMOTRON_BASE_URL, MODAL_KEY, and MODAL_SECRET must all be set "
            "(via .env or exported environment variables) to run this script."
        )
    router = ModelRouter(default_alias="nemotron")
    router.register(
        "nemotron",
        VLLMModelClient(
            base_url=settings.MODEL_NEMOTRON_BASE_URL,
            served_model_name=settings.MODEL_NEMOTRON_NAME,
            modal_key=settings.MODAL_KEY,
            modal_secret=settings.MODAL_SECRET,
            default_timeout_seconds=settings.MODEL_REQUEST_TIMEOUT,
        ),
    )
    return router


async def main() -> int:
    try:
        router = _build_router()
    except ModelConfigurationError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    client: ModelClient = router.get_client()
    request = ModelRequest(system_prompt=SYSTEM_PROMPT, user_prompt=USER_PROMPT, max_tokens=MAX_TOKENS)

    print(f"Sending one live request to {settings.MODEL_NEMOTRON_NAME!r} ...")
    start = time.perf_counter()
    try:
        response = await client.generate(request)
    except ModelError as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    elapsed_s = time.perf_counter() - start

    print()
    print("--- Result ---")
    print(f"content: {response.content!r}")
    print(f"finish_reason: {response.finish_reason}")
    print(
        "tokens: "
        f"input={response.usage.input_tokens} "
        f"output={response.usage.output_tokens} "
        f"total={response.usage.total_tokens}"
    )
    if response.latency_ms is not None:
        print(f"reported latency: {response.latency_ms:.1f} ms")
    print(f"wall-clock elapsed: {elapsed_s:.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
