"""Judge verdict engine after pitch scorecard (Phase 9A)."""

from __future__ import annotations

import logging
import re
from typing import Any

from core.deal_persona_builder import get_persona_display
from core.judge_settings import get_label, normalize_difficulty
from core.json_utils import parse_model_json, sanitize_for_log
from core import model_router

logger = logging.getLogger(__name__)

_INTEREST_LABELS = {
    "strong_interest": "Strong Interest",
    "mild_interest": "Mild Interest",
    "too_early": "Too Early",
    "no_interest": "No Interest",
}

_DEAL_TYPE_FROM_ASK: list[tuple[str, str]] = [
    (r"\b(?:seed|series|funding|investment|equity|valuation|lakhs?|crores?|vc|investor)\b", "equity"),
    (r"\b(?:mentorship|mentor|guidance|advisor|architecture|introduc)\b", "mentorship"),
    (r"\b(?:pilot|paid pilot|contract|deployment|client|procurement|enterprise)\b", "pilot"),
    (r"\b(?:sponsor|sponsorship|partnership|event|fest|budget)\b", "sponsorship"),
]


def _get_battle_phase(round_number: int) -> str:
    if round_number <= 3:
        return "explore"
    if round_number <= 6:
        return "pressure"
    return "close"


def _session_maturity(session: dict) -> dict[str, Any]:
    history = session.get("history", [])
    user_turns = sum(1 for m in history if m.get("role") == "user")
    rounds_completed = max(user_turns, session.get("round", 1) - 1)
    battle_phase = _get_battle_phase(session.get("round", rounds_completed + 1))
    enough_context = (
        rounds_completed >= 4 and battle_phase in ("pressure", "close")
    ) or (rounds_completed >= 3 and battle_phase == "close")
    return {
        "rounds_completed": rounds_completed,
        "battle_phase_reached": battle_phase,
        "enough_context": enough_context,
    }


def determine_deal_type(session: dict, pitch_scorecard: dict) -> str:
    """Infer deal type from persona + ask field."""
    persona = session.get("persona", "hackathon_judge")
    difficulty = normalize_difficulty(
        session.get("difficulty_profile") or session.get("difficulty", "practice")
    )

    # Practice mode: always allow a deal drill (mentorship terms) even with hackathon persona.
    if difficulty == "practice":
        if persona == "hackathon_judge":
            return "mentorship"
        # fall through for other personas in practice

    if persona == "hackathon_judge":
        return "verdict_only"

    startup = session.get("startup", {}) or {}
    ask = " ".join([
        str(startup.get("ask", "")),
        str(startup.get("traction", "")),
        str(startup.get("problem", "")),
    ]).lower()

    for pattern, deal_type in _DEAL_TYPE_FROM_ASK:
        if re.search(pattern, ask, re.IGNORECASE):
            return deal_type

    if persona == "skeptical_vc":
        return "equity"
    if persona == "technical_judge":
        return "mentorship"
    return "none"


def determine_interest_level(session: dict, pitch_scorecard: dict) -> str:
    """Return interest_level from score + battle maturity."""
    overall = int(pitch_scorecard.get("overall", 0) or 0)
    maturity = _session_maturity(session)
    rounds = maturity["rounds_completed"]
    phase = maturity["battle_phase_reached"]
    enough = maturity["enough_context"]
    difficulty = normalize_difficulty(
        session.get("difficulty_profile") or session.get("difficulty", "practice")
    )
    is_practice = difficulty == "practice"

    persona = session.get("persona", "hackathon_judge")
    if persona == "hackathon_judge":
        return "mild_interest" if overall >= 48 else "no_interest"

    # Practice mode: slightly more room to continue into deal for demo learning.
    score_for_verdict = overall + (5 if is_practice else 0)

    if rounds < 3 and score_for_verdict < 68:
        return "too_early"
    if phase == "explore" and score_for_verdict < 62:
        return "too_early"
    if not enough and score_for_verdict < 58:
        return "too_early"

    if score_for_verdict >= 65 and rounds >= 3:
        return "strong_interest"
    if score_for_verdict >= 48 and rounds >= 3:
        return "mild_interest"
    if score_for_verdict < 40:
        return "no_interest"
    if is_practice and rounds >= 2 and overall >= 42:
        return "mild_interest"
    return "mild_interest" if enough else "too_early"


def _weakest_dimension(pitch_scorecard: dict) -> tuple[str, int]:
    scores = pitch_scorecard.get("scores") or {}
    if not scores:
        return "business_model", 30
    dim, data = min(scores.items(), key=lambda x: int(x[1].get("score", 0)))
    return dim, int(data.get("score", 0))


def _strongest_dimension(pitch_scorecard: dict) -> tuple[str, int]:
    scores = pitch_scorecard.get("scores") or {}
    if not scores:
        return "clarity", 50
    dim, data = max(scores.items(), key=lambda x: int(x[1].get("score", 0)))
    return dim, int(data.get("score", 0))


