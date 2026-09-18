"""ModelClient — one async interface for ONE already-configured model/provider.

    ModelRequest
        v
    ModelClient.generate()
        v
    ModelResponse

A ModelClient instance represents one specific provider+model, already
configured. It does NOT choose between providers — that's ModelRouter's
job (app/ai/model_router.py). It does NOT know about Pitch, JudgePersona,
difficulty, battle rounds, deals, retries, Scorecards, Mongo, or Redis —
only prompts and model execution.

All generation is async: even the fake provider, since real inference
calls are network-bound.
"""

from abc import ABC, abstractmethod

from app.ai.schemas import BuiltPrompt, ModelRequest, ModelResponse, ModelResponseFormat


class ModelClient(ABC):
    """One configured model/provider implementation."""

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Run one generation call and return a normalized ModelResponse."""


def build_model_request(
    built_prompt: BuiltPrompt,
    *,
    response_format: ModelResponseFormat = ModelResponseFormat.JSON,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    timeout_seconds: float | None = None,
) -> ModelRequest:
    """Convert a Phase 10 BuiltPrompt into a provider-neutral ModelRequest.

    Lives here, not in prompt_builder.py — PromptBuilder stays unaware that
    providers or ModelClient exist. Defaults to JSON: every current Phase
    10 task (battle question/follow-up, retry feedback, deal negotiation)
    asks for structured JSON output in its OUTPUT FORMAT section.
    """
    return ModelRequest(
        system_prompt=built_prompt.system_prompt,
        user_prompt=built_prompt.user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        timeout_seconds=timeout_seconds,
        response_format=response_format,
        metadata=dict(built_prompt.metadata),
    )
