"""AIOrchestrator tests: task orchestration, prompt/model wiring, structured
output parsing, and error propagation. Uses FakeModelClient / a mocked
ModelClient — no test here calls Modal, vLLM, or the internet."""


import pytest

from app.ai import AIOrchestrator, AIOutputParseError
from app.ai.model_client import ModelClient
from app.ai.model_errors import ModelConfigurationError, ModelUnavailableError
from app.ai.model_router import ModelRouter
from app.ai.providers import FakeModelClient
from app.ai.schemas import (
    BattleFollowupRequest,
    BattleQuestionOutput,
    BattleQuestionRequest,
    DealNegotiationOutput,
    DealNegotiationRequest,
    ModelResponse,
    RetryFeedbackOutput,
    RetryFeedbackRequest,
    TokenUsage,
)
from app.models.enums import Difficulty

PITCH_SNAPSHOT = {
    "startup_name": "PitchFight",
    "problem": "Founders can't rehearse investor pressure.",
    "target_users": "First-time founders",
    "solution": "AI judges that simulate real pitch pressure.",
    "why_ai": "Adaptive tone and difficulty in real time.",
    "traction": "10 pilot users",
    "competitors": "Practicing with friends",
    "ask": "Pre-seed funding",
}


def _battle_question_request(**overrides) -> BattleQuestionRequest:
    defaults = {
        "judge_config_version": "technical_judge-v1",
        "difficulty": Difficulty.INVESTOR,
        "pitch_snapshot": PITCH_SNAPSHOT,
        "current_phase": "PITCH_BATTLE",
        "battle_round": 1,
    }
    defaults.update(overrides)
    return BattleQuestionRequest(**defaults)


def _router_with_fake(response_content: str) -> tuple[ModelRouter, FakeModelClient]:
    fake = FakeModelClient(response_content=response_content)
    router = ModelRouter(default_alias="fake")
    router.register("fake", fake)
    return router, fake


# ---------------------------------------------------------------------------
# battle_question
# ---------------------------------------------------------------------------


async def test_generate_battle_question_returns_typed_output() -> None:
    router, _ = _router_with_fake(
        '{"question": "Why does this need AI?", "attack_tag": "Architecture", "is_follow_up": false}'
    )
    orchestrator = AIOrchestrator(router)
    result = await orchestrator.generate_battle_question(_battle_question_request())

    assert isinstance(result, BattleQuestionOutput)
    assert result.question == "Why does this need AI?"
    assert result.attack_tag == "Architecture"
    assert result.is_follow_up is False


async def test_battle_question_prompt_receives_correct_task_persona_difficulty_and_context() -> None:
    router, fake = _router_with_fake('{"question": "Q", "attack_tag": "A", "is_follow_up": false}')
    orchestrator = AIOrchestrator(router)
    await orchestrator.generate_battle_question(
        _battle_question_request(judge_config_version="skeptical_vc-v1", difficulty=Difficulty.PRACTICE)
    )

    system_prompt = fake.last_request.system_prompt
    assert "Would I actually put money into this company?" in system_prompt  # skeptical_vc persona
    assert "supportive but still challenging" in system_prompt  # PRACTICE difficulty
    assert "Generate the next primary judge question" in system_prompt  # battle_question task
    assert "PitchFight" in fake.last_request.user_prompt  # pitch snapshot context


# ---------------------------------------------------------------------------
# battle_followup
# ---------------------------------------------------------------------------


async def test_generate_battle_followup_returns_typed_output_and_includes_prior_answer() -> None:
    router, fake = _router_with_fake(
        '{"question": "What evidence?", "attack_tag": "Traction", "is_follow_up": true}'
    )
    orchestrator = AIOrchestrator(router)
    request = BattleFollowupRequest(
        judge_config_version="skeptical_vc-v1",
        difficulty=Difficulty.JUDGE,
        pitch_snapshot=PITCH_SNAPSHOT,
        current_phase="PITCH_BATTLE",
        prior_answer="We have a lot of users.",
    )
    result = await orchestrator.generate_battle_followup(request)

    assert isinstance(result, BattleQuestionOutput)
    assert result.is_follow_up is True
    assert "We have a lot of users." in fake.last_request.user_prompt
    assert "Generate a follow-up question" in fake.last_request.system_prompt