def build_local_verdict_fallback(
    session: dict,
    pitch_scorecard: dict,
    interest_level: str,
    deal_type: str,
) -> dict[str, str]:
    """Local verdict text when Nemotron is unavailable."""
    overall = int(pitch_scorecard.get("overall", 0) or 0)
    weak_dim, weak_score = _weakest_dimension(pitch_scorecard)
    strong_dim, strong_score = _strongest_dimension(pitch_scorecard)
    weak_name = weak_dim.replace("_", " ")
    startup = session.get("startup", {}) or {}
    ask = str(startup.get("ask", "")).strip() or "your stated ask"
    persona_name, _ = get_persona_display(session.get("persona", "skeptical_vc"))

    if interest_level == "strong_interest" and deal_type == "equity":
        reaction = (
            f"The traction is real enough for me to continue. I am interested, "
            f"but your valuation needs pressure-testing. I would open below {ask}."
        )
        offer = "₹30 lakhs for 15% — subject to due diligence on your pilot metrics."
        why = f"Strong overall pitch ({overall}/100) but {weak_name} ({weak_score}) still needs proof."
        next_label = "Continue to Deal Round"
    elif interest_level == "mild_interest":
        if deal_type == "mentorship":
            reaction = (
                "Good practice session. I see enough promise to walk through mentorship terms — "
                "what you would get from me and what commitment I expect from you."
            )
            offer = "Two hours per week for four weeks focused on your weakest pitch dimension."
        else:
            reaction = (
                "I am not fully convinced yet, but there is enough here to discuss terms. "
                "My offer would reflect the risk I still see in your market and proof."
            )
            offer = "Terms would be conservative until you strengthen your weakest answers."
        why = (
            f"Score {overall}/100 — strongest area {strong_dim.replace('_', ' ')} ({strong_score}), "
            f"still work needed on {weak_name} ({weak_score})."
        )
        next_label = "Start Negotiation →"
    elif interest_level == "too_early":
        reaction = (
            "You ended before I could test the harder parts of this business. "
            "I cannot make a serious deal decision yet."
        )
        offer = ""
        why = "Not enough battle rounds or maturity to negotiate terms credibly."
        next_label = "Practice More — Negotiate Later"
    elif deal_type == "verdict_only":
        reaction = (
            "You are on the right track, but this is not a deal negotiation. "
            "What separates you from top submissions is stronger proof, sharper differentiation, "
            "and a clearer demo story."
        )
        offer = ""
        why = f"Hackathon verdict at {overall}/100 — focus on {weak_name} before finals."
        next_label = "View Winning Gap Analysis"
    else:
        reaction = (
            "I am not ready to invest at this stage. The weakest part is your "
            f"{weak_name}, and I would need stronger proof before discussing terms."
        )
        offer = ""
        why = f"Overall {overall}/100 is below the bar for term discussion."
        next_label = "Retry Weakest Question"

    return {
        "judge_reaction": reaction,
        "deal_opening_offer": offer,
        "why_this_verdict": why,
        "next_step_label": next_label,
    }


def _build_verdict_nemotron_messages(
    session: dict,
    pitch_scorecard: dict,
    interest_level: str,
    deal_type: str,
    maturity: dict,
) -> list[dict[str, str]]:
    startup = session.get("startup", {}) or {}
    persona = session.get("persona", "skeptical_vc")
    persona_name, persona_role = get_persona_display(persona)
    weak_dim, weak_score = _weakest_dimension(pitch_scorecard)
    strong_dim, strong_score = _strongest_dimension(pitch_scorecard)
    difficulty = session.get("difficulty_profile") or "practice"

    system = (
        f"You are {persona_name} ({persona_role}) giving a post-pitch verdict.\n"
        "Return ONLY valid JSON. No markdown. No reasoning. No array wrapper.\n"
        "Use the persona voice. Do not hallucinate facts. Use only provided context.\n\n"
        "REQUIRED JSON:\n"
        '{"judge_reaction":"","deal_opening_offer":"","why_this_verdict":"","next_step_label":""}\n\n'
        "Rules:\n"
        "- judge_reaction: 2-3 sentences in character.\n"
        "- deal_opening_offer: opening terms if deal continues; empty string if not.\n"
        "- For verdict_only (hackathon): deal_opening_offer must be empty; "
        "next_step_label = 'View Winning Gap Analysis'.\n"
        "- For too_early/no_interest: deal_opening_offer empty.\n"
        "- next_step_label: 'Start Negotiation' if interested; "
        "'Practice More — Negotiate Later' if too_early; 'Retry Weakest Question' if no_interest."
    )

    user = (
        f"Startup: {startup.get('name', '')}\n"
        f"Ask: {startup.get('ask', '')}\n"
        f"Traction: {startup.get('traction', '')}\n"
        f"Pitch overall: {pitch_scorecard.get('overall', 0)}/100\n"
        f"Weakest dimension: {weak_dim} ({weak_score})\n"
        f"Strongest dimension: {strong_dim} ({strong_score})\n"
        f"Interest level (computed): {interest_level}\n"
        f"Deal type: {deal_type}\n"
        f"Rounds completed: {maturity.get('rounds_completed')}\n"
        f"Battle phase: {maturity.get('battle_phase_reached')}\n"
        f"Difficulty: {difficulty}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_judge_reaction_with_nemotron(
    session: dict,
    pitch_scorecard: dict,
    verdict_base: dict[str, str],
) -> dict[str, str]:
    """Enhance verdict text via Nemotron; fall back to verdict_base on failure."""
    messages = _build_verdict_nemotron_messages(
        session,
        pitch_scorecard,
        verdict_base.get("interest_level", "no_interest"),
        verdict_base.get("deal_type", "none"),
        verdict_base.get("session_maturity", {}),
    )
    model_mode = session.get("model_mode", "premium_nvidia")
    result = model_router.generate_deal_verdict_response(messages, model_mode=model_mode)
    if not result.get("ok") or not result.get("content"):
        return {
            "judge_reaction": verdict_base.get("judge_reaction", ""),
            "deal_opening_offer": verdict_base.get("deal_opening_offer", ""),
            "why_this_verdict": verdict_base.get("why_this_verdict", ""),
            "next_step_label": verdict_base.get("next_step_label", ""),
        }

    raw = result["content"]
    parsed, _ = parse_model_json(raw)
    if not isinstance(parsed, dict) or not parsed:
        repair = model_router.generate_deal_verdict_repair_response(raw, model_mode=model_mode)
        if repair.get("ok") and repair.get("content"):
            parsed, _ = parse_model_json(repair["content"])

    if isinstance(parsed, dict) and parsed.get("judge_reaction"):
        return {
            "judge_reaction": str(parsed.get("judge_reaction", ""))[:500],
            "deal_opening_offer": str(parsed.get("deal_opening_offer", ""))[:300],
            "why_this_verdict": str(parsed.get("why_this_verdict", ""))[:400],
            "next_step_label": str(parsed.get("next_step_label", verdict_base.get("next_step_label", "")))[:80],
        }

    logger.warning("deal_verdict: Nemotron parse failed preview=%r", sanitize_for_log(raw))
    return {
        "judge_reaction": verdict_base.get("judge_reaction", ""),
        "deal_opening_offer": verdict_base.get("deal_opening_offer", ""),
        "why_this_verdict": verdict_base.get("why_this_verdict", ""),
        "next_step_label": verdict_base.get("next_step_label", ""),
    }


