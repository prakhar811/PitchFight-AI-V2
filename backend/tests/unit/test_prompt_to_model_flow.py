"""First end-to-end test of PromptBuilder -> model abstraction:

    PromptContext (Phase 10)
        -> build_prompt() -> BuiltPrompt
        -> build_model_request() -> ModelRequest
        -> ModelRouter -> FakeModelClient
        -> ModelResponse

Still no real model — FakeModelClient only. No database either."""

from app.ai.model_client import build_model_request
from app.ai.model_router import ModelRouter
from app.ai.prompt_builder import build_prompt
from app.ai.providers import FakeModelClient
from app.ai.schemas import PromptContext, PromptTask
from app.models.enums import Difficulty


def _context() -> PromptContext:
    return PromptContext(
        judge_config_version="technical_judge-v1",
        difficulty=Difficulty.INVESTOR,
        task=PromptTask.BATTLE_QUESTION,
        pitch_snapshot={
            "startup_name": "PitchFight",
            "problem": "Founders cannot rehearse investor pressure.",
            "target_users": "First-time founders",
            "solution": "AI judges that simulate real pitch pressure.",
            "why_ai": "Adaptive tone and difficulty in real time.",
            "traction": "10 pilot users",
            "competitors": "Practicing with friends",
            "ask": "Pre-seed funding",
        },
        current_phase="PITCH_BATTLE",
        battle_round=1,
    )


async def test_built_prompt_flows_through_router_to_fake_client_unchanged() -> None:
    built = build_prompt(_context())
    request = build_model_request(built)

    router = ModelRouter(default_alias="fake")
    fake_client = FakeModelClient(response_content='{"question": "Why does this need AI?", "attack_tag": "Architecture", "is_follow_up": false}')
    router.register("fake", fake_client)

    response = await router.get_client().generate(request)

    # The fake client received exactly what PromptBuilder produced.
    assert fake_client.last_request.system_prompt == built.system_prompt
    assert fake_client.last_request.user_prompt == built.user_prompt

    # Configured fake output comes back successfully.
    assert response.content == (
        '{"question": "Why does this need AI?", "attack_tag": "Architecture", "is_follow_up": false}'
    )
    assert response.provider == "fake"


async def test_metadata_from_built_prompt_reaches_the_model_request() -> None:
    built = build_prompt(_context())
    request = build_model_request(built)
    assert request.metadata == built.metadata
    assert request.metadata["judge_config_version"] == "technical_judge-v1"
    assert request.metadata["task"] == "BATTLE_QUESTION"
