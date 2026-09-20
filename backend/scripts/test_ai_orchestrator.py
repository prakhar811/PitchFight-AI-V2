"""Manual, one-off live test of AIOrchestrator against the real Nemotron
provider (Phase 13). Sends exactly ONE real battle_question request
through the full stack:

    BattleQuestionRequest -> AIOrchestrator -> PromptBuilder -> ModelRouter
        -> VLLMModelClient -> Modal/vLLM/Nemotron -> typed BattleQuestionOutput

This is deliberately separate from backend/scripts/test_real_model.py
(Phase 12B, proves the raw provider connection works) — this script proves
the ORCHESTRATION layer works end to end against the real model.

MANUAL ONLY.
- Never runs during pytest (lives outside backend/tests/, and pytest.ini's
  testpaths = tests means it would be skipped even if discovered).
- Makes a real, billed call to the Modal-hosted GPU endpoint.
- Never prints MODAL_KEY or MODAL_SECRET.

Usage:
    python backend/scripts/test_ai_orchestrator.py

Requires MODEL_NEMOTRON_BASE_URL, MODEL_NEMOTRON_NAME, MODAL_KEY, and
MODAL_SECRET to be set (via .env or already-exported environment variables).
"""

import asyncio
import sys
import time

from app.ai import AIOrchestrator
from app.ai.model_errors import ModelConfigurationError, ModelError
from app.ai.model_router import ModelRouter
from app.ai.orchestrator import AIOutputParseError
from app.ai.providers import VLLMModelClient
from app.ai.schemas import BattleQuestionRequest
from app.core.config import settings
from app.models.enums import Difficulty

PITCH_SNAPSHOT = {
    "startup_name": "StudyPlanner AI",
    "problem": "Students struggle to plan study schedules around deadlines and energy levels.",
    "target_users": "College students",
    "solution": "An AI planner that adapts a student's study schedule daily based on progress.",
    "why_ai": "Static planners don't adapt; an AI planner reschedules automatically as plans slip.",
    "traction": "300 student signups from two campuses",
    "competitors": "Notion, Google Calendar, generic to-do apps",
    "ask": "$25k pre-seed to fund the first semester pilot",
}


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

    orchestrator = AIOrchestrator(router)
    request = BattleQuestionRequest(
        judge_config_version="technical_judge-v1",
        difficulty=Difficulty.INVESTOR,
        pitch_snapshot=PITCH_SNAPSHOT,
        current_phase="PITCH_BATTLE",
        battle_round=1,
    )

    print("Sending one live battle_question request through AIOrchestrator ...")
    start = time.perf_counter()
    try:
        result = await orchestrator.generate_battle_question(request)
    except (ModelError, AIOutputParseError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    elapsed_s = time.perf_counter() - start

    print()
    print("--- Typed result (BattleQuestionOutput) ---")
    print(f"question: {result.question!r}")
    print(f"attack_tag: {result.attack_tag!r}")
    print(f"is_follow_up: {result.is_follow_up}")
    print(f"expected_evidence: {result.expected_evidence}")
    print(f"wall-clock elapsed: {elapsed_s:.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