def build_judge_verdict(
    session: dict,
    pitch_scorecard: dict,
    local_only: bool = False,
) -> dict[str, Any]:
    """Build full judge_verdict object after pitch scorecard."""
    from core.scoring_engine import _sync_overall_to_dimensions

    pitch_scorecard = _sync_overall_to_dimensions(dict(pitch_scorecard))
    session["latest_scorecard"] = pitch_scorecard

    persona = session.get("persona", "hackathon_judge")
    persona_name, persona_role = get_persona_display(persona)
    maturity = _session_maturity(session)
    deal_type = determine_deal_type(session, pitch_scorecard)
    interest_level = determine_interest_level(session, pitch_scorecard)

    startup = session.get("startup", {}) or {}
    ask_detected = str(startup.get("ask", "")).strip()

    difficulty_profile = session.get("difficulty_profile") or normalize_difficulty(
        session.get("difficulty", "practice")
    )

    can_continue = (
        interest_level in ("strong_interest", "mild_interest")
        and deal_type not in ("verdict_only", "none")
    )
    if deal_type == "verdict_only":
        can_continue = False
    if interest_level in ("too_early", "no_interest"):
        can_continue = False
    # Practice mode: mild/strong interest always unlocks deal practice.
    if difficulty_profile == "practice" and interest_level in ("strong_interest", "mild_interest"):
        can_continue = True
        if deal_type in ("verdict_only", "none"):
            deal_type = "mentorship"

    local = build_local_verdict_fallback(session, pitch_scorecard, interest_level, deal_type)
    verdict_base = {
        **local,
        "interest_level": interest_level,
        "deal_type": deal_type,
        "session_maturity": maturity,
    }

    use_local = local_only or bool(pitch_scorecard.get("retry_applied"))
    if use_local:
        nemotron_text = {
            "judge_reaction": local["judge_reaction"],
            "deal_opening_offer": local["deal_opening_offer"],
            "why_this_verdict": local["why_this_verdict"],
            "next_step_label": local["next_step_label"],
        }
    else:
        nemotron_text = generate_judge_reaction_with_nemotron(session, pitch_scorecard, verdict_base)

    return {
        "interest_level": interest_level,
        "interest_label": _INTEREST_LABELS.get(interest_level, interest_level),
        "deal_type": deal_type,
        "can_continue_to_deal": can_continue,
        "judge_reaction": nemotron_text.get("judge_reaction", local["judge_reaction"]),
        "deal_opening_offer": nemotron_text.get("deal_opening_offer", local["deal_opening_offer"]),
        "why_this_verdict": nemotron_text.get("why_this_verdict", local["why_this_verdict"]),
        "next_step_label": nemotron_text.get("next_step_label", local["next_step_label"]),
        "persona_name": persona_name,
        "persona_type": persona_role,
        "ask_detected": ask_detected,
        "session_maturity": maturity,
        "difficulty_profile": difficulty_profile,
        "difficulty_label": get_label(difficulty_profile),
    }
