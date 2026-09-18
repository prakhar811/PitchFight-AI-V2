"""FakeModelClient tests: deterministic response, recorded request/call
count, and simulated failure modes. No network, no GPU."""

import inspect

import pytest

from app.ai.model_client import ModelClient
from app.ai.model_errors import ModelTimeoutError, ModelUnavailableError
from app.ai.providers import FakeModelClient
from app.ai.schemas import ModelRequest, TokenUsage


def _request(**overrides) -> ModelRequest:
    defaults = {"system_prompt": "sys", "user_prompt": "usr"}
    defaults.update(overrides)
    return ModelRequest(**defaults)


def test_fake_client_implements_model_client() -> None:
    assert isinstance(FakeModelClient(), ModelClient)


def test_generate_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(FakeModelClient().generate)


async def test_generate_returns_configured_content() -> None:
    client = FakeModelClient(response_content='{"question": "Why now?"}')
    response = await client.generate(_request())
    assert response.content == '{"question": "Why now?"}'


async def test_generate_receives_the_exact_request() -> None:
    client = FakeModelClient()
    request = _request(system_prompt="SYSTEM", user_prompt="USER")
    await client.generate(request)
    assert client.last_request is request


async def test_response_has_provider_and_model_identity() -> None:
    client = FakeModelClient(provider="fake", model="fake-model-v1")
    response = await client.generate(_request())
    assert response.provider == "fake"
    assert response.model == "fake-model-v1"


async def test_configured_usage_round_trips() -> None:
    usage = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    client = FakeModelClient(usage=usage)
    response = await client.generate(_request())
    assert response.usage == usage


async def test_call_count_increments_per_call() -> None:
    client = FakeModelClient()
    await client.generate(_request())
    await client.generate(_request())
    assert client.call_count == 2


async def test_default_usage_is_all_none() -> None:
    client = FakeModelClient()
    response = await client.generate(_request())
    assert response.usage == TokenUsage()


async def test_response_includes_latency_and_request_id() -> None:
    client = FakeModelClient()
    response = await client.generate(_request())
    assert response.latency_ms is not None
    assert response.latency_ms >= 0
    assert response.request_id


# ---------------------------------------------------------------------------
# Simulated failure modes
# ---------------------------------------------------------------------------


async def test_simulated_timeout_failure() -> None:
    client = FakeModelClient(fail_with=ModelTimeoutError)
    with pytest.raises(ModelTimeoutError):
        await client.generate(_request())


async def test_simulated_unavailable_failure() -> None:
    client = FakeModelClient(fail_with=ModelUnavailableError)
    with pytest.raises(ModelUnavailableError):
        await client.generate(_request())


async def test_simulated_failure_still_records_the_request() -> None:
    client = FakeModelClient(fail_with=ModelUnavailableError)
    request = _request()
    with pytest.raises(ModelUnavailableError):
        await client.generate(request)
    assert client.last_request is request
    assert client.call_count == 1