# ---------------------------------------------------------------------------
# retry_feedback
# ---------------------------------------------------------------------------


async def test_generate_retry_feedback_returns_typed_output_and_includes_both_answers() -> None:
    router, fake = _router_with_fake(
        '{"feedback": "Better, but still vague.", "improved": true, "remaining_gap": "a real number"}'
    )
    orchestrator = AIOrchestrator(router)
    request = RetryFeedbackRequest(
        judge_config_version="hackathon_judge-v1",
        difficulty=Difficulty.PRACTICE,
        pitch_snapshot=PITCH_SNAPSHOT,
        current_phase="RETRY",
        original_answer="We have some users.",
        retry_answer="We have 50 paying users.",
    )
    result = await orchestrator.generate_retry_feedback(request)

    assert isinstance(result, RetryFeedbackOutput)
    assert result.improved is True
    assert result.remaining_gap == "a real number"
    assert "We have some users." in fake.last_request.user_prompt
    assert "We have 50 paying users." in fake.last_request.user_prompt
    assert "Retry" in fake.last_request.system_prompt or "retry" in fake.last_request.system_prompt.lower()


# ---------------------------------------------------------------------------
# deal_negotiation
# ---------------------------------------------------------------------------


async def test_generate_deal_negotiation_returns_typed_output() -> None:
    router, fake = _router_with_fake(
        '{"response": "20% equity is too rich for this stage.", "negotiation_tag": "equity"}'
    )
    orchestrator = AIOrchestrator(router)
    request = DealNegotiationRequest(
        judge_config_version="skeptical_vc-v1",
        difficulty=Difficulty.INVESTOR,
        pitch_snapshot=PITCH_SNAPSHOT,
        current_phase="DEAL",
        deal_round=1,
        founder_offer="I'll offer 5% equity for $50k.",
    )
    result = await orchestrator.generate_deal_negotiation(request)

    assert isinstance(result, DealNegotiationOutput)
    assert result.negotiation_tag == "equity"
    assert "I'll offer 5% equity for $50k." in fake.last_request.user_prompt


async def test_deal_negotiation_without_founder_offer_omits_task_context() -> None:
    router, fake = _router_with_fake('{"response": "What terms are you proposing?"}')
    orchestrator = AIOrchestrator(router)
    request = DealNegotiationRequest(
        judge_config_version="skeptical_vc-v1",
        difficulty=Difficulty.JUDGE,
        pitch_snapshot=PITCH_SNAPSHOT,
        current_phase="DEAL",
    )
    await orchestrator.generate_deal_negotiation(request)
    assert "TASK CONTEXT" not in fake.last_request.user_prompt


# ---------------------------------------------------------------------------
# Model alias resolution
# ---------------------------------------------------------------------------


async def test_default_alias_used_when_not_overridden() -> None:
    router, fake = _router_with_fake('{"question": "Q", "attack_tag": "A", "is_follow_up": false}')
    orchestrator = AIOrchestrator(router)
    await orchestrator.generate_battle_question(_battle_question_request())
    assert fake.call_count == 1


async def test_explicit_model_alias_override_is_used() -> None:
    router = ModelRouter(default_alias="fake")
    default_fake = FakeModelClient(response_content='{"question": "default", "attack_tag": "A", "is_follow_up": false}')
    other_fake = FakeModelClient(response_content='{"question": "other", "attack_tag": "A", "is_follow_up": false}')
    router.register("fake", default_fake)
    router.register("other", other_fake)

    orchestrator = AIOrchestrator(router)
    result = await orchestrator.generate_battle_question(
        _battle_question_request(), model_alias="other"
    )

    assert result.question == "other"
    assert default_fake.call_count == 0
    assert other_fake.call_count == 1


