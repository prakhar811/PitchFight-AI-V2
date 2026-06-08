"""PitchFight AI — shared API handler functions for REST and Gradio routes."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

from core.attack_tags import get_attack_tags, get_next_attack_tag
from core.persona_builder import build_persona_prompt
from core.samples import get_sample_startup
from core.scoring_engine import (
    mock_scorecard,
    generate_real_scorecard,
    generate_claim_based_scorecard,
    build_session_aware_fallback_scorecard,
)
from core.claim_extractor import extract_concrete_signals
from core import battle_flow
from core import model_router
from core import session_manager
from core.output_sanitizer import sanitize_model_output

load_dotenv()

logger = logging.getLogger(__name__)

MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "6"))

OPENING_MESSAGES: dict[str, tuple[str, str]] = {
    "skeptical_vc": (
        "Market Size",
        "How big is this really? Student event discovery sounds like a nice feature, not a venture-scale business.",
    ),
    "technical_judge": (
        "AI Justification",
        "Why does this need AI? A sorted event list with filters seems enough. What is the intelligence here?",
    ),
    "hackathon_judge": (
        "User Pain",
        "Students already lurk in WhatsApp groups. What pain are you solving that a shared Google Sheet cannot?",
    ),
}

MOCK_FOLLOWUPS: dict[str, list[str]] = {
    "skeptical_vc": [
        "You named competitors but did not explain why students switch. What is your wedge for the first 100 users?",
        "Where is the retention? Why would a student open this weekly instead of once before a hackathon?",
        "Walk me through revenue. Who pays and why would they pay you instead of Luma or LinkedIn?",
        "What stops a bigger platform from adding your ranking layer in a weekend?",
        "Your traction sounds like a prototype. What metric proves demand, not just build activity?",
        "If I gave you $50k today, what single milestone would prove this is investable?",
    ],
    "technical_judge": [
        "What data do you rank on, and how do you keep event metadata fresh without manual cleanup?",
        "If ranking is the core value, why is a small model better than deterministic scoring rules?",
        "What happens when two students with different goals get the same top recommendation?",
        "How does this scale beyond one campus without quality collapsing?",
        "What is your failure mode when event sources break or duplicate listings?",
        "Show me the simplest non-AI version. Why is that not good enough?",
    ],
    "hackathon_judge": [
        "In one sentence: what is novel here versus another event aggregator?",
        "If I only saw a 30-second demo, what would convince me the AI matching is real?",
        "What did you ship this weekend that proves user pain, not just scraped listings?",
        "Why is AI load-bearing in the MVP instead of optional polish?",
        "How does this fit the Backyard AI theme beyond using a model as a label?",
        "What will I remember about your project after judging 40 teams?",
    ],
}


_HISTORY_WINDOW = 12  # max turns sent to Nemotron for live inference


def pressure_level(round_number: int) -> str:
    if round_number <= 2:
        return "Medium"
    if round_number <= 4:
        return "High"
    return "Extreme"


def get_battle_phase(round_number: int) -> str:
    """Return a battle phase label based on round count."""
    if round_number <= 3:
        return "explore"
    if round_number <= 6:
        return "pressure"
    return "close"


def _recent_history(session_id: str, max_turns: int = _HISTORY_WINDOW) -> list[dict]:
    """Return at most max_turns recent history entries for live inference."""
    full = session_manager.get_history(session_id)
    return full[-max_turns:] if len(full) > max_turns else full


def handle_load_sample() -> dict[str, Any]:
    """Return the EventRadar AI demo startup."""
    return {"startup": get_sample_startup()}


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_opening_messages(
    startup: dict,
    persona: str,
    difficulty: str,
    attack_tag: str,
) -> list[dict[str, str]]:
    """Build the OpenAI-format messages list for the opening judge question."""
    system_prompt = build_persona_prompt(persona, startup, difficulty)
    tags = get_attack_tags(persona)
    tags_preview = ", ".join(tags[:4])

    user_content = (
        f"Current attack focus: {attack_tag}\n"
        f"Other pressure angles available: {tags_preview}\n\n"
        "Open the battle. Ask your first hard question about the startup above. "
        "Do not introduce yourself. Do not say hello. Go straight to the question. "
        "Attack the weakest claim in the pitch. Keep it under 3 sentences. "
        "Ask exactly one question."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _build_followup_messages(
    startup: dict,
    persona: str,
    difficulty: str,
    attack_tag: str,
    history: list[dict[str, Any]],
    judge_action: dict[str, Any],
    answer_quality: dict[str, Any],
) -> list[dict[str, str]]:
    """Build the OpenAI-format messages list for a follow-up judge question.

    The prompt instruction varies based on judge_action to guide Nemotron
    toward the correct Socratic behavior:
      - follow_up_same_tag  → press harder on the same topic
      - move_next_tag       → acknowledge prior point, move cleanly
      - move_after_limit    → briefly flag unresolved point, move on

    Voice mode note:
      History entries may originate from typed text or voice transcripts.
      The prompt wording uses "your answer" rather than "you typed" throughout.
    """
    system_prompt = build_persona_prompt(persona, startup, difficulty)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Replay conversation history as role turns (strip attack_tag metadata)
    for entry in history:
        role = entry.get("role", "user")
        content = entry.get("content", "")
        if role == "assistant":
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": "user", "content": content})

    action = judge_action.get("judge_action", "follow_up_same_tag")
    prev_tag = judge_action.get("previous_attack_tag", attack_tag)
    quality = answer_quality.get("quality", "partial")
    transition = judge_action.get("transition_note", "")

    if action == "follow_up_same_tag":
        instruction = (
            f"Attack focus: {attack_tag}\n"
            f"Your answer was classified as {quality}. {transition}\n\n"
            "The founder's last answer was insufficient. "
            "Ask one sharper, more specific follow-up on the SAME topic. "
            "Reference what they just said directly. "
            "Do not move to a new topic yet. "
            "Do not give advice. Do not say 'great answer' or 'interesting.' "
            "Keep it under 3 sentences. Ask exactly one question."
        )
    elif action == "move_next_tag":
        instruction = (
            f"New attack focus: {attack_tag}\n"
            f"Previous topic ({prev_tag}) is considered resolved. Do NOT revisit it.\n\n"
            "The founder gave a sufficient answer on the previous point. "
            "Move immediately to the new attack focus above. "
            "Do not keep drilling the previous topic. "
            "Do not say 'great answer', 'good point', 'well done', or any praise. "
            "Do not ask multiple questions. "
            "Do not give advice. "
            "Ask exactly one hard, specific question on the new attack focus. "
            "Keep the entire response under 3 sentences."
        )
    else:  # move_after_limit
        instruction = (
            f"New attack focus: {attack_tag}\n"
            f"Previous topic ({prev_tag}) remains unresolved. {transition}\n\n"
            "Briefly note that the previous issue was not fully addressed — "
            "one short clause only, then move on. "
            "Ask one hard question on the new attack focus. "
            "Do not keep drilling the unresolved point. "
            "Do not give advice. Keep it under 4 sentences. Ask exactly one question."
        )

    messages.append({"role": "user", "content": instruction})
    return messages


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_start_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a new pitch battle session and return the opening challenge."""
    startup = payload.get("startup") or {}
    persona = payload.get("persona", "technical_judge")
    difficulty = payload.get("difficulty", "high")
    input_mode = payload.get("input_mode", "text")
    mode = payload.get("mode", "pitch_battle")
    model_mode = payload.get("model_mode", "premium_nvidia")

    session = session_manager.create_session(
        startup, persona, difficulty, input_mode
    )
    session["mode"] = mode
    session["model_mode"] = model_mode

    mock_attack_tag, mock_ai_message = OPENING_MESSAGES.get(
        persona, OPENING_MESSAGES["technical_judge"]
    )

    attack_tag = mock_attack_tag
    ai_message = mock_ai_message
    model_ok = False
    provider = "mock"
    used_model_mode = "mock_fallback"
    model_error: str | None = None

    try:
        messages = _build_opening_messages(startup, persona, difficulty, mock_attack_tag)
        result = model_router.generate_opponent_response(
            messages,
            model_mode=model_mode,
            persona=persona,
            attack_tag=mock_attack_tag,
        )
        if result.get("ok") and result.get("content"):
            ai_message = sanitize_model_output(result["content"])
            model_ok = True
            provider = result.get("provider", "nvidia")
            used_model_mode = result.get("model_mode", model_mode)
        else:
            model_error = result.get("error") or "Model returned empty response"
            logger.warning("start_session: model not ok — using mock. error=%s", model_error)
    except Exception as exc:
        model_error = str(exc)
        logger.warning("start_session: model call raised — using mock. error=%s", exc)

    # Initialize battle_state with opening tag
    battle_flow.init_opening_state(session, attack_tag)

    session_manager.append_ai_message(session["session_id"], ai_message, attack_tag)

    return {
        "session_id": session["session_id"],
        "round": 1,
        "pressure_level": pressure_level(1),
        "battle_phase": get_battle_phase(1),
        "attack_tag": attack_tag,
        "ai_message": ai_message,
        "model_mode": used_model_mode,
        "provider": provider,
        "model_ok": model_ok,
        "judge_action": "opening_question",
        "answer_quality": None,
        "topic_satisfied": None,
        "tag_attempt": 1,
        "soft_round_limit_reached": False,
        "battle_complete": False,
        "can_continue": True,
        "next_action": "continue",
        **({"model_error": model_error} if model_error else {}),
    }


