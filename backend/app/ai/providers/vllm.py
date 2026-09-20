"""VLLMModelClient — real provider adapter for the Modal-hosted vLLM/
Nemotron deployment validated standalone in Phase 12A.

    ModelRequest
        v
    VLLMModelClient.generate()
        v
    AsyncOpenAI  ->  Modal proxy auth  ->  vLLM  ->  Nemotron
        v
    ModelResponse

Higher layers (ModelRouter, PromptBuilder, SimulationService, ...) never
see Modal's proxy-auth scheme or Nemotron's `enable_thinking` flag — those
are provider-specific details that stay entirely inside this adapter.
That isolation is the entire point of the ModelClient abstraction (Phase 11).
"""

import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    OpenAIError,
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
from app.ai.schemas import ModelRequest, ModelResponse, ModelResponseFormat, TokenUsage

PROVIDER_NAME = "vllm"

DEFAULT_TIMEOUT_SECONDS = 30.0

# Nemotron 3.5 has "thinking" (reasoning) enabled by default, which can
# consume an entire small max_tokens budget before any final content is
# produced — discovered during Phase 12A standalone validation (responses
# came back with finish_reason="length" and empty content). Every normal
# PitchFight interactive call disables it via vLLM's chat-template
# passthrough. This is a Nemotron/vLLM implementation detail; it never
# leaks above this adapter.
_DISABLE_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


class VLLMModelClient(ModelClient):
    """Talks to one Modal-hosted, OpenAI-compatible vLLM server."""

    def __init__(
        self,
        *,
        base_url: str,
        served_model_name: str,
        modal_key: str,
        modal_secret: str,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not base_url:
            raise ModelConfigurationError("VLLMModelClient requires a base_url")
        if not served_model_name:
            raise ModelConfigurationError("VLLMModelClient requires a served_model_name")
        if not modal_key or not modal_secret:
            raise ModelConfigurationError(
                "VLLMModelClient requires both a Modal proxy key and secret"
            )

        self._served_model_name = served_model_name
        self._default_timeout_seconds = default_timeout_seconds

        # Modal proxy auth: the endpoint expects
        # `Authorization: Bearer <key>.<secret>`. Passing this combined
        # value as the OpenAI client's api_key makes it send exactly that
        # header. Never logged, never included in any exception message.
        proxy_token = f"{modal_key}.{modal_secret}"
        self._client = AsyncOpenAI(base_url=f"{base_url.rstrip('/')}/v1", api_key=proxy_token)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self._served_model_name,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "extra_body": _DISABLE_THINKING_EXTRA_BODY,
            "timeout": request.timeout_seconds or self._default_timeout_seconds,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p
        if request.response_format == ModelResponseFormat.JSON:
            # Not exercised by Phase 12A's live validation (that smoke test
            # relied on plain prompt instructions, not this parameter) —
            # verify this against the real endpoint before depending on it.
            kwargs["response_format"] = {"type": "json_object"}

        start = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APITimeoutError as exc:
            raise ModelTimeoutError("Nemotron request timed out") from exc
        except AuthenticationError as exc:
            raise ModelConfigurationError(
                "Nemotron endpoint rejected the Modal proxy credentials (401)"
            ) from exc
        except RateLimitError as exc:
            raise ModelUnavailableError("Nemotron endpoint is rate-limiting requests") from exc
        except BadRequestError as exc:
            raise ModelRequestError(f"Nemotron endpoint rejected the request: {exc}") from exc
        except APIStatusError as exc:
            raise ModelUnavailableError(
                f"Nemotron endpoint returned an error status ({exc.status_code})"
            ) from exc
        except APIConnectionError as exc:
            raise ModelUnavailableError("Could not reach the Nemotron endpoint") from exc
        except OpenAIError as exc:
            raise ModelUnavailableError(f"Unexpected error calling Nemotron: {exc}") from exc

        latency_ms = (time.perf_counter() - start) * 1000

        if not response.choices:
            raise ModelResponseError("Nemotron response contained no choices")

        choice = response.choices[0]
        content = choice.message.content if choice.message else None
        if not content or not content.strip():
            raise ModelResponseError(
                f"Nemotron returned empty content (finish_reason={choice.finish_reason!r}); "
                "this usually means enable_thinking wasn't honored or max_tokens was too small"
            )

        usage = response.usage
        token_usage = TokenUsage(
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )

        return ModelResponse(
            content=content,
            provider=PROVIDER_NAME,
            model=response.model or self._served_model_name,
            finish_reason=choice.finish_reason,
            usage=token_usage,
            latency_ms=latency_ms,
            request_id=response.id,
            raw_metadata={},
        )
