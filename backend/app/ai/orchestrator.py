"""AIOrchestrator — coordinates PromptBuilder -> ModelRouter -> ModelClient
for the four locked prompt tasks, returning typed PitchFight results.

    BattleQuestionRequest / BattleFollowupRequest /
    RetryFeedbackRequest / DealNegotiationRequest
        v
    PromptContext            (this module builds it)
        v
    build_prompt()           (existing PromptBuilder — untouched)
        v
    BuiltPrompt
        v
    build_model_request()    (existing Phase 11 helper — untouched)
        v
    ModelRequest
        v
    ModelRouter.get_client(alias)   (existing — untouched)
        v
    ModelClient.generate()
        v
    ModelResponse.content (JSON text)
        v
    parsed + validated typed output (BattleQuestionOutput / etc.)

Pure AI computation only:
- no SQL, MongoDB, or Redis reads or writes
- no simulation phase transitions or round-count decisions
- no Scorecard/scoring logic
- no provider construction (AsyncOpenAI, VLLMModelClient, Modal
  credentials, ...) — callers hand this a already-configured ModelRouter

SimulationService (app/services/simulation_service.py) owns persistence
and workflow; it supplies this orchestrator's inputs and decides what to
do with its outputs. Provider/model errors (app/ai/model_errors.py)
propagate unchanged — this module doesn't catch or hide them.
"""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.model_client import build_model_request
from app.ai.model_router import ModelRouter
from app.ai.prompt_builder import build_prompt
from app.ai.schemas import (
    BaseGenerationRequest,
    BattleFollowupRequest,
    BattleQuestionOutput,
    BattleQuestionRequest,
    DealNegotiationOutput,
    DealNegotiationRequest,
    PromptContext,
    PromptTask,
    RetryFeedbackOutput,
    RetryFeedbackRequest,
)

T = TypeVar("T", bound=BaseModel)


class AIOutputParseError(Exception):
    """The model's response content wasn't valid JSON, or didn't match the
    expected structured-output schema for the task. Raised instead of
    silently accepting malformed output."""


class AIOrchestrator:
    """Depends only on a pre-configured ModelRouter — never constructs a
    provider client itself. Model alias selection ("fake", "nemotron", ...)
    is an explicit, optional, per-call argument; the default comes from
    however the router itself was configured (see ModelRouter.default_alias)."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def generate_battle_question(
        self, request: BattleQuestionRequest, *, model_alias: str | None = None
    ) -> BattleQuestionOutput:
        context = _build_context(request, PromptTask.BATTLE_QUESTION)
        return await self._generate_and_parse(context, BattleQuestionOutput, model_alias)

    async def generate_battle_followup(
        self, request: BattleFollowupRequest, *, model_alias: str | None = None
    ) -> BattleQuestionOutput:
        context = _build_context(
            request,
            PromptTask.BATTLE_FOLLOWUP,
            task_context={"prior_answer": request.prior_answer},
        )
        return await self._generate_and_parse(context, BattleQuestionOutput, model_alias)

    async def generate_retry_feedback(
        self, request: RetryFeedbackRequest, *, model_alias: str | None = None
    ) -> RetryFeedbackOutput:
        context = _build_context(
            request,
            PromptTask.RETRY_FEEDBACK,
            task_context={
                "original_answer": request.original_answer,
                "retry_answer": request.retry_answer,
            },
        )
        return await self._generate_and_parse(context, RetryFeedbackOutput, model_alias)

    async def generate_deal_negotiation(
        self, request: DealNegotiationRequest, *, model_alias: str | None = None
    ) -> DealNegotiationOutput:
        task_context = {"founder_offer": request.founder_offer} if request.founder_offer else None
        context = _build_context(request, PromptTask.DEAL_NEGOTIATION, task_context=task_context)
        return await self._generate_and_parse(context, DealNegotiationOutput, model_alias)

    # -- shared plumbing ----------------------------------------------------

    async def _generate_and_parse(
        self, context: PromptContext, output_schema: type[T], model_alias: str | None
    ) -> T:
        built_prompt = build_prompt(context)
        model_request = build_model_request(built_prompt)

        client = self._router.get_client(model_alias)
        response = await client.generate(model_request)

        return _parse_structured_output(response.content, output_schema)


def _build_context(
    request: BaseGenerationRequest, task: PromptTask, *, task_context: dict[str, Any] | None = None
) -> PromptContext:
    return PromptContext(
        judge_config_version=request.judge_config_version,
        difficulty=request.difficulty,
        task=task,
        pitch_snapshot=request.pitch_snapshot,
        current_phase=request.current_phase,
        battle_round=request.battle_round,
        deal_round=request.deal_round,
        active_attack_tag=request.active_attack_tag,
        completed_attack_tags=request.completed_attack_tags,
        recent_events=request.recent_events,
        task_context=task_context,
    )


def _parse_structured_output(content: str, schema: type[T]) -> T:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIOutputParseError(
            f"Model output was not valid JSON (first 200 chars): {content[:200]!r}"
        ) from exc

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise AIOutputParseError(f"Model output did not match {schema.__name__}: {exc}") from exc
