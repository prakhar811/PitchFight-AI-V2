"""ModelRequest/ModelResponse validation and the BuiltPrompt -> ModelRequest
conversion helper. No network, no database."""

import pytest
from pydantic import ValidationError

from app.ai.model_client import build_model_request
from app.ai.schemas import (
    BuiltPrompt,
    ModelRequest,
    ModelResponse,
    ModelResponseFormat,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# ModelRequest
# ---------------------------------------------------------------------------


def test_valid_request_creation_preserves_system_and_user_prompts() -> None:
    request = ModelRequest(system_prompt="You are a judge.", user_prompt="Pitch details.")
    assert request.system_prompt == "You are a judge."
    assert request.user_prompt == "Pitch details."


def test_default_response_format_is_text() -> None:
    request = ModelRequest(system_prompt="s", user_prompt="u")
    assert request.response_format == ModelResponseFormat.TEXT


def test_json_response_format_is_settable() -> None:
    request = ModelRequest(system_prompt="s", user_prompt="u", response_format=ModelResponseFormat.JSON)
    assert request.response_format == ModelResponseFormat.JSON


def test_valid_generation_parameters_accepted() -> None:
    request = ModelRequest(
        system_prompt="s", user_prompt="u", temperature=0.7, max_tokens=256, top_p=0.9, timeout_seconds=30
    )
    assert request.temperature == 0.7
    assert request.max_tokens == 256
    assert request.top_p == 0.9
    assert request.timeout_seconds == 30


def test_negative_max_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(system_prompt="s", user_prompt="u", max_tokens=-1)


def test_zero_max_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(system_prompt="s", user_prompt="u", max_tokens=0)


def test_negative_temperature_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(system_prompt="s", user_prompt="u", temperature=-0.1)


def test_top_p_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(system_prompt="s", user_prompt="u", top_p=1.5)
    with pytest.raises(ValidationError):
        ModelRequest(system_prompt="s", user_prompt="u", top_p=-0.1)


def test_non_positive_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(system_prompt="s", user_prompt="u", timeout_seconds=0)


def test_request_is_frozen() -> None:
    request = ModelRequest(system_prompt="s", user_prompt="u")
    with pytest.raises(ValidationError):
        request.system_prompt = "changed"


# ---------------------------------------------------------------------------
# ModelResponse
# ---------------------------------------------------------------------------


def test_model_response_defaults() -> None:
    response = ModelResponse(content="hello", provider="fake", model="fake-model-v1")
    assert response.usage == TokenUsage()
    assert response.raw_metadata == {}
    assert response.finish_reason is None


def test_token_usage_fields_may_be_none() -> None:
    usage = TokenUsage()
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None


# ---------------------------------------------------------------------------
# build_model_request (BuiltPrompt -> ModelRequest)
# ---------------------------------------------------------------------------


def test_build_model_request_copies_prompts_and_metadata() -> None:
    built = BuiltPrompt(
        system_prompt="SYSTEM TEXT",
        user_prompt="USER TEXT",
        metadata={"judge_config_version": "skeptical_vc-v1", "difficulty": "INVESTOR", "task": "BATTLE_QUESTION"},
    )
    request = build_model_request(built)

    assert request.system_prompt == "SYSTEM TEXT"
    assert request.user_prompt == "USER TEXT"
    assert request.metadata == built.metadata
    # Mutating the returned metadata dict must not mutate BuiltPrompt's.
    request.metadata["extra"] = "x"
    assert "extra" not in built.metadata


def test_build_model_request_defaults_to_json() -> None:
    built = BuiltPrompt(system_prompt="s", user_prompt="u", metadata={})
    request = build_model_request(built)
    assert request.response_format == ModelResponseFormat.JSON


def test_build_model_request_accepts_generation_overrides() -> None:
    built = BuiltPrompt(system_prompt="s", user_prompt="u", metadata={})
    request = build_model_request(built, temperature=0.2, max_tokens=128, response_format=ModelResponseFormat.TEXT)
    assert request.temperature == 0.2
    assert request.max_tokens == 128
    assert request.response_format == ModelResponseFormat.TEXT