def handle_chat_round(payload: dict[str, Any]) -> dict[str, Any]:
    """Process a user reply and return the next judge question.

    Voice mode note:
      user_message may be a typed string or a transcript from voice input.
      battle_flow.classify_answer_quality() handles both the same way.
    """
    session_id = payload.get("session_id", "")
    message = (
        payload.get("user_message") or payload.get("message") or ""
    ).strip()

    session = session_manager.get_session(session_id)
    if not session:
        return {
            "session_id": session_id,
            "error": "Session not found",
            "round": 0,
            "pressure_level": "High",
            "attack_tag": "Session Error",
            "ai_message": "Session expired. Please start a new battle.",
            "model_ok": False,
            "provider": "none",
            "model_mode": "none",
        }

    if message:
        session_manager.append_user_message(session_id, message)

    persona = session.get("persona", "technical_judge")
    difficulty = session.get("difficulty", "high")
    startup = session.get("startup", {})
    model_mode = session.get("model_mode", "premium_nvidia")
    next_round = session_manager.increment_round(session_id)

    soft_limit = next_round >= MAX_ROUNDS

    # Determine current attack tag from last AI message
    current_attack_tag = battle_flow.get_current_attack_tag(session)
    if not current_attack_tag:
        current_attack_tag = get_next_attack_tag(persona, next_round)

    # Classify answer quality (rule-based, no extra API call)
    answer_quality_result = {"quality": "partial", "reason": "No message provided.", "signals": []}
    if message:
        try:
            answer_quality_result = battle_flow.classify_answer_quality(message)
        except Exception as exc:
            logger.warning("battle_flow.classify_answer_quality error: %s", exc)

    quality = answer_quality_result.get("quality", "partial")

    # Decide judge action
    judge_action_result: dict[str, Any] = {}
    try:
        judge_action_result = battle_flow.decide_next_judge_action(
            session, current_attack_tag, quality, persona
        )
    except Exception as exc:
        logger.warning("battle_flow.decide_next_judge_action error: %s", exc)
        judge_action_result = {
            "judge_action": "follow_up_same_tag",
            "next_attack_tag": current_attack_tag,
            "previous_attack_tag": current_attack_tag,
            "attempt_number_for_tag": 1,
            "topic_satisfied": False,
            "transition_note": "Fallback due to decision error.",
        }

    # Update session battle state
    try:
        battle_flow.update_battle_state(session, current_attack_tag, answer_quality_result, judge_action_result)
    except Exception as exc:
        logger.warning("battle_flow.update_battle_state error: %s", exc)

    attack_tag = judge_action_result.get("next_attack_tag", current_attack_tag)

    # Mock fallback
    followups = MOCK_FOLLOWUPS.get(persona, MOCK_FOLLOWUPS["technical_judge"])
    index = min(next_round - 2, len(followups) - 1)
    mock_ai_message = followups[max(0, index)]

    ai_message = mock_ai_message
    model_ok = False
    provider = "mock"
    used_model_mode = "mock_fallback"
    model_error: str | None = None

    try:
        # Cap history sent to model; full history preserved in session for scorecard
        recent_history = _recent_history(session_id)
        messages = _build_followup_messages(
            startup,
            persona,
            difficulty,
            attack_tag,
            recent_history,
            judge_action_result,
            answer_quality_result,
        )
        result = model_router.generate_opponent_response(
            messages,
            model_mode=model_mode,
            persona=persona,
            attack_tag=attack_tag,
        )
        if result.get("ok") and result.get("content"):
            ai_message = sanitize_model_output(result["content"])
            model_ok = True
            provider = result.get("provider", "nvidia")
            used_model_mode = result.get("model_mode", model_mode)
        else:
            model_error = result.get("error") or "Model returned empty response"
            logger.warning("chat_round: model not ok — using mock. error=%s", model_error)
    except Exception as exc:
        model_error = str(exc)
        logger.warning("chat_round: model call raised — using mock. error=%s", exc)

    session_manager.append_ai_message(session_id, ai_message, attack_tag)

    return {
        "session_id": session_id,
        "round": next_round,
        "pressure_level": pressure_level(next_round),
        "battle_phase": get_battle_phase(next_round),
        "attack_tag": attack_tag,
        "ai_message": ai_message,
        "model_mode": used_model_mode,
        "provider": provider,
        "model_ok": model_ok,
        "answer_quality": quality,
        "answer_quality_reason": answer_quality_result.get("reason", ""),
        "judge_action": judge_action_result.get("judge_action", "follow_up_same_tag"),
        "previous_attack_tag": judge_action_result.get("previous_attack_tag", current_attack_tag),
        "topic_satisfied": judge_action_result.get("topic_satisfied", False),
        "tag_attempt": judge_action_result.get("attempt_number_for_tag", 1),
        "battle_complete": False,
        "can_continue": True,
        "next_action": "continue",
        "soft_round_limit_reached": soft_limit,
        "rounds_soft_limit_reached": soft_limit,
        "recommended_action": "end_battle" if soft_limit else None,
        "completion_message": (
            "You have enough material for a scorecard. You can end the battle now or continue practicing."
            if soft_limit else None
        ),
        **({"model_error": model_error} if model_error else {}),
    }