async def test_unknown_model_alias_raises_model_configuration_error() -> None:
    router, _ = _router_with_fake('{"question": "Q", "attack_tag": "A", "is_follow_up": false}')
    orchestrator = AIOrchestrator(router)
    with pytest.raises(ModelConfigurationError):
        await orchestrator.generate_battle_question(_battle_question_request(), model_alias="does-not-exist")


# ---------------------------------------------------------------------------
# Structured output parsing failures
# ---------------------------------------------------------------------------


async def test_malformed_json_raises_ai_output_parse_error() -> None:
    router, _ = _router_with_fake("this is not JSON at all")
    orchestrator = AIOrchestrator(router)
    with pytest.raises(AIOutputParseError):
        await orchestrator.generate_battle_question(_battle_question_request())


async def test_schema_invalid_json_raises_ai_output_parse_error() -> None:
    # Valid JSON, but missing the required "question" and "attack_tag" fields.
    router, _ = _router_with_fake('{"unexpected_field": true}')
    orchestrator = AIOrchestrator(router)
    with pytest.raises(AIOutputParseError):
        await orchestrator.generate_battle_question(_battle_question_request())


async def test_json_array_instead_of_object_raises_ai_output_parse_error() -> None:
    router, _ = _router_with_fake('["question", "attack_tag"]')
    orchestrator = AIOrchestrator(router)
    with pytest.raises(AIOutputParseError):
        await orchestrator.generate_battle_question(_battle_question_request())


# ---------------------------------------------------------------------------
# Model/provider error propagation
# ---------------------------------------------------------------------------


async def test_model_errors_propagate_unchanged() -> None:
    failing_client = FakeModelClient(fail_with=ModelUnavailableError)
    router = ModelRouter(default_alias="fake")
    router.register("fake", failing_client)
    orchestrator = AIOrchestrator(router)

    with pytest.raises(ModelUnavailableError):
        await orchestrator.generate_battle_question(_battle_question_request())


async def test_prompt_version_not_found_propagates_unchanged() -> None:
    from app.ai.prompt_builder import PromptVersionNotFoundError

    router, _ = _router_with_fake('{"question": "Q", "attack_tag": "A", "is_follow_up": false}')
    orchestrator = AIOrchestrator(router)
    with pytest.raises(PromptVersionNotFoundError):
        await orchestrator.generate_battle_question(
            _battle_question_request(judge_config_version="unknown_persona-v999")
        )


# ---------------------------------------------------------------------------
# No database/Mongo/Redis dependency
# ---------------------------------------------------------------------------


async def test_orchestrator_construction_requires_only_a_router() -> None:
    """AIOrchestrator.__init__ takes nothing but a ModelRouter — no
    AsyncSession, no Mongo collection, no Redis client."""
    import inspect

    signature = inspect.signature(AIOrchestrator.__init__)
    params = list(signature.parameters)
    assert params == ["self", "router"]


async def test_generate_and_parse_never_touches_a_real_model_client_type() -> None:
    """A minimal hand-rolled ModelClient (not FakeModelClient) works too —
    proves the orchestrator only depends on the ModelClient abstraction."""

    class _MockClient(ModelClient):
        async def generate(self, request) -> ModelResponse:
            return ModelResponse(
                content='{"question": "Q", "attack_tag": "A", "is_follow_up": false}',
                provider="mock",
                model="mock-model",
                usage=TokenUsage(),
            )

    router = ModelRouter(default_alias="mock")
    router.register("mock", _MockClient())
    orchestrator = AIOrchestrator(router)

    result = await orchestrator.generate_battle_question(_battle_question_request())
    assert result.question == "Q"
