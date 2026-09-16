"""Deal phase start helpers (Phase 9B)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from core.deal_persona_builder import DEAL_TYPE_LABELS, build_deal_system_prompt, get_persona_display
from core.judge_settings import get_label
from core import model_router

logger = logging.getLogger(__name__)

NEGOTIATION_TAGS = [
    "Anchoring",
    "Evidence Quality",
    "Concession Control",
    "Alternatives",
    "Value Articulation",
    "Closing Move",
]

_DEAL_FIRST_FALLBACK: dict[str, str] = {
    "equity": (
        "You mentioned traction in your pitch, but it is not enough for your full ask. "
        "I would open below your terms. Convince me why I should move closer to what you want."
    ),
    "mentorship": (
        "You clearly need help sharpening execution. I can offer limited mentorship time, "
        "but I need you to define exactly what outcome you want from me."
    ),
    "pilot": (
        "I am open to a pilot, but I will not approve a long free trial without risk controls. "
        "What paid pilot structure can you defend?"
    ),
    "sponsorship": (
        "I can consider sponsorship, but I need measurable return and audience quality. "
        "What do we get for the budget you are asking?"
    ),
}


def get_deal_negotiation_tags(deal_type: str) -> list[str]:
    return list(NEGOTIATION_TAGS)


def build_deal_context(session: dict) -> dict[str, Any]:
    """Build deal context from session, scorecard, and verdict."""
    startup = session.get("startup", {}) or {}
    verdict = session.get("judge_verdict") or {}
    scorecard = session.get("latest_scorecard") or {}
    difficulty_profile = session.get("difficulty_profile") or session.get("difficulty", "practice")
    deal_type = session.get("deal_type") or verdict.get("deal_type", "equity")

    return {
        "ask": str(startup.get("ask", "")).strip(),
        "opening_offer": str(verdict.get("deal_opening_offer", "")).strip(),
        "founder_position": str(startup.get("ask", "")).strip(),
        "judge_position": str(verdict.get("deal_opening_offer", "")).strip(),
        "deal_type": deal_type,
        "deal_type_label": DEAL_TYPE_LABELS.get(deal_type, deal_type),
        "pitch_overall": scorecard.get("overall", 0),
        "traction": str(startup.get("traction", "")).strip(),
        "startup_name": str(startup.get("name", "")).strip(),
        "difficulty_profile": difficulty_profile,
        "difficulty_label": get_label(difficulty_profile),
    }


def _build_first_deal_messages(session: dict, deal_context: dict) -> list[dict[str, str]]:
    system = build_deal_system_prompt(session, deal_context, "Anchoring")
    startup = session.get("startup", {}) or {}
    verdict = session.get("judge_verdict") or {}

    user = (
        f"Transition from pitch to deal negotiation.\n"
        f"Startup: {startup.get('name', '')}\n"
        f"Traction: {startup.get('traction', '')}\n"
        f"Founder's ask: {deal_context.get('ask', '')}\n"
        f"Your opening offer: {deal_context.get('opening_offer', '')}\n"
        f"Verdict reaction: {verdict.get('judge_reaction', '')}\n\n"
        "Deliver your first deal negotiation message. Reference the pitch if possible. "
        "1-3 sentences. One pushback or opening terms. Plain text only."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_first_deal_message(session: dict, deal_context: dict) -> dict[str, str]:
    """Generate first deal message via Nemotron with local fallback."""
    deal_type = deal_context.get("deal_type", "equity")
    fallback = _DEAL_FIRST_FALLBACK.get(deal_type, _DEAL_FIRST_FALLBACK["equity"])

    verdict = session.get("judge_verdict") or {}
    if verdict.get("judge_reaction"):
        fallback = str(verdict["judge_reaction"])
        if deal_context.get("opening_offer"):
            fallback += f" {deal_context['opening_offer']}"

    messages = _build_first_deal_messages(session, deal_context)
    model_mode = session.get("model_mode", "premium_nvidia")
    result = model_router.generate_deal_round_response(messages, model_mode=model_mode)

    if result.get("ok") and result.get("content"):
        text = str(result["content"]).strip()
        if text:
            return {"ai_message": text[:600], "provider": result.get("provider", "nvidia")}

    logger.warning("deal_phase: first message fallback — %s", result.get("error"))
    return {"ai_message": fallback[:600], "provider": "local"}


def start_deal_phase(session: dict) -> dict[str, Any]:
    """Initialize deal phase on existing pitch session."""
    if not session.get("latest_scorecard"):
        return {"error": "No scorecard found. End a battle before starting deal phase."}

    verdict = session.get("judge_verdict")
    if not verdict:
        return {"error": "No judge verdict found. End a battle first."}

    if not verdict.get("can_continue_to_deal"):
        return {
            "error": (
                f"Deal phase cannot start because the judge verdict is "
                f"{verdict.get('interest_level', 'no_interest')}."
            )
        }

    if session.get("deal_phase_active") and session.get("deal_history"):
        deal_context = session.get("deal_context") or build_deal_context(session)
        last_judge = next(
            (h for h in reversed(session.get("deal_history", [])) if h.get("role") == "judge"),
            None,
        )
        return {
            "session_id": session.get("session_id", ""),
            "deal_phase_id": session.get("deal_phase_id", ""),
            "deal_type": session.get("deal_type", ""),
            "persona_name": verdict.get("persona_name", ""),
            "persona_role": verdict.get("persona_type", ""),
            "round": session.get("deal_round", 1),
            "negotiation_tag": last_judge.get("negotiation_tag", "Anchoring") if last_judge else "Anchoring",
            "ai_message": last_judge.get("message", "") if last_judge else "",
            "deal_context": deal_context,
            "can_continue": True,
            "soft_limit_reached": False,
        }

    deal_phase_id = str(uuid.uuid4())
    deal_type = verdict.get("deal_type", "equity")
    deal_context = build_deal_context(session)
    persona_name, persona_role = get_persona_display(session.get("persona", "skeptical_vc"))

    first = build_first_deal_message(session, deal_context)
    ai_message = first["ai_message"]
    tag = "Anchoring"

    session["deal_phase_active"] = True
    session["deal_phase_id"] = deal_phase_id
    session["deal_type"] = deal_type
    session["deal_context"] = deal_context
    session["deal_round"] = 1
    session["deal_history"] = [{
        "round": 1,
        "role": "judge",
        "message": ai_message,
        "negotiation_tag": tag,
        "answer_quality": "",
        "action": "opening",
        "input_mode": "",
        "voice_turn_id": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]
    session["deal_scorecard"] = {}
    session["combined_scorecard"] = {}

    return {
        "session_id": session.get("session_id", ""),
        "deal_phase_id": deal_phase_id,
        "deal_type": deal_type,
        "persona_name": persona_name,
        "persona_role": persona_role,
        "round": 1,
        "negotiation_tag": tag,
        "ai_message": ai_message,
        "deal_context": deal_context,
        "can_continue": True,
        "soft_limit_reached": False,
    }
