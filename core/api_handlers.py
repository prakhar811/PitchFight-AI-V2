"""PitchFight AI — shared API handler functions for REST and Gradio routes."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from dotenv import load_dotenv

from core.attack_tags import get_attack_tags, get_next_attack_tag, get_answer_checklist
from core.persona_builder import build_persona_prompt
from core.samples import get_sample_startup
from core.scoring_engine import (
    mock_scorecard,
    generate_real_scorecard,
    generate_claim_based_scorecard,
    build_session_aware_fallback_scorecard,
)
from core.claim_extractor import extract_concrete_signals
from core.judge_settings import normalize_difficulty, get_label, get_pressure_display_label
from core import battle_flow
from core import model_router
from core import session_manager
from core.output_sanitizer import sanitize_model_output
from core import voice_handler
from core import retry_handler
from core import session_repository
from core.deal_verdict import build_judge_verdict
from core.deal_phase import start_deal_phase
from core.deal_flow import next_deal_round
from core.deal_scoring_engine import generate_deal_scorecard
from core.json_utils import parse_model_json

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


import re as _re

_HAS_NUMBER = _re.compile(r"\d")
_HAS_USER_WORD = _re.compile(
    r"\b(users?|customers?|students?|people|patients?|teachers?|clients?|founders?|hospitals?)\b",
    _re.IGNORECASE,
)


def _micro_coach_tip(message: str, quality: str, attack_tag: str, difficulty_profile: str) -> str:
    """One short, encouraging nudge after a round — teaches the next answer, not the score.

    Local only (no API). Trains the founder toward 'minimum viable answer': one number,
    one user, one real result. Kept gentle for Practice; empty when nothing useful to add.
    """
    text = (message or "").strip()
    if not text:
        return ""
    if quality == "non_answer":
        return "Take a real guess next time — even one specific detail beats a blank."

    has_number = bool(_HAS_NUMBER.search(text))
    has_user = bool(_HAS_USER_WORD.search(text))

    if not has_number:
        return "Good start — next time add one number (a count, a result, or a price)."
    if not has_user:
        return "Nice, you gave a number — next time say who it's for or who it's from."
    return "Solid — to go further, tie that proof directly to the question asked."


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
    # Accept difficulty_profile (new) or difficulty (legacy) — normalize both
    raw_difficulty = (
        payload.get("difficulty_profile")
        or payload.get("difficulty")
        or "practice"
    )
    difficulty_profile = normalize_difficulty(raw_difficulty)
    difficulty_label = get_label(difficulty_profile)
    input_mode = payload.get("input_mode", "text")
    mode = payload.get("mode", "pitch_battle")
    model_mode = payload.get("model_mode", "premium_nvidia")

    session = session_manager.create_session(
        startup, persona, difficulty_profile, input_mode
    )
    session["mode"] = mode
    session["model_mode"] = model_mode
    # Store normalized profile so scorecard and chat rounds can use it
    session["difficulty_profile"] = difficulty_profile
    session["difficulty_label"] = difficulty_label

    voice_pitch = payload.get("voice_pitch")
    if input_mode == "voice" and isinstance(voice_pitch, dict):
        session_manager.set_voice_pitch(session["session_id"], voice_pitch)

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
        messages = _build_opening_messages(startup, persona, difficulty_profile, mock_attack_tag)
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

    # Phase 9.5: persist fully-populated session (opening message already in history).
    session_repository.save_session(session)

    _phase_start = get_battle_phase(1)
    return {
        "session_id": session["session_id"],
        "round": 1,
        "pressure_level": pressure_level(1),
        "battle_phase": _phase_start,
        "pressure_label": get_pressure_display_label(difficulty_profile, _phase_start),
        "attack_tag": attack_tag,
        "answer_hint": get_answer_checklist(attack_tag),
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
        "difficulty_profile": difficulty_profile,
        "difficulty_label": difficulty_label,
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
    # Use stored normalized profile; fall back to normalizing legacy difficulty field
    difficulty_profile = session.get("difficulty_profile") or normalize_difficulty(
        session.get("difficulty", "practice")
    )
    difficulty_label = session.get("difficulty_label") or get_label(difficulty_profile)
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
            difficulty_profile,
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

    # Phase 9.5: persist the new user + judge history entries (last 2 appended above).
    session_repository.update_round(session_id, session.get("history", [])[-2:])

    input_mode = payload.get("input_mode") or session.get("input_mode", "text")
    voice_turn_id = payload.get("voice_turn_id", "")
    if input_mode == "voice" and voice_turn_id and message:
        voice_handler.confirm_voice_turn(session_id, voice_turn_id, message)

    _phase_chat = get_battle_phase(next_round)
    return {
        "session_id": session_id,
        "round": next_round,
        "pressure_level": pressure_level(next_round),
        "battle_phase": _phase_chat,
        "pressure_label": get_pressure_display_label(difficulty_profile, _phase_chat),
        "attack_tag": attack_tag,
        "answer_hint": get_answer_checklist(attack_tag),
        "micro_coach": _micro_coach_tip(message, quality, current_attack_tag, difficulty_profile),
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
        "difficulty_profile": difficulty_profile,
        "difficulty_label": difficulty_label,
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

    voice_summary = voice_handler.build_voice_delivery_summary(session)
    if voice_summary:
        scorecard["voice_delivery"] = voice_summary

    session["latest_scorecard"] = scorecard

    # Phase 9.5: persist scorecard and battle summary after in-memory mutation.
    session_repository.save_scorecard(session_id, scorecard)
    session_repository.update_battle_summary(session_id, {
        "total_rounds": session.get("round", 0),
        "final_round": session.get("round", 0),
        "status": "completed",
        "battle_complete": True,
    })

    try:
        judge_verdict = build_judge_verdict(session, scorecard)
        session["judge_verdict"] = judge_verdict
        scorecard["judge_verdict"] = judge_verdict
        # Phase 9.5: persist judge verdict after it is stored on session.
        session_repository.save_judge_verdict(session_id, judge_verdict)
    except Exception as exc:
        logger.warning("handle_end_battle: judge verdict failed: %s", exc)

    return scorecard


def handle_start_deal_phase(payload: dict[str, Any]) -> dict[str, Any]:
    """Start integrated deal phase from pitch session."""
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return {"error": "session_id is required"}

    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    try:
        result = start_deal_phase(session)
        # Phase 9.5: persist the opening judge deal message after deal_history is populated.
        if isinstance(result, dict) and "error" not in result:
            deal_history = session.get("deal_history", [])
            if deal_history:
                session_repository.update_deal_round(session_id, deal_history[-1])
        return result
    except Exception as exc:
        logger.warning("handle_start_deal_phase raised: %s", exc)
        return {"error": "Could not start deal phase."}


def handle_deal_round(payload: dict[str, Any]) -> dict[str, Any]:
    """Process one deal negotiation round."""
    session_id = str(payload.get("session_id", "")).strip()
    message = str(payload.get("user_message", "")).strip()
    input_mode = str(payload.get("input_mode", "text") or "text")
    voice_turn_id = str(payload.get("voice_turn_id", "") or "")

    if not session_id:
        return {"error": "session_id is required"}

    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    if input_mode == "voice" and voice_turn_id and message:
        voice_handler.confirm_voice_turn(session_id, voice_turn_id, message)

    try:
        result = next_deal_round(session, message, input_mode=input_mode, voice_turn_id=voice_turn_id)
        # Phase 9.5: persist the new founder + judge deal entries (last 2 appended above).
        if isinstance(result, dict) and "error" not in result:
            deal_history = session.get("deal_history", [])
            new_entries = deal_history[-2:] if len(deal_history) >= 2 else deal_history
            if new_entries:
                session_repository.update_deal_round(session_id, new_entries)
        return result
    except Exception as exc:
        logger.warning("handle_deal_round raised: %s", exc)
        return {"error": "Could not process deal round."}


def handle_end_deal(payload: dict[str, Any]) -> dict[str, Any]:
    """End deal phase and return deal + combined scorecards."""
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return {"error": "session_id is required"}

    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    try:
        result = generate_deal_scorecard(session)
        # Phase 9.5: persist deal scorecard + combined scorecard after generation.
        if isinstance(result, dict) and "error" not in result:
            session_repository.save_deal_scorecard(
                session_id,
                result.get("deal_scorecard") or {},
                result.get("combined_scorecard") or {},
            )
        return result
    except Exception as exc:
        logger.warning("handle_end_deal raised: %s", exc)
        return {"error": "Could not generate deal scorecard."}


def handle_retry_weakest_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a retry drill from the latest scorecard answer_to_retry."""
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return {"error": "session_id is required"}

    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    try:
        result = retry_handler.start_retry_drill(session)
        # Phase 9.5: persist the newly created drill after it is stored on session.
        retry_id = result.get("retry_id") if isinstance(result, dict) else None
        if retry_id and "error" not in result:
            drill = session.get("retry_drills", {}).get(retry_id)
            if drill:
                session_repository.save_retry_drill(session_id, drill)
        return result
    except Exception as exc:
        logger.warning("handle_retry_weakest_start raised: %s", exc)
        return {"error": "Could not start retry drill. Try ending a battle first."}