def handle_end_battle(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate and return a Nemotron scorecard for the completed battle.

    Falls back to mock_scorecard if the model call or JSON parsing fails.
    Never crashes for a valid session.

    Voice mode note:
        Session history contains plain text regardless of input source.
        No changes are needed here when voice mode is integrated.
    """
    session_id = payload.get("session_id", "")
    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    try:
        scorecard = generate_claim_based_scorecard(session)
    except Exception as exc:
        logger.warning("handle_end_battle: generate_claim_based_scorecard raised: %s", exc)
        try:
            signals = extract_concrete_signals(session)
            scorecard = build_session_aware_fallback_scorecard(
                session, signals, f"Scorecard generation error: {type(exc).__name__}"
            )
        except Exception as exc2:
            logger.warning("handle_end_battle: session-aware fallback also raised: %s", exc2)
            scorecard = mock_scorecard(session)
            scorecard["model_error"] = f"Scorecard generation error: {type(exc).__name__}"

    return scorecard


def handle_reset_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Clear a battle session."""
    session_id = payload.get("session_id", "")
    session_manager.reset_session(session_id)
    return {"status": "reset"}


def handle_voice_pitch_placeholder(_payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Reserved endpoint for voice pitch mode."""
    return {
        "status": "not_implemented",
        "message": (
            "Voice Mode endpoint is reserved and will be connected "
            "after transcription integration."
        ),
    }


def handle_deal_session_placeholder(_payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Reserved endpoint for Deal Battle mode."""
    return {
        "status": "not_implemented",
        "message": (
            "Deal Battle endpoint is reserved and will be connected "
            "in a later phase."
        ),
    }


def handle_deck_critique_placeholder(_payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Reserved endpoint for pitch deck critique."""
    return {
        "status": "not_implemented",
        "message": (
            "Deck critique endpoint is reserved and will be connected "
            "after MiniCPM-V vision integration."
        ),
    }
