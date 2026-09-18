"""FakeModelClient — deterministic in-process ModelClient.

No GPU, no network, no external credentials. Used for tests, offline
development, and future Simulation/AI integration work before a real
provider (Phase 12) exists.
"""

import asyncio
import time
import uuid

from app.ai.model_client import ModelClient
from app.ai.schemas import ModelRequest, ModelResponse, TokenUsage

DEFAULT_PROVIDER = "fake"
DEFAULT_MODEL = "fake-model-v1"


class FakeModelClient(ModelClient):
    """Returns a configured, deterministic response.

    Records the last request and a call count for test assertions. Can
    optionally simulate latency or a failure (timeout/unavailable/malformed
    — pass the exception class you want raised, e.g. `fail_with=ModelTimeoutError`).
    """

    def __init__(
        self,
        *,
        response_content: str = '{"question": "What evidence supports that claim?"}',
        provider: str = DEFAULT_PROVIDER,
        model: str = DEFAULT_MODEL,
        usage: TokenUsage | None = None,
        simulated_latency_seconds: float = 0.0,
        fail_with: type[Exception] | None = None,
    ) -> None:
        self.response_content = response_content
        self.provider = provider
        self.model = model
        self.usage = usage if usage is not None else TokenUsage()
        self.simulated_latency_seconds = simulated_latency_seconds
        self.fail_with = fail_with

        self.last_request: ModelRequest | None = None
        self.call_count = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.last_request = request
        self.call_count += 1

        start = time.perf_counter()
        if self.simulated_latency_seconds:
            await asyncio.sleep(self.simulated_latency_seconds)

        if self.fail_with is not None:
            raise self.fail_with("Simulated failure from FakeModelClient")

        latency_ms = (time.perf_counter() - start) * 1000

        return ModelResponse(
            content=self.response_content,
            provider=self.provider,
            model=self.model,
            finish_reason="stop",
            usage=self.usage,
            latency_ms=latency_ms,
            request_id=str(uuid.uuid4()),
            raw_metadata={"fake": True},
        )