def handle_retry_weakest_submit(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a retry answer against the original weak answer."""
    session_id = str(payload.get("session_id", "")).strip()
    retry_id = str(payload.get("retry_id", "")).strip()
    retry_answer = str(payload.get("retry_answer", "")).strip()
    input_mode = str(payload.get("input_mode", "text") or "text")
    voice_turn_id = str(payload.get("voice_turn_id", "") or "")

    if not session_id:
        return {"error": "session_id is required"}
    if not retry_id:
        return {"error": "retry_id is required"}

    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    if input_mode == "voice" and voice_turn_id and retry_answer:
        voice_handler.confirm_voice_turn(session_id, voice_turn_id, retry_answer)

    try:
        result = retry_handler.evaluate_retry_answer(
            session,
            retry_id,
            retry_answer,
            input_mode=input_mode,
            voice_turn_id=voice_turn_id,
        )
        # Phase 9.5: persist updated drill, scorecard, and refreshed verdict after eval.
        if isinstance(result, dict) and "error" not in result:
            drill = session.get("retry_drills", {}).get(retry_id)
            if drill:
                session_repository.save_retry_drill(session_id, drill)
            latest_scorecard = session.get("latest_scorecard")
            if isinstance(latest_scorecard, dict):
                session_repository.save_scorecard(session_id, latest_scorecard)
            latest_verdict = session.get("judge_verdict")
            if isinstance(latest_verdict, dict):
                session_repository.save_judge_verdict(session_id, latest_verdict)
        return result
    except Exception as exc:
        logger.warning("handle_retry_weakest_submit raised: %s", exc)
        return {"error": "Could not evaluate retry answer. Please try again."}


def handle_reset_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Clear a battle session."""
    session_id = payload.get("session_id", "")
    session_manager.reset_session(session_id)
    return {"status": "reset"}


_STARTUP_CONTEXT_FIELDS = (
    "name",
    "problem",
    "target_users",
    "solution",
    "why_ai",
    "traction",
    "competitors",
    "ask",
)

_STRUCTURE_PITCH_PROMPT = """You are structuring a founder's spoken or written startup pitch for a pitch battle app.

Extract ONLY what the founder actually said or wrote.
Do not hallucinate traction, competitors, funding, or users.
If a field was not mentioned, use an empty string and list it in missing_fields.

Return ONLY valid JSON.
First character must be {.
Last character must be }.
No markdown.
No explanation.
No reasoning.

Required JSON:
{
"startup_context": {
"name": "",
"problem": "",
"target_users": "",
"solution": "",
"why_ai": "",
"traction": "",
"competitors": "",
"ask": ""
},
"missing_fields": [],
"confidence": "low",
"brief_summary": ""
}

confidence must be one of: low, medium, high
brief_summary: one sentence summary of the pitch in the founder's words."""


def _normalize_startup_context(raw: dict[str, Any] | None) -> dict[str, str]:
    ctx = raw if isinstance(raw, dict) else {}
    return {field: str(ctx.get(field, "")).strip() for field in _STARTUP_CONTEXT_FIELDS}


def _missing_startup_fields(ctx: dict[str, str]) -> list[str]:
    return [field for field in _STARTUP_CONTEXT_FIELDS if not ctx.get(field)]


def _confidence_from_fill(ctx: dict[str, str]) -> str:
    filled = sum(1 for field in _STARTUP_CONTEXT_FIELDS if ctx.get(field))
    if filled >= 5:
        return "high"
    if filled >= 3:
        return "medium"
    return "low"


def _structure_pitch_local_fallback(pitch_text: str) -> dict[str, Any]:
    """Heuristic extraction when Nemotron is unavailable."""
    text = pitch_text.strip()
    lower = text.lower()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    ctx = {field: "" for field in _STARTUP_CONTEXT_FIELDS}

    name_patterns = [
        r"(?:called|named)\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,3})",
        r"(?:building|build|creating|launching)\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2})",
        r"\b([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,2}\s+AI)\b",
        r"(?:we(?:'re| are))\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2})",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text)
        if match:
            ctx["name"] = match.group(1).strip()
            break

    problem_kw = ("problem", "pain", "miss", "struggle", "hard to", "difficult", "scattered", "frustrat")
    for sentence in sentences:
        sl = sentence.lower()
        if any(kw in sl for kw in problem_kw):
            ctx["problem"] = sentence
            break

    user_kw = ("students", "founders", "users", "customers", "developers", "teams", "college")
    for sentence in sentences:
        sl = sentence.lower()
        if any(kw in sl for kw in user_kw):
            ctx["target_users"] = sentence
            break
    if not ctx["target_users"]:
        for kw in user_kw:
            if kw in lower:
                ctx["target_users"] = f"Targeting {kw}."
                break

    solution_kw = ("we build", "we're building", "we are building", "platform", "app", "product", "tool")
    for sentence in sentences:
        sl = sentence.lower()
        if any(kw in sl for kw in solution_kw):
            ctx["solution"] = sentence
            break

    if "ai" in lower or "machine learning" in lower or "model" in lower:
        for sentence in sentences:
            sl = sentence.lower()
            if "ai" in sl or "model" in sl or "machine learning" in sl:
                ctx["why_ai"] = sentence
                break
        if not ctx["why_ai"]:
            ctx["why_ai"] = "Uses AI as described in the pitch."

    traction_patterns = [
        r"\b\d[\d,]*\+?\s*(?:users|students|customers|signups|downloads|pilots?)\b",
        r"\b(?:tested with|pilot with|revenue|mrr|arr)\b[^.?!]*[.?!]?",
        r"\b\d+%\b[^.?!]*[.?!]?",
    ]
    for pattern in traction_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            ctx["traction"] = match.group(0).strip().rstrip(".")
            break

    competitor_kw = ("competitor", "versus", " vs ", "compared to", "alternative", "luma", "linkedin")
    for sentence in sentences:
        sl = sentence.lower()
        if any(kw in sl for kw in competitor_kw):
            ctx["competitors"] = sentence
            break

    ask_kw = ("funding", "invest", "mentor", "pilot", "sponsor", "partnership", "raise", "support")
    for sentence in sentences:
        sl = sentence.lower()
        if any(kw in sl for kw in ask_kw):
            ctx["ask"] = sentence
            break

    missing = _missing_startup_fields(ctx)
    summary = " ".join(sentences[:2])[:220] if sentences else text[:220]

    return {
        "ok": True,
        "startup_context": ctx,
        "missing_fields": missing,
        "confidence": _confidence_from_fill(ctx),
        "brief_summary": summary,
        "source": "local_fallback",
    }


def _parse_structure_pitch_response(raw: str) -> dict[str, Any] | None:
    parsed, _ = parse_model_json(raw)
    if not isinstance(parsed, dict):
        return None

    ctx = _normalize_startup_context(parsed.get("startup_context"))
    missing = parsed.get("missing_fields")
    if not isinstance(missing, list):
        missing = _missing_startup_fields(ctx)
    else:
        missing = [str(f).strip() for f in missing if str(f).strip() in _STARTUP_CONTEXT_FIELDS]

    confidence = str(parsed.get("confidence", "")).strip().lower()
    if confidence not in ("low", "medium", "high"):
        confidence = _confidence_from_fill(ctx)

    summary = str(parsed.get("brief_summary", "")).strip()
    if not summary:
        summary = ctx.get("solution") or ctx.get("problem") or ""

    return {
        "startup_context": ctx,
        "missing_fields": missing,
        "confidence": confidence,
        "brief_summary": summary,
    }


def handle_structure_pitch(payload: dict[str, Any]) -> dict[str, Any]:
    """Structure free-form pitch text into startup_context fields."""
    pitch_text = str(payload.get("pitch_text", "")).strip()
    if not pitch_text:
        return {"ok": False, "error": "pitch_text is required and must be non-empty."}

    if len(pitch_text) < 20:
        return {"ok": False, "error": "pitch_text is too short. Add a few more details about your startup."}

    model_mode = payload.get("model_mode", "premium_nvidia")
    messages = [
        {"role": "system", "content": _STRUCTURE_PITCH_PROMPT},
        {"role": "user", "content": f"Founder pitch:\n\n{pitch_text[:6000]}"},
    ]

    try:
        result = model_router.generate_structure_pitch_response(messages, model_mode=model_mode)
        if result.get("ok") and result.get("content"):
            structured = _parse_structure_pitch_response(result["content"])
            if structured is None:
                repair = model_router.generate_structure_pitch_repair_response(
                    result["content"], model_mode=model_mode
                )
                if repair.get("ok") and repair.get("content"):
                    structured = _parse_structure_pitch_response(repair["content"])

            if structured is not None:
                return {
                    "ok": True,
                    "startup_context": structured["startup_context"],
                    "missing_fields": structured["missing_fields"],
                    "confidence": structured["confidence"],
                    "brief_summary": structured["brief_summary"],
                    "source": "nemotron",
                }
            logger.warning("structure_pitch: Nemotron returned unparseable JSON — using local fallback")
    except Exception as exc:
        logger.warning("structure_pitch: Nemotron call failed — using local fallback: %s", exc)

    return _structure_pitch_local_fallback(pitch_text)


def handle_voice_pitch(payload: dict[str, Any]) -> dict[str, Any]:
    """Process opening spoken pitch audio via Nemotron Omni."""
    audio = payload.get("audio") or payload.get("audio_base64") or ""
    audio_format = payload.get("audio_format", "webm")
    return voice_handler.process_voice_pitch(str(audio), str(audio_format))


def handle_voice_turn(payload: dict[str, Any]) -> dict[str, Any]:
    """Process one spoken battle answer — returns transcript for confirmation."""
    session_id = payload.get("session_id", "")
    audio = payload.get("audio") or payload.get("audio_base64") or ""
    audio_format = payload.get("audio_format", "webm")
    return voice_handler.process_voice_turn(session_id, str(audio), str(audio_format))


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
