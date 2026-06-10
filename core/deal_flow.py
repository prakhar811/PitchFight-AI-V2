"""Deal negotiation round flow (Phase 9C)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from core.deal_claim_extractor import extract_deal_signals
from core.deal_persona_builder import build_deal_system_prompt, build_deal_round_prompt
from core.deal_phase import NEGOTIATION_TAGS
from core import model_router

logger = logging.getLogger(__name__)

# Adaptive deal length — measured in FOUNDER replies, not raw round counter.
MIN_FOUNDER_REPLIES = 3   # below this we never recommend ending
SOFT_FOUNDER_REPLIES = 4  # ideal length; soft-recommend ending around here
HARD_MAX_FOUNDER_REPLIES = 6  # never force more than this

# Kept for backward compatibility with existing callers/tests.
MAX_DEAL_ROUNDS = 8
SOFT_DEAL_LIMIT = 5

_ALL_DEAL_DIMS = (
    "anchoring", "evidence", "concession_control",
    "alternatives", "value_articulation", "closing",
)


def _count_founder_replies(session: dict) -> int:
    return sum(1 for h in session.get("deal_history", []) if h.get("role") == "user")


def evaluate_deal_readiness(session: dict) -> dict[str, Any]:
    """Decide whether enough negotiation signal exists to score the deal.

    Returns a readiness dict (see schema in PART A). Driven by how many dimensions
    the founder has actually touched plus the number of founder replies, so the deal
    can end naturally after 3–4 strong replies instead of grinding fixed rounds.
    """
    history = session.get("deal_history") or []
    deal_context = session.get("deal_context") or {}
    signals = extract_deal_signals(history, deal_context)
    replies = _count_founder_replies(session)

    covered: list[str] = []
    if signals.get("anchor_points") or signals.get("counteroffers"):
        covered.append("anchoring")
    if signals.get("evidence_signals") or signals.get("specific_numbers"):
        covered.append("evidence")
    has_concession = bool(
        signals.get("concession_signals")
        or signals.get("tradeoffs")
        or signals.get("weak_concession_signals")
    )
    if has_concession:
        covered.append("concession_control")
    if signals.get("alternative_signals"):
        covered.append("alternatives")
    if signals.get("value_signals"):
        covered.append("value_articulation")
    if signals.get("closing_signals"):
        covered.append("closing")

    missing = [d for d in _ALL_DEAL_DIMS if d not in covered]

    # Core negotiation evidence: anchor/counter + proof + a concession/tradeoff + value.
    core_ready = (
        ("anchoring" in covered)
        and ("evidence" in covered)
        and has_concession
        and ("value_articulation" in covered)
    )
    enough = (replies >= MIN_FOUNDER_REPLIES and core_ready) or replies >= HARD_MAX_FOUNDER_REPLIES

    if len(covered) >= 5 and replies >= SOFT_FOUNDER_REPLIES:
        confidence = "high"
    elif enough:
        confidence = "medium"
    else:
        confidence = "low"

    if replies >= HARD_MAX_FOUNDER_REPLIES:
        action = "force_end"
        reason = "You have negotiated enough rounds — time to lock in your deal scorecard."
    elif enough and replies >= SOFT_FOUNDER_REPLIES:
        action = "recommend_end"
        reason = "You have enough negotiation material for a scorecard."
    elif enough:
        action = "recommend_end"
        reason = "You have covered the key negotiation points. End now or push one more round."
    else:
        action = "continue"
        reason = "Keep negotiating — anchor your terms, cite proof, and propose a tradeoff."

    return {
        "enough_to_score": bool(enough),
        "recommended_action": action,
        "reason": reason,
        "covered_dimensions": covered,
        "missing_dimensions": missing,
        "rounds_completed": replies,
        "confidence": confidence,
    }

_NON_ANSWER = re.compile(
    r"^(ok|yeah|yes|no|idk|i don'?t know|not sure|maybe|n/?a|pass)\.?$",
    re.IGNORECASE,
)

_VALID_ACTIONS = frozenset({
    "acknowledge_and_counter",
    "press_harder",
    "escalate_stakes",
    "partial_concession",
    "move_to_close",
})


def classify_deal_answer_quality(
    user_message: str,
    deal_context: dict,
    current_tag: str,
) -> str:
    """Classify founder deal answer: strong | partial | weak | non_answer."""
    text = (user_message or "").strip()
    if not text or _NON_ANSWER.match(text) or len(text.split()) < 3:
        return "non_answer"

    signals = extract_deal_signals(
        [{"role": "user", "message": text}],
        deal_context,
    )

    if signals.get("weak_concession_signals") and not signals.get("counteroffers"):
        return "weak"

    has_proof = bool(
        signals.get("specific_numbers")
        or signals.get("evidence_signals")
        or signals.get("counteroffers")
    )
    has_anchor = bool(signals.get("anchor_points") or signals.get("tradeoffs"))

    if current_tag == "Closing Move" and signals.get("closing_signals"):
        return "strong"
    if has_proof and has_anchor and len(text.split()) >= 12:
        return "strong"
    if has_proof or has_anchor:
        return "partial"
    if signals.get("concession_signals") and not has_proof:
        return "weak"
    if len(text.split()) >= 8:
        return "partial"
    return "weak"


def choose_next_negotiation_tag(session: dict) -> str:
    """Pick next tag based on round and history."""
    history = session.get("deal_history") or []
    used = [h.get("negotiation_tag") for h in history if h.get("negotiation_tag")]
    deal_round = session.get("deal_round", 1)

    if deal_round >= 6:
        return "Closing Move"
    if deal_round >= 4 and "Evidence Quality" not in used:
        return "Evidence Quality"
    if deal_round >= 3 and "Concession Control" not in used:
        return "Concession Control"

    for tag in NEGOTIATION_TAGS:
        if tag not in used:
            return tag
    return NEGOTIATION_TAGS[(deal_round - 1) % len(NEGOTIATION_TAGS)]


def choose_deal_action(answer_quality: str, tag: str, session: dict) -> str:
    """Map answer quality + tag to judge action."""
    if answer_quality == "non_answer":
        return "press_harder"
    if answer_quality == "weak":
        return "escalate_stakes" if tag in ("Anchoring", "Concession Control") else "press_harder"
    if answer_quality == "strong" and tag == "Closing Move":
        return "partial_concession"
    if answer_quality == "strong":
        return "acknowledge_and_counter"
    if tag == "Closing Move":
        return "move_to_close"
    if tag == "Concession Control":
        return "press_harder"
    return "acknowledge_and_counter"


def should_soft_limit_deal(session: dict) -> bool:
    return _count_founder_replies(session) >= SOFT_FOUNDER_REPLIES


def _deal_state(signals: dict, answer_quality: str) -> dict[str, str]:
    weak_con = bool(signals.get("weak_concession_signals"))
    if answer_quality == "strong":
        founder = "strong"
    elif answer_quality in ("partial", "weak") and not weak_con:
        founder = "mixed"
    else:
        founder = "weak"

    if answer_quality == "strong":
        momentum = "improving"
    elif answer_quality == "non_answer" or weak_con:
        momentum = "declining"
    else:
        momentum = "neutral"

    concession = "none"
    if signals.get("concession_signals") and not weak_con:
        concession = "small"
    if weak_con:
        concession = "medium"

    return {
        "judge_concession_level": concession,
        "founder_position_strength": founder,
        "deal_momentum": momentum,
    }


def _generate_deal_ai_message(
    session: dict,
    user_message: str,
    negotiation_tag: str,
    answer_quality: str,
    action: str,
) -> str:
    deal_context = session.get("deal_context") or {}
    system = build_deal_system_prompt(session, deal_context, negotiation_tag)
    user_prompt = build_deal_round_prompt(
        session, user_message, negotiation_tag, answer_quality, action
    )

    messages = [{"role": "system", "content": system}]
    # Token control: only the last 6 deal turns go to the model (full history kept for scoring).
    for entry in session.get("deal_history", [])[-6:]:
        role = "assistant" if entry.get("role") == "judge" else "user"
        messages.append({"role": role, "content": entry.get("message", "")})
    messages.append({"role": "user", "content": user_prompt})

    model_mode = session.get("model_mode", "premium_nvidia")
    result = model_router.generate_deal_round_response(messages, model_mode=model_mode)
    if result.get("ok") and result.get("content"):
        return str(result["content"]).strip()[:600]

    fallbacks = {
        "press_harder": "That answer does not give me enough proof to move on terms. Be specific.",
        "escalate_stakes": "I still see too much risk here. What number or commitment changes that?",
        "partial_concession": "I can move slightly, but I need a concrete tradeoff from you.",
        "move_to_close": "If we agree in principle, what is the exact next step and timeline?",
        "acknowledge_and_counter": "I hear you, but my terms still need to reflect the risk I see.",
    }
    logger.warning("deal_flow: Nemotron deal round failed — %s", result.get("error"))
    return fallbacks.get(action, fallbacks["acknowledge_and_counter"])


def next_deal_round(
    session: dict,
    user_message: str,
    input_mode: str = "text",
    voice_turn_id: str = "",
) -> dict[str, Any]:
    """Process one deal negotiation round."""
    if not session.get("deal_phase_active"):
        return {"error": "Deal phase is not active. Start deal phase from the judge verdict."}

    message = (user_message or "").strip()
    if not message:
        return {"error": "Deal counter cannot be empty."}

    if _count_founder_replies(session) >= HARD_MAX_FOUNDER_REPLIES:
        return {"error": "Maximum deal rounds reached. End the deal to see your scorecard."}

    current_round = int(session.get("deal_round", 1))

    deal_context = session.get("deal_context") or {}
    last_tag = "Anchoring"
    if session.get("deal_history"):
        for h in reversed(session["deal_history"]):
            if h.get("negotiation_tag"):
                last_tag = h["negotiation_tag"]
                break

    answer_quality = classify_deal_answer_quality(message, deal_context, last_tag)
    signals = extract_deal_signals(
        session.get("deal_history", []) + [{"role": "user", "message": message}],
        deal_context,
    )

    session.setdefault("deal_history", []).append({
        "round": current_round,
        "role": "user",
        "message": message,
        "negotiation_tag": last_tag,
        "answer_quality": answer_quality,
        "action": "",
        "input_mode": input_mode or "text",
        "voice_turn_id": voice_turn_id or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    next_round = current_round + 1
    negotiation_tag = choose_next_negotiation_tag(session)
    action = choose_deal_action(answer_quality, negotiation_tag, session)
    if action not in _VALID_ACTIONS:
        action = "acknowledge_and_counter"

    ai_message = _generate_deal_ai_message(
        session, message, negotiation_tag, answer_quality, action
    )

    session["deal_round"] = next_round
    session["deal_history"].append({
        "round": next_round,
        "role": "judge",
        "message": ai_message,
        "negotiation_tag": negotiation_tag,
        "answer_quality": "",
        "action": action,
        "input_mode": "",
        "voice_turn_id": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    readiness = evaluate_deal_readiness(session)
    founder_replies = readiness["rounds_completed"]
    soft_limit = readiness["recommended_action"] in ("recommend_end", "force_end")
    can_continue = founder_replies < HARD_MAX_FOUNDER_REPLIES

    return {
        "session_id": session.get("session_id", ""),
        "deal_phase_id": session.get("deal_phase_id", ""),
        "round": next_round,
        "negotiation_tag": negotiation_tag,
        "answer_quality": answer_quality,
        "action": action,
        "ai_message": ai_message,
        "deal_state": _deal_state(signals, answer_quality),
        "readiness": readiness,
        "soft_limit_reached": soft_limit,
        "can_continue": can_continue,
        "completion_message": (readiness["reason"] if soft_limit else ""),
    }
