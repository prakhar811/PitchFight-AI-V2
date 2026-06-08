"""Scoring engine for PitchFight AI — Phase 5D: Hybrid Claim-Based Scorecard.

Architecture (permanent):
  - Local deterministic logic scores all 6 dimensions using extracted signals.
  - Nemotron generates ONLY: improved_answer, improved_pitch, top_3_questions.
  - No giant fragile Nemotron full-scorecard JSON in the main path.

scorecard_source values:
  "hybrid_claims_nemotron" — local scores + Nemotron coaching succeeded
  "hybrid_claims_local"    — local scores + local coaching fallback (still useful)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from core import model_router
from core.json_utils import safe_json_parse, _score_label
from core.claim_extractor import extract_concrete_signals

logger = logging.getLogger(__name__)

MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "6"))

_REQUIRED_DIMS = (
    "clarity",
    "problem_understanding",
    "market_awareness",
    "differentiation",
    "business_model",
    "objection_handling",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, v))


def _dimension(score: int, reason: str, quote: str, signals: list[str] | None = None) -> dict:
    return {
        "score": score,
        "label": _score_label(score),
        "reason": reason,
        "quote": quote,
        "signals_used": signals or [],
    }


def _empty_signals() -> dict:
    return {
        "numbers": [], "percentages": [], "pricing": [], "user_counts": [],
        "validation": [], "college_mentions": [], "competitors": [],
        "technical_mechanisms": [], "revenue_signals": [], "retention_signals": [],
        "gtm_signals": [], "non_answers": [], "vague_claims": [],
        "best_user_quotes": [], "all_user_answers": [], "signal_count": 0,
    }


def _first(lst: list, default: str = "") -> str:
    return lst[0] if lst else default


# ---------------------------------------------------------------------------
# Local dimension scoring functions
# ---------------------------------------------------------------------------

def _score_clarity(signals: dict, engagement: int, total: int) -> tuple[int, str, str, list]:
    """Did the founder communicate what the product does and who it helps?"""
    has_tech = bool(signals.get("technical_mechanisms"))
    has_numbers = bool(signals.get("numbers") or signals.get("user_counts"))
    has_validation = bool(signals.get("validation"))
    has_vague_only = bool(signals.get("vague_claims")) and not has_tech and not has_numbers
    best_quotes = signals.get("best_user_quotes", [])
    quote = best_quotes[0][:160] if best_quotes else ""
    used: list[str] = []

    if engagement == 0:
        return 15, "No substantive answers — product explanation absent.", quote, []

    # Floor: any on-topic answer = at least 33
    score = 33
    parts: list[str] = []

    if has_tech and (has_numbers or has_validation):
        score = max(score, 65)
        techs = signals.get("technical_mechanisms", [])[:2]
        used += techs
        parts.append(f"Technical mechanism described ({', '.join(techs)}) with supporting evidence.")
    elif has_tech:
        score = max(score, 58)
        techs = signals.get("technical_mechanisms", [])[:2]
        used += techs
        parts.append(f"Technical mechanism explained: {', '.join(techs)}.")
    elif has_validation:
        score = max(score, 55)
        vals = signals.get("validation", [])[:2]
        used += vals
        parts.append(f"Validation evidence present ({', '.join(vals)}) — product is real.")
    elif has_numbers:
        score = max(score, 52)
        nums = signals.get("numbers", [])[:2]
        used += nums
        parts.append(f"Concrete numbers ({', '.join(nums)}) suggest product has been built/used.")
    elif has_vague_only:
        score = _clamp(score, 33, 40)
        parts.append("Answer was on-topic but used vague language without concrete specifics.")
    else:
        parts.append("Product described with some substance but limited concrete evidence.")

    reason = " ".join(parts)[:280]
    return _clamp(score), reason, quote, list(dict.fromkeys(used))[:5]


def _score_problem_understanding(signals: dict, engagement: int, total: int) -> tuple[int, str, str, list]:
    """Did they name a specific user, pain, and provide evidence of understanding?"""
    has_validation = bool(signals.get("validation"))
    has_colleges = bool(signals.get("college_mentions"))
    has_user_counts = bool(signals.get("user_counts") or signals.get("numbers"))
    val_list = signals.get("validation", [])
    col_list = signals.get("college_mentions", [])
    num_list = (signals.get("user_counts", []) + signals.get("numbers", []))[:2]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (val_list[0] if val_list else (col_list[0] if col_list else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (val_list[:2] + col_list[:2])[:5]

    if engagement == 0:
        return 15, "No evidence of problem understanding — no substantive answers.", quote[:160], []

    score = 33
    parts: list[str] = []

    if has_validation and has_colleges:
        score = max(score, 72)
        parts.append(
            f"Validated with real users ({', '.join(val_list[:2])}) "
            f"at named campuses ({', '.join(col_list[:2])})."
        )
    elif has_validation:
        score = max(score, 62)
        parts.append(f"Validation evidence: {', '.join(val_list[:2])}.")
    elif has_colleges:
        score = max(score, 52)
        parts.append(f"Campus/college context mentioned: {', '.join(col_list[:2])}.")
    elif has_user_counts:
        score = max(score, 50)
        parts.append(f"User/number evidence present: {', '.join(num_list)}.")
    else:
        parts.append("Problem described but without user research or validation evidence.")

    return _clamp(score), " ".join(parts)[:280], quote[:160] if isinstance(quote, str) else "", used


def _score_market_awareness(signals: dict, engagement: int, total: int) -> tuple[int, str, str, list]:
    """Did they demonstrate knowledge of market size, segment, or competitive landscape?"""
    has_numbers = bool(signals.get("numbers") or signals.get("user_counts"))
    has_competitors = bool(signals.get("competitors"))
    has_colleges = bool(signals.get("college_mentions"))
    nums = (signals.get("user_counts", []) + signals.get("numbers", []))[:3]
    comps = signals.get("competitors", [])[:3]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (nums[0] if nums else (comps[0] if comps else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (nums[:2] + comps[:2])[:5]

    if engagement == 0:
        return 15, "No market awareness demonstrated — no substantive answers.", str(quote)[:160], []

    score = 33
    parts: list[str] = []

    if has_numbers and has_competitors:
        score = max(score, 67)
        parts.append(
            f"Market numbers ({', '.join(nums[:2])}) and competitors named ({', '.join(comps[:2])})."
        )
    elif has_numbers and has_colleges:
        score = max(score, 60)
        parts.append(
            f"User/market numbers ({', '.join(nums[:2])}) with campus context."
        )
    elif has_numbers:
        score = max(score, 55)
        parts.append(f"Market/user numbers: {', '.join(nums[:2])}.")
    elif has_competitors:
        score = max(score, 48)
        parts.append(
            f"Competitors identified ({', '.join(comps[:2])}) — indicates market awareness."
        )
    else:
        parts.append("Market described but without user counts, TAM, or competitor landscape.")

    return _clamp(score), " ".join(parts)[:280], str(quote)[:160], used


def _score_differentiation(signals: dict, engagement: int, total: int) -> tuple[int, str, str, list]:
    """Did they explain why this beats alternatives (competitor + mechanism/moat)?"""
    has_competitors = bool(signals.get("competitors"))
    has_tech = bool(signals.get("technical_mechanisms"))
    comps = signals.get("competitors", [])[:3]
    techs = signals.get("technical_mechanisms", [])[:3]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (comps[0] if comps else (techs[0] if techs else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (comps[:2] + techs[:2])[:5]

    if engagement == 0:
        return 15, "No differentiation demonstrated — no substantive answers.", str(quote)[:160], []

    score = 33
    parts: list[str] = []

    if has_competitors and has_tech:
        score = max(score, 70)
        parts.append(
            f"Named competitors ({', '.join(comps[:2])}) with technical moat ({', '.join(techs[:2])})."
        )
    elif has_competitors:
        score = max(score, 52)
        parts.append(
            f"Competitors identified ({', '.join(comps[:2])}) but moat/mechanism not fully articulated."
        )
    elif has_tech:
        score = max(score, 50)
        parts.append(
            f"Technical approach described ({', '.join(techs[:2])}) but no direct competitor comparison."
        )
    else:
        parts.append(
            "Differentiation not clearly supported — no competitors named and no technical mechanism stated."
        )

    return _clamp(score), " ".join(parts)[:280], str(quote)[:160], used


def _score_business_model(signals: dict, engagement: int, total: int) -> tuple[int, str, str, list]:
    """Did they explain who pays, how much, and why?"""
    has_pricing = bool(signals.get("pricing"))
    has_revenue = bool(signals.get("revenue_signals"))
    has_validation = bool(signals.get("validation"))
    pricing = signals.get("pricing", [])[:3]
    revenue = signals.get("revenue_signals", [])[:3]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (pricing[0] if pricing else (revenue[0] if revenue else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (pricing[:2] + revenue[:2])[:5]

    if engagement == 0:
        return 12, "No business model addressed — all non-answers.", str(quote)[:160], []

    # Business model floor is lower — it's OK for early-stage students to not have revenue
    score = 28
    parts: list[str] = []

    if has_pricing and has_revenue:
        score = max(score, 68)
        parts.append(f"Pricing ({', '.join(pricing[:2])}) and revenue logic ({', '.join(revenue[:2])}) present.")
    elif has_pricing:
        score = max(score, 52)
        parts.append(f"Pricing mentioned: {', '.join(pricing[:2])}.")
    elif has_revenue:
        score = max(score, 48)
        parts.append(f"Revenue/monetization signals: {', '.join(revenue[:2])}.")
    elif has_validation:
        # Traction is a proxy for business activity, even if no explicit model yet
        score = max(score, 36)
        parts.append(
            "Traction/validation evidence present but no explicit pricing or revenue model stated."
        )
    else:
        parts.append("Business model not clearly stated — no pricing, revenue, or monetization mentioned.")

    return _clamp(score), " ".join(parts)[:280], str(quote)[:160], used


def _score_objection_handling(signals: dict, engagement: int, total: int) -> tuple[int, str, str, list]:
    """Did they answer hard questions directly with evidence?"""
    has_validation = bool(signals.get("validation"))
    has_numbers = bool(signals.get("numbers") or signals.get("user_counts"))
    has_tech = bool(signals.get("technical_mechanisms"))
    best_quotes = signals.get("best_user_quotes", [])
    quote = best_quotes[0][:160] if best_quotes else ""
    used: list[str] = (signals.get("validation", [])[:2] + signals.get("numbers", [])[:2])[:4]

    if total == 0 or engagement == 0:
        return 15, "No substantive answers to objections recorded.", quote, []

    engagement_rate = engagement / total
    # Base score: engagement_rate * 60
    score = int(engagement_rate * 60)
    parts: list[str] = []

    if has_validation:
        score += 10
        vals = signals.get("validation", [])[:2]
        parts.append(f"Evidence-backed answers: {', '.join(vals)}.")
    if has_numbers:
        score += 7
        parts.append("Concrete numbers used to support claims.")
    if has_tech:
        score += 5

    # Floor: at least 30 if majority were substantive
    if engagement_rate > 0.5:
        score = max(score, 30)

    if not parts:
        parts.append(
            f"{engagement}/{total} answers were substantive. Limited evidence-backed responses to objections."
        )
    else:
        parts.insert(0, f"{engagement}/{total} answers substantive.")

    return _clamp(score, 0, 82), " ".join(parts)[:280], quote, used


# ---------------------------------------------------------------------------
# Local scoring orchestrator
# ---------------------------------------------------------------------------

def _why_weak_reason(weak_answer: str, signals: dict) -> str:
    stripped = weak_answer.strip().lower()
    if not stripped or stripped in ("no answers recorded.", "no answers recorded yet."):
        return "No answers were recorded in this session."
    if len(stripped.split()) < 4:
        return "This answer was too brief to evaluate — no supporting evidence given."
    if signals.get("vague_claims") and not signals.get("numbers") and not signals.get("validation"):
        return "This answer used vague language without concrete evidence or specifics."
    return "This answer lacked the concrete numbers, validation, or mechanisms present in stronger answers."


def _compute_local_scores(
    signals: dict, startup: dict
) -> tuple[dict[str, Any], str, str, str]:
    """Return (scores_dict, best_answer, weakest_answer, why_weak).

    All 6 dimension scores are computed deterministically from extracted signals.
    No API calls.
    """
    all_answers = signals.get("all_user_answers", [])
    non_answers = signals.get("non_answers", [])
    best_quotes = signals.get("best_user_quotes", [])
    total = len(all_answers)
    engagement = total - len(non_answers)  # number of substantive answers

    scores = {
        "clarity": _dimension(
            *_score_clarity(signals, engagement, total)
        ),
        "problem_understanding": _dimension(
            *_score_problem_understanding(signals, engagement, total)
        ),
        "market_awareness": _dimension(
            *_score_market_awareness(signals, engagement, total)
        ),
        "differentiation": _dimension(
            *_score_differentiation(signals, engagement, total)
        ),
        "business_model": _dimension(
            *_score_business_model(signals, engagement, total)
        ),
        "objection_handling": _dimension(
            *_score_objection_handling(signals, engagement, total)
        ),
    }

    best_answer = (
        best_quotes[0]
        if best_quotes
        else (all_answers[0] if all_answers else "No answers recorded.")
    )
    non_best = [a for a in all_answers if a != best_answer]
    if non_answers:
        weakest_answer = non_answers[0]
    elif non_best:
        weakest_answer = min(non_best, key=len)
    else:
        weakest_answer = all_answers[-1] if len(all_answers) > 1 else best_answer

    why_weak = _why_weak_reason(weakest_answer, signals)
    return scores, best_answer, weakest_answer, why_weak


# ---------------------------------------------------------------------------
# Coaching prompt builder (Nemotron generates only 3 coaching fields)
# ---------------------------------------------------------------------------

def _build_coaching_prompt(
    session: dict,
    signals: dict,
    scores: dict[str, Any],
    best_answer: str,
    weakest_answer: str,
    why_weak: str,
) -> list[dict[str, str]]:
    """Build messages for Nemotron coaching-only call.

    Nemotron generates only: improved_answer, improved_pitch, top_3_questions.
    All scoring is already done locally and passed as context.
    """
    startup = session.get("startup", {})

    startup_block = "\n".join([
        f"Startup: {startup.get('name', 'Unknown')}",
        f"Problem: {startup.get('problem', 'Not stated')}",
        f"Solution: {startup.get('solution', 'Not stated')}",
        f"Why AI: {startup.get('why_ai', 'Not stated')}",
        f"Stage: {startup.get('stage', 'Not stated')}",
        f"Traction: {startup.get('traction', 'Not stated')}",
        f"Target users: {startup.get('target_users', 'Not stated')}",
    ])

    # Scores block + weak dimensions (explicit requirement)
    scores_lines = ["DIMENSION SCORES (local — do not re-score):"]
    weak_dims: list[tuple[str, int, str]] = []
    for dim in _REQUIRED_DIMS:
        d = scores.get(dim, {})
        s = d.get("score", 0)
        lbl = d.get("label", "")
        reason_snippet = d.get("reason", "")[:80]
        scores_lines.append(f"  {dim}: {s} ({lbl})")
        if s < 55:
            weak_dims.append((dim, s, lbl, reason_snippet))

    scores_block = "\n".join(scores_lines)

    if weak_dims:
        weak_lines = ["\nWEAK DIMENSIONS (score < 55) — focus improved_answer and top_3_questions here:"]
        for dim, s, lbl, reason_snippet in weak_dims:
            weak_lines.append(f"  {dim}: {s} ({lbl}) — {reason_snippet}")
        weak_block = "\n".join(weak_lines)
    else:
        weak_block = "\nAll dimensions Solid or above — focus coaching on deepening evidence."

    # Signals block
    sig_lines = ["CONCRETE SIGNALS EXTRACTED FROM ANSWERS:"]
    for key, label in [
        ("numbers", "Numbers/metrics"),
        ("validation", "Validation evidence"),
        ("competitors", "Competitors"),
        ("pricing", "Pricing/currency"),
        ("technical_mechanisms", "Technical mechanisms"),
        ("college_mentions", "Colleges/campuses"),
    ]:
        items = signals.get(key, [])[:4]
        if items:
            sig_lines.append(f"  {label}: {', '.join(str(x) for x in items)}")
    signals_block = "\n".join(sig_lines)

    # Actual answers block
    all_answers = signals.get("all_user_answers", [])
    answers_lines = ["ACTUAL FOUNDER ANSWERS (use these — do not hallucinate):"]
    for i, a in enumerate(all_answers[:5], 1):
        answers_lines.append(f"  {i}. {a[:200]}")
    answers_block = "\n".join(answers_lines)

    system_content = (
        "Return ONLY valid JSON. First character must be {. Last character must be }.\n"
        "No markdown. No explanation. No analysis. No reasoning. No chain-of-thought.\n\n"
        "You are a startup pitch coach for a student founder. "
        "Generate coaching content based on the provided context.\n\n"
        "RULES:\n"
        "  - Do NOT hallucinate traction, numbers, or facts not in the provided context.\n"
        "  - Do NOT re-score — scores are already computed.\n"
        "  - Use actual startup context and actual founder answers.\n"
        "  - If concrete signals exist, reference them in improved_answer and improved_pitch.\n"
        "  - improved_answer: rewrite of the weakest answer using specifics the founder already knows.\n"
        "  - improved_pitch: one concise 60-second pitch using startup name, problem, solution, evidence.\n"
        "  - top_3_questions: 3 pointed follow-up questions an investor would ask, focused on weak dimensions.\n\n"
        "Return exactly this JSON schema — nothing else:\n"
        '{"improved_answer": "string", "improved_pitch": "string", "top_3_questions": ["string", "string", "string"]}'
    )

    user_content = (
        f"STARTUP CONTEXT:\n{startup_block}\n\n"
        f"{scores_block}\n"
        f"{weak_block}\n\n"
        f"{signals_block}\n\n"
        f"BEST ANSWER (strongest): {best_answer[:300]}\n\n"
        f"WEAKEST ANSWER: {weakest_answer[:200]}\n"
        f"WHY WEAK: {why_weak}\n\n"
        f"{answers_block}\n\n"
        "Generate improved_answer, improved_pitch, and top_3_questions. Return JSON only."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_coaching_json(raw: str) -> dict[str, Any] | None:
    """Parse and validate the coaching JSON response."""
    parsed = safe_json_parse(raw)
    if not parsed or not isinstance(parsed, dict):
        return None

    improved_answer = str(parsed.get("improved_answer", "")).strip()
    improved_pitch = str(parsed.get("improved_pitch", "")).strip()
    raw_q = parsed.get("top_3_questions", [])

    if isinstance(raw_q, list):
        questions = [str(q).strip() for q in raw_q if str(q).strip()][:3]
    else:
        questions = []

    while len(questions) < 3:
        questions.append("What concrete evidence can you give to support your strongest claim?")

    # Both coaching fields must be non-empty for the parse to be considered valid
    if not improved_answer or not improved_pitch:
        return None

    return {
        "improved_answer": improved_answer,
        "improved_pitch": improved_pitch,
        "top_3_questions": questions,
    }


# ---------------------------------------------------------------------------
# Local coaching fallback helpers
# ---------------------------------------------------------------------------

def _local_improved_answer(weak: str, startup: dict, signals: dict) -> str:
    name = startup.get("name", "our product")
    parts: list[str] = [f"A stronger version would anchor in specifics. {name} "]
    numbers = signals.get("numbers", []) + signals.get("user_counts", [])
    validation = signals.get("validation", [])
    competitors = signals.get("competitors", [])
    if numbers:
        parts.append(f"has demonstrated by {', '.join(numbers[:3])} ")
    if validation:
        parts.append(f"validated through {', '.join(validation[:2])} ")
    if competitors:
        parts.append(f"and is differentiated from {', '.join(competitors[:2])} ")
    parts.append(f'(Original answer was: "{weak[:100]}")')
    return "".join(parts)


def _local_improved_pitch(startup: dict, signals: dict) -> str:
    name = startup.get("name", "Our startup")
    problem = startup.get("problem", "a student pain point")
    solution = startup.get("solution", "a focused product")
    evidence = (
        signals.get("user_counts", []) +
        signals.get("validation", []) +
        signals.get("numbers", [])
    )[:3]
    pitch = f"{name} solves {problem}. Our solution: {solution}."
    if evidence:
        pitch += f" Evidence so far: {', '.join(evidence)}."
    pricing = signals.get("pricing", [])
    if pricing:
        pitch += f" Business model: {pricing[0]}."
    return pitch


def _fallback_questions(weakest_dims: list[tuple], startup: dict) -> list[str]:
    _q = {
        "clarity":               "In one sentence, what does your product do and who does it help?",
        "problem_understanding": "What is the most painful part of this problem for your user, and how do you know?",
        "market_awareness":      "How many potential users exist in year one, and how did you arrive at that number?",
        "differentiation":       "What would a student miss if they used a competitor instead of you?",
        "business_model":        "Who pays, how much, and what triggers the first payment?",
        "objection_handling":    "What is the strongest argument that this startup will not work, and how do you respond?",
    }
    out = [
        _q.get(dim, f"What evidence do you have for your {dim.replace('_', ' ')}?")
        for dim, _ in weakest_dims[:3]
    ]
    while len(out) < 3:
        out.append("What concrete evidence can you give to back your strongest claim?")
    return out[:3]


def _local_coaching(
    weakest: str,
    startup: dict,
    signals: dict,
    scores: dict[str, Any],
) -> dict[str, Any]:
    """Generate local coaching content when Nemotron coaching fails."""
    dim_sorted = sorted(scores.items(), key=lambda x: x[1]["score"])
    return {
        "improved_answer": _local_improved_answer(weakest, startup, signals),
        "improved_pitch": _local_improved_pitch(startup, signals),
        "top_3_questions": _fallback_questions(dim_sorted, startup),
    }


# ---------------------------------------------------------------------------
# Main hybrid scorecard generator (Phase 5D — permanent architecture)
# ---------------------------------------------------------------------------

def generate_claim_based_scorecard(
    session: dict, model_mode: str | None = None
) -> dict[str, Any]:
    """Hybrid claim-based scorecard.

    Local scoring → deterministic, signal-based, always fair to student founders.
    Nemotron coaching → generates improved_answer, improved_pitch, top_3_questions only.

    Returns a frontend-safe dict with all required fields on every path.
    """
    resolved_mode = model_mode or session.get("model_mode") or os.getenv(
        "DEFAULT_MODEL_MODE", "premium_nvidia"
    )
    startup = session.get("startup", {})

    # Step 1: Extract signals (local, no API)
    try:
        signals = extract_concrete_signals(session)
    except Exception as exc:
        logger.warning("scoring_engine: signal extraction failed: %s", exc)
        signals = _empty_signals()

    # Step 2: Compute all 6 dimension scores + best/weakest answers locally
    try:
        scores, best_answer, weakest_answer, why_weak = _compute_local_scores(signals, startup)
    except Exception as exc:
        logger.warning("scoring_engine: local scoring failed: %s", exc)
        return build_session_aware_fallback_scorecard(
            session, signals, f"Local scoring error: {type(exc).__name__}"
        )

    # Step 3: Compute overall and concrete_signals_summary locally
    overall = round(sum(d["score"] for d in scores.values()) / len(scores))
    concrete_signals_summary = {
        "numbers":              signals.get("numbers", [])[:6],
        "validation":           signals.get("validation", [])[:6],
        "competitors":          signals.get("competitors", [])[:6],
        "revenue_signals":      signals.get("revenue_signals", [])[:6],
        "technical_mechanisms": signals.get("technical_mechanisms", [])[:6],
    }

    # Step 4: Call Nemotron for coaching only
    coaching: dict[str, Any] | None = None
    coaching_error: str = ""
    coaching_raw: str = ""

    try:
        coaching_messages = _build_coaching_prompt(
            session, signals, scores, best_answer, weakest_answer, why_weak
        )
        coaching_result = model_router.generate_coaching_response(
            coaching_messages, model_mode=resolved_mode
        )
        if coaching_result.get("ok") and coaching_result.get("content"):
            coaching_raw = coaching_result["content"]
            coaching = _parse_coaching_json(coaching_raw)
            if coaching:
                logger.info("scoring_engine: Nemotron coaching JSON parsed OK")
            else:
                logger.warning("scoring_engine: primary coaching parse failed, raw[:200]=%r", coaching_raw[:200])
        else:
            coaching_error = coaching_result.get("error") or "Coaching model returned empty response"
            logger.warning("scoring_engine: coaching call not ok — %s", coaching_error)
    except Exception as exc:
        coaching_error = f"Coaching error: {type(exc).__name__}"
        logger.warning("scoring_engine: coaching call raised — %s", exc)

    # Step 5: Repair retry if JSON parse failed (content was returned but not valid JSON)
    if coaching is None and coaching_raw:
        logger.info("scoring_engine: attempting coaching JSON repair")
        try:
            repair_result = model_router.generate_coaching_repair_response(
                coaching_raw, model_mode=resolved_mode
            )
            if repair_result.get("ok") and repair_result.get("content"):
                coaching = _parse_coaching_json(repair_result["content"])
                if coaching:
                    logger.info("scoring_engine: repaired coaching JSON OK")
                else:
                    logger.warning("scoring_engine: repair coaching parse also failed")
        except Exception as exc:
            logger.warning("scoring_engine: coaching repair raised — %s", exc)

    # Step 6: Local coaching fallback if Nemotron failed
    if coaching is None:
        logger.warning(
            "scoring_engine: using local coaching fallback. error=%r", coaching_error
        )
        coaching = _local_coaching(weakest_answer, startup, signals, scores)
        source = "hybrid_claims_local"
        model_ok = False
        provider = "local"
    else:
        source = "hybrid_claims_nemotron"
        model_ok = True
        provider = "local+nvidia"

    # Step 7: Assemble and return complete scorecard
    result: dict[str, Any] = {
        "overall": overall,
        "overall_label": _score_label(overall),
        "scores": scores,
        "best_answer": best_answer,
        "weakest_answer": weakest_answer,
        "why_weak": why_weak,
        "improved_answer": coaching["improved_answer"],
        "improved_pitch": coaching["improved_pitch"],
        "top_3_questions": coaching["top_3_questions"],
        "concrete_signals_summary": concrete_signals_summary,
        "model_ok": model_ok,
        "provider": provider,
        "model_mode": resolved_mode,
        "scorecard_source": source,
    }
    if coaching_error and not model_ok:
        result["model_error"] = coaching_error

    logger.info(
        "scoring_engine: hybrid scorecard complete — overall=%d source=%s signals=%d",
        overall, source, signals.get("signal_count", 0),
    )
    return result


# ---------------------------------------------------------------------------
# Session-aware fallback (used by api_handlers exception handler + local crash)
# ---------------------------------------------------------------------------

def build_session_aware_fallback_scorecard(
    session: dict, signals: dict, error: str = ""
) -> dict[str, Any]:
    """Session-aware fallback when even local scoring crashes.

    Uses actual user answers and extracted signals — never shows static EventRadar content.
    """
    startup = session.get("startup", {})
    all_answers = signals.get("all_user_answers", [])
    best_quotes = signals.get("best_user_quotes", [])
    non_answers = signals.get("non_answers", [])

    best_answer = best_quotes[0] if best_quotes else (all_answers[0] if all_answers else "No answers recorded.")
    non_best = [a for a in all_answers if a != best_answer]
    if non_answers:
        weakest_answer = non_answers[0]
    elif non_best:
        weakest_answer = min(non_best, key=len)
    else:
        weakest_answer = all_answers[-1] if all_answers else "No answers recorded."

    has_numbers    = bool(signals.get("numbers") or signals.get("user_counts"))
    has_validation = bool(signals.get("validation"))
    has_competitors= bool(signals.get("competitors"))
    has_tech       = bool(signals.get("technical_mechanisms"))
    has_revenue    = bool(signals.get("revenue_signals") or signals.get("pricing"))
    has_colleges   = bool(signals.get("college_mentions"))
    total          = len(all_answers)
    non_ans_count  = len(non_answers)
    engagement     = 1.0 - (non_ans_count / max(total, 1))

    def _c(v: int) -> int:
        return max(0, min(100, v))

    clarity_score = _c(65 if (has_numbers and total > 1) else 52 if total > 2 else 35)
    problem_score = _c(
        72 if (has_validation and has_colleges) else
        63 if has_validation else
        55 if has_numbers else
        45 if engagement > 0.7 else 30
    )
    market_score = _c(
        68 if (has_numbers and has_competitors) else
        55 if (has_numbers or has_competitors) else
        38 if engagement > 0.6 else 22
    )
    diff_score = _c(
        70 if (has_competitors and has_tech) else
        55 if (has_competitors or has_tech) else
        38 if engagement > 0.6 else 25
    )
    biz_score = _c(
        65 if (has_revenue and has_numbers) else
        52 if has_revenue else
        38 if has_validation else
        30 if engagement > 0.5 else 18
    )
    obj_score = _c(int(engagement * 65) + (8 if has_validation else 0) + (5 if has_numbers else 0))

    scores = {
        "clarity": _dimension(
            clarity_score,
            f"Local estimate from {total} answer(s). Scoring engine unavailable.",
            best_answer[:160],
            signals.get("numbers", [])[:3],
        ),
        "problem_understanding": _dimension(
            problem_score,
            "Based on validation/research evidence detected in answers."
            + (" College mentions found." if has_colleges else ""),
            (signals.get("validation") or [""])[0],
            (signals.get("validation", []) + signals.get("college_mentions", []))[:3],
        ),
        "market_awareness": _dimension(
            market_score,
            "Based on numbers/metrics and competitor mentions in answers.",
            (signals.get("numbers") or signals.get("competitors") or [""])[0],
            (signals.get("numbers", []) + signals.get("competitors", []))[:3],
        ),
        "differentiation": _dimension(
            diff_score,
            "Based on competitor mentions and technical mechanism signals.",
            (signals.get("competitors") or signals.get("technical_mechanisms") or [""])[0],
            (signals.get("competitors", []) + signals.get("technical_mechanisms", []))[:3],
        ),
        "business_model": _dimension(
            biz_score,
            "Based on revenue/pricing signals detected in answers."
            + (" No explicit price found." if not has_revenue else ""),
            (signals.get("revenue_signals") or signals.get("pricing") or [""])[0],
            (signals.get("revenue_signals", []) + signals.get("pricing", []))[:3],
        ),
        "objection_handling": _dimension(
            obj_score,
            f"{int(engagement * 100)}% substantive responses. {non_ans_count} non-answer turn(s) noted.",
            best_answer[:160],
            (signals.get("validation", []) + signals.get("numbers", []))[:3],
        ),
    }

    overall = round(sum(d["score"] for d in scores.values()) / 6)
    dim_sorted = sorted(scores.items(), key=lambda x: x[1]["score"])

    return {
        "overall": overall,
        "overall_label": _score_label(overall),
        "scores": scores,
        "best_answer": best_answer,
        "weakest_answer": weakest_answer,
        "why_weak": "This answer lacked concrete evidence compared to your stronger responses.",
        "improved_answer": _local_improved_answer(weakest_answer, startup, signals),
        "improved_pitch": _local_improved_pitch(startup, signals),
        "top_3_questions": _fallback_questions(dim_sorted, startup),
        "concrete_signals_summary": {
            "numbers":              signals.get("numbers", [])[:6],
            "validation":           signals.get("validation", [])[:6],
            "competitors":          signals.get("competitors", [])[:6],
            "revenue_signals":      signals.get("revenue_signals", [])[:6],
            "technical_mechanisms": signals.get("technical_mechanisms", [])[:6],
        },
        "model_ok": False,
        "provider": "local",
        "model_mode": "session_fallback",
        "scorecard_source": "session_fallback",
        **({"model_error": error} if error else {}),
    }


# ---------------------------------------------------------------------------
# Static mock scorecard (absolute last resort — no session available)
# ---------------------------------------------------------------------------

def mock_scorecard(session: dict) -> dict:
    """Static mock. Use ONLY when session-aware fallback also cannot run."""
    startup = session.get("startup", {})
    history = session.get("history", [])
    name = startup.get("name", "your startup")
    user_messages = [m["content"] for m in history if m.get("role") == "user"]
    best_answer = user_messages[0] if user_messages else "No answers recorded yet."
    weakest_answer = user_messages[-1] if user_messages else "No answers recorded."

    scores = {
        "clarity": _dimension(64, f"Several answers stayed high-level without concrete proof.", weakest_answer[:160]),
        "problem_understanding": _dimension(
            76, f"Problem understanding was articulated for {name}.", startup.get("problem", "")[:160]
        ),
        "market_awareness": _dimension(67, "Competitors were named but differentiation was not sharp.", ""),
        "differentiation": _dimension(63, "The AI angle needs a clearer moat beyond basic filtering.", ""),
        "business_model": _dimension(61, "Revenue path and retention logic were not defended under pressure.", ""),
        "objection_handling": _dimension(72, "You stayed in the fight but dodged the hardest follow-ups.", best_answer[:160]),
    }
    return {
        "overall": 68,
        "overall_label": _score_label(68),
        "scores": scores,
        "best_answer": best_answer,
        "weakest_answer": weakest_answer,
        "why_weak": "The answer was vague and lacked concrete evidence or numbers.",
        "improved_answer": f"A stronger answer would anchor {name}'s claims in specific evidence.",
        "improved_pitch": f"{name} addresses {startup.get('problem', 'a key pain point')}.",
        "top_3_questions": [
            "Why does this need AI instead of filters and sorted lists?",
            "How will you get students to use this instead of existing alternatives?",
            "What is your wedge for the first 100 active users on one campus?",
        ],
        "concrete_signals_summary": {
            "numbers": [], "validation": [], "competitors": [],
            "revenue_signals": [], "technical_mechanisms": [],
        },
        "model_ok": False,
        "provider": "mock",
        "model_mode": "mock_fallback",
        "scorecard_source": "fallback",
    }


# ---------------------------------------------------------------------------
# Legacy full-Nemotron scorecard (kept for diagnostics — not main path)
# ---------------------------------------------------------------------------

def generate_real_scorecard(session: dict, model_mode: str | None = None) -> dict:
    """Legacy: redirects to generate_claim_based_scorecard."""
    return generate_claim_based_scorecard(session, model_mode)
