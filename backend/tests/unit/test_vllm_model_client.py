"""VLLMModelClient tests: request mapping, Modal proxy-auth construction,
response mapping, and error translation. Entirely mocked — no unit test
here ever calls the real Modal/vLLM endpoint or the internet."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from app.ai.model_client import ModelClient
from app.ai.model_errors import (
    ModelConfigurationError,
    ModelRequestError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.ai.model_router import ModelRouter
from app.ai.providers import VLLMModelClient
from app.ai.schemas import ModelRequest, ModelResponseFormat

BASE_URL = "https://prakharkshp--pitchfight-nemotron-inference-server.us-east.modal.direct"
SERVED_MODEL_NAME = "pitchfight-nemotron"
MODAL_KEY = "wk-test-key"
MODAL_SECRET = "ws-test-secret"


def _fake_response(
    *,
    content: str | None = "What evidence supports that claim?",
    finish_reason: str | None = "stop",
    model: str = SERVED_MODEL_NAME,
    request_id: str = "chatcmpl-test-123",
    prompt_tokens: int | None = 10,
    completion_tokens: int | None = 5,
    total_tokens: int | None = 15,
    no_choices: bool = False,
) -> SimpleNamespace:
    if no_choices:
        return SimpleNamespace(choices=[], model=model, id=request_id, usage=None)

    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = (
        SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens
        )
        if prompt_tokens is not None
        else None
    )
    return SimpleNamespace(choices=[choice], model=model, id=request_id, usage=usage)


def _build_client(monkeypatch, *, create_mock: AsyncMock | None = None) -> tuple[VLLMModelClient, AsyncMock, MagicMock]:
    """Builds a VLLMModelClient whose internal AsyncOpenAI is replaced with
    a mock, and returns (client, mocked create(), captured constructor kwargs)."""
    create_mock = create_mock if create_mock is not None else AsyncMock(return_value=_fake_response())
    mock_openai_instance = MagicMock()
    mock_openai_instance.chat.completions.create = create_mock

    captured_kwargs: dict = {}

    def _fake_async_openai(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_openai_instance

    monkeypatch.setattr("app.ai.providers.vllm.AsyncOpenAI", _fake_async_openai)

    client = VLLMModelClient(
        base_url=BASE_URL,
        served_model_name=SERVED_MODEL_NAME,
        modal_key=MODAL_KEY,
        modal_secret=MODAL_SECRET,
    )
    return client, create_mock, captured_kwargs


def _request(**overrides) -> ModelRequest:
    defaults = {"system_prompt": "You are a judge.", "user_prompt": "Evaluate this pitch."}
    defaults.update(overrides)
    return ModelRequest(**defaults)


def _http_error(cls, status_code: int, message: str = "error"):
    request = httpx.Request("POST", f"{BASE_URL}/v1/chat/completions")
    response = httpx.Response(status_code=status_code, request=request)
    return cls(message, response=response, body=None)


# ---------------------------------------------------------------------------
# Construction / Modal proxy-auth
# ---------------------------------------------------------------------------


def test_vllm_client_implements_model_client(monkeypatch) -> None:
    client, _, _ = _build_client(monkeypatch)
    assert isinstance(client, ModelClient)


def test_constructor_builds_proxy_token_as_bearer_api_key(monkeypatch) -> None:
    _, _, captured_kwargs = _build_client(monkeypatch)
    assert captured_kwargs["api_key"] == f"{MODAL_KEY}.{MODAL_SECRET}"
    assert captured_kwargs["base_url"] == f"{BASE_URL}/v1"


def test_missing_credentials_raise_configuration_error_immediately(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.providers.vllm.AsyncOpenAI", MagicMock())
    with pytest.raises(ModelConfigurationError):
        VLLMModelClient(
            base_url=BASE_URL, served_model_name=SERVED_MODEL_NAME, modal_key="", modal_secret=MODAL_SECRET
        )
    with pytest.raises(ModelConfigurationError):
        VLLMModelClient(
            base_url=BASE_URL, served_model_name=SERVED_MODEL_NAME, modal_key=MODAL_KEY, modal_secret=""
        )
    with pytest.raises(ModelConfigurationError):
        VLLMModelClient(
            base_url="", served_model_name=SERVED_MODEL_NAME, modal_key=MODAL_KEY, modal_secret=MODAL_SECRET
        )


async def test_secret_never_appears_in_a_raised_error_message(monkeypatch) -> None:
    create_mock = AsyncMock(side_effect=_http_error(AuthenticationError, 401))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelConfigurationError) as exc_info:
        await client.generate(_request())
    assert MODAL_SECRET not in str(exc_info.value)
    assert MODAL_KEY not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Request mapping
# ---------------------------------------------------------------------------


async def test_request_mapping_sends_system_and_user_messages(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request(system_prompt="SYSTEM TEXT", user_prompt="USER TEXT"))
    call_kwargs = create_mock.call_args.kwargs
    assert call_kwargs["messages"] == [
        {"role": "system", "content": "SYSTEM TEXT"},
        {"role": "user", "content": "USER TEXT"},
    ]
    assert call_kwargs["model"] == SERVED_MODEL_NAME


async def test_request_mapping_forwards_generation_parameters(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request(temperature=0.4, max_tokens=200, top_p=0.8))
    call_kwargs = create_mock.call_args.kwargs
    assert call_kwargs["temperature"] == 0.4
    assert call_kwargs["max_tokens"] == 200
    assert call_kwargs["top_p"] == 0.8


async def test_unset_generation_parameters_are_not_forwarded(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request())
    call_kwargs = create_mock.call_args.kwargs
    assert "temperature" not in call_kwargs
    assert "max_tokens" not in call_kwargs
    assert "top_p" not in call_kwargs


async def test_enable_thinking_false_is_always_sent(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request())
    call_kwargs = create_mock.call_args.kwargs
    assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


async def test_json_response_format_is_mapped(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request(response_format=ModelResponseFormat.JSON))
    call_kwargs = create_mock.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}


async def test_text_response_format_does_not_set_response_format(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request(response_format=ModelResponseFormat.TEXT))
    call_kwargs = create_mock.call_args.kwargs
    assert "response_format" not in call_kwargs


async def test_request_timeout_seconds_is_forwarded(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request(timeout_seconds=5))
    assert create_mock.call_args.kwargs["timeout"] == 5


async def test_default_timeout_used_when_request_does_not_specify_one(monkeypatch) -> None:
    client, create_mock, _ = _build_client(monkeypatch)
    await client.generate(_request())
    assert create_mock.call_args.kwargs["timeout"] == client._default_timeout_seconds


# ---------------------------------------------------------------------------
# Response mapping
# ---------------------------------------------------------------------------


async def test_basic_response_mapping(monkeypatch) -> None:
    create_mock = AsyncMock(
        return_value=_fake_response(content="Why now?", finish_reason="stop", model=SERVED_MODEL_NAME)
    )
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    response = await client.generate(_request())
    assert response.content == "Why now?"
    assert response.provider == "vllm"
    assert response.model == SERVED_MODEL_NAME
    assert response.finish_reason == "stop"
    assert response.request_id == "chatcmpl-test-123"
    assert response.latency_ms is not None and response.latency_ms >= 0


async def test_token_usage_mapping(monkeypatch) -> None:
    create_mock = AsyncMock(
        return_value=_fake_response(prompt_tokens=42, completion_tokens=17, total_tokens=59)
    )
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    response = await client.generate(_request())
    assert response.usage.input_tokens == 42
    assert response.usage.output_tokens == 17
    assert response.usage.total_tokens == 59


async def test_missing_usage_maps_to_all_none(monkeypatch) -> None:
    create_mock = AsyncMock(return_value=_fake_response(prompt_tokens=None))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    response = await client.generate(_request())
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None
    assert response.usage.total_tokens is None


# ---------------------------------------------------------------------------
# Empty / malformed output
# ---------------------------------------------------------------------------


async def test_empty_content_raises_model_response_error(monkeypatch) -> None:
    create_mock = AsyncMock(return_value=_fake_response(content="", finish_reason="length"))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelResponseError):
        await client.generate(_request())


async def test_none_content_raises_model_response_error(monkeypatch) -> None:
    create_mock = AsyncMock(return_value=_fake_response(content=None, finish_reason="length"))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelResponseError):
        await client.generate(_request())


async def test_no_choices_raises_model_response_error(monkeypatch) -> None:
    create_mock = AsyncMock(return_value=_fake_response(no_choices=True))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelResponseError):
        await client.generate(_request())


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


async def test_timeout_maps_to_model_timeout_error(monkeypatch) -> None:
    request_obj = httpx.Request("POST", f"{BASE_URL}/v1/chat/completions")
    create_mock = AsyncMock(side_effect=APITimeoutError(request=request_obj))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelTimeoutError):
        await client.generate(_request())


async def test_401_maps_to_model_configuration_error(monkeypatch) -> None:
    create_mock = AsyncMock(side_effect=_http_error(AuthenticationError, 401))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelConfigurationError):
        await client.generate(_request())


async def test_rate_limit_maps_to_model_unavailable_error(monkeypatch) -> None:
    create_mock = AsyncMock(side_effect=_http_error(RateLimitError, 429))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelUnavailableError):
        await client.generate(_request())


async def test_5xx_maps_to_model_unavailable_error(monkeypatch) -> None:
    create_mock = AsyncMock(side_effect=_http_error(InternalServerError, 503))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelUnavailableError):
        await client.generate(_request())


async def test_bad_request_maps_to_model_request_error(monkeypatch) -> None:
    create_mock = AsyncMock(side_effect=_http_error(BadRequestError, 400))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelRequestError):
        await client.generate(_request())


async def test_connection_error_maps_to_model_unavailable_error(monkeypatch) -> None:
    request_obj = httpx.Request("POST", f"{BASE_URL}/v1/chat/completions")
    create_mock = AsyncMock(side_effect=APIConnectionError(request=request_obj))
    client, _, _ = _build_client(monkeypatch, create_mock=create_mock)
    with pytest.raises(ModelUnavailableError):
        await client.generate(_request())


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


async def test_router_resolves_nemotron_alias(monkeypatch) -> None:
    client, _, _ = _build_client(monkeypatch)
    router = ModelRouter(default_alias="fake")
    router.register("nemotron", client)
    resolved = router.get_client("nemotron")
    assert resolved is client
    assert isinstance(resolved, VLLMModelClient)
