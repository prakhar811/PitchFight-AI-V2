"""Scoring engine for PitchFight AI — Phase 8: Nemotron Full Scoring as Primary.

Architecture:
  Primary path  — Nemotron reads the full battle Q&A and scores all 6 dimensions.
  Fallback path — Local claim-based scoring if Nemotron full scoring fails.
  Last resort   — Session-aware local fallback for catastrophic errors.

scorecard_source values:
  "nemotron_full"          — Nemotron judged all 6 dimensions from actual Q&A (primary)
  "hybrid_claims_nemotron" — Local regex scores + Nemotron coaching (fallback 1)
  "hybrid_claims_local"    — Local scores + local coaching (fallback 2)
  "session_fallback"       — Catastrophic crash fallback
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from core import model_router
from core.json_utils import (
    safe_json_parse,
    parse_model_json,
    parse_json_object,
    normalize_parsed_root,
    extract_partial_string_fields,
    extract_partial_string_list,
    ends_abruptly,
    sanitize_for_log,
    _score_label,
)
from core.claim_extractor import extract_concrete_signals, extract_startup_context_signals
from core.judge_settings import (
    normalize_difficulty,
    get_scoring_calibration,
    get_coaching_style,
    get_label,
)

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


_ROUND_REF_RE = re.compile(r"^(?:round\s*)?r?\s*(\d{1,2})$", re.IGNORECASE)


def _user_answers_from_session(session: dict) -> list[str]:
    """Return founder answer texts in battle order."""
    history = session.get("history", [])
    return [
        str(m.get("content", "")).strip()
        for m in history
        if m.get("role") == "user" and str(m.get("content", "")).strip()
    ]


def _parse_round_reference(text: str) -> int | None:
    """Parse round labels like R4, r2, Round 3 into a 1-based round number."""
    t = text.strip()
    if not t:
        return None
    m = re.fullmatch(r"[Rr](\d{1,2})", t)
    if m:
        return int(m.group(1))
    m = _ROUND_REF_RE.fullmatch(t)
    if m:
        return int(m.group(1))
    return None


def _is_round_reference(text: str) -> bool:
    """Return True when text is only a round label (e.g. R4), not real answer content."""
    return _parse_round_reference(text) is not None


def _resolve_answer_text(
    raw: str,
    session: dict,
    local_fallback: str,
) -> tuple[str, int | None]:
    """Map Nemotron round refs (R2, R4) to actual founder answer text."""
    text = str(raw or "").strip()
    user_answers = _user_answers_from_session(session)

    round_num = _parse_round_reference(text)
    if round_num is not None and 1 <= round_num <= len(user_answers):
        return user_answers[round_num - 1][:400], round_num

    if _is_prompt_artifact(text):
        text = ""

    if _is_round_reference(text) or (text and len(text) <= 6 and not text.endswith((".", "!", "?"))):
        if local_fallback and not _is_prompt_artifact(local_fallback):
            return local_fallback[:400], None
        if user_answers:
            return user_answers[-1][:400], len(user_answers)
        return "No battle answers were submitted.", None

    if text:
        # Try to match a quoted excerpt back to a round for UI badges
        for idx, answer in enumerate(user_answers, start=1):
            snippet = answer[:80].lower()
            if snippet and snippet in text.lower():
                return text[:400], idx
        return text[:400], None

    if local_fallback:
        return local_fallback[:400], None
    if user_answers:
        return user_answers[0][:400], 1
    return "No answer recorded.", None


def _resolve_best_weakest_answers(
    session: dict,
    best_raw: str,
    weakest_raw: str,
    local_best: str,
    local_weakest: str,
) -> tuple[str, str, int | None, int | None]:
    """Ensure best/weakest fields contain readable answer text, not round codes."""
    best_answer, best_round = _resolve_answer_text(best_raw, session, local_best)
    weakest_answer, weakest_round = _resolve_answer_text(weakest_raw, session, local_weakest)
    return best_answer, weakest_answer, best_round, weakest_round


def _sync_overall_to_dimensions(scorecard: dict[str, Any]) -> dict[str, Any]:
    """Keep overall aligned with the six dimension scores shown in the UI."""
    scores = scorecard.get("scores") or {}
    if len(scores) < 6:
        return scorecard
    avg = round(sum(int(v.get("score", 0)) for v in scores.values()) / len(scores))
    scorecard["overall"] = avg
    scorecard["overall_label"] = _score_label(avg)
    return scorecard


def _apply_practice_score_nudge(
    overall: int,
    signals: dict,
    difficulty_profile: str,
) -> int:
    """Small practice-mode nudge when the founder showed real effort."""
    if normalize_difficulty(difficulty_profile) != "practice":
        return overall
    answers = signals.get("all_user_answers") or []
    has_substance = signals.get("signal_count", 0) > 0 or any(
        len(str(a).split()) >= 4 for a in answers if str(a).strip()
    )
    if not has_substance:
        return overall
    return min(100, overall + 3)


def _apply_practice_signal_floor(
    scores: dict[str, Any],
    local_reference: dict | None,
    difficulty_profile: str,
) -> dict[str, Any]:
    """In Practice mode, never score a dimension below what real signals already justify.

    The local claim-based scorer (`_compute_local_scores`) uses student-friendly floors and
    only credits genuinely extracted signals, so it cannot be gamed by fluff. Lifting the
    Nemotron score up to that deterministic reference protects honest students who gave a
    short answer with one real proof point from a harsh prose-biased judgement.

    Practice mode only — Judge and Investor keep pure Nemotron scoring.
    """
    if normalize_difficulty(difficulty_profile) != "practice":
        return scores
    if not local_reference or not isinstance(local_reference.get("scores"), dict):
        return scores
    ref = local_reference["scores"]
    for dim, entry in scores.items():
        ref_score = ref.get(dim, {}).get("score")
        if not isinstance(ref_score, (int, float)):
            continue
        try:
            cur = int(entry.get("score", 0))
        except (TypeError, ValueError):
            cur = 0
        if ref_score > cur:
            lifted = _clamp(int(round(ref_score)), 0, 100)
            entry["score"] = lifted
            entry["label"] = _score_label(lifted)
    return scores


_PROMPT_ARTIFACTS = frozenset({
    "battle q&a", "local ref", "battle q&a:", "local ref (hints only)",
    "no answer recorded.", "no answers recorded.", "not identified.",
})


def _is_prompt_artifact(text: str) -> bool:
    """True when text is a scoring-prompt label, not a founder answer."""
    t = text.strip().lower()
    if not t:
        return True
    if t in _PROMPT_ARTIFACTS:
        return True
    if "local ref" in t and len(t) < 40:
        return True
    if t.startswith("battle q") and len(t) < 30:
        return True
    return False


def _merge_signal_dicts(battle: dict, extra: dict) -> dict:
    """Merge two signal dicts (lists concatenated, deduped where sensible)."""
    merged = dict(battle)
    for key in (
        "numbers", "percentages", "pricing", "user_counts", "validation",
        "college_mentions", "competitors", "technical_mechanisms",
        "revenue_signals", "retention_signals", "gtm_signals", "vague_claims",
        "best_user_quotes",
    ):
        a = list(merged.get(key, []) or [])
        b = list(extra.get(key, []) or [])
        seen: set[str] = set()
        out: list[str] = []
        for item in a + b:
            k = str(item).strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(str(item).strip())
        merged[key] = out
    merged["all_user_answers"] = list(merged.get("all_user_answers", []) or [])
    merged["non_answers"] = list(merged.get("non_answers", []) or [])
    merged["signal_count"] = (
        len(merged.get("numbers", [])) + len(merged.get("validation", [])) +
        len(merged.get("competitors", [])) + len(merged.get("technical_mechanisms", [])) +
        len(merged.get("pricing", [])) + len(merged.get("user_counts", [])) +
        len(merged.get("revenue_signals", []))
    )
    return merged


def _battle_engagement(signals: dict) -> dict[str, int]:
    """Summarize how much the founder actually answered during the battle."""
    all_answers = signals.get("all_user_answers", [])
    non_answers = signals.get("non_answers", [])
    user_turns = len(all_answers)
    substantive = max(0, user_turns - len(non_answers))
    return {
        "user_turns": user_turns,
        "substantive_answers": substantive,
    }


def _has_startup_context(startup: dict, startup_signals: dict) -> bool:
    """Return True if the idea was described upfront (form or voice pitch)."""
    if startup_signals.get("signal_count", 0) > 0:
        return True
    substantive_fields = 0
    for key in ("problem", "solution", "why_ai", "traction", "target_users"):
        if len(str(startup.get(key, "")).strip()) > 20:
            substantive_fields += 1
    return substantive_fields >= 2


def _apply_startup_context_cap(score: int, engagement: int, cal: dict) -> int:
    """Cap scores when battle had no substantive answers (startup-only credit)."""
    if engagement > 0:
        return score
    cap = cal.get("startup_context_max", 45)
    return min(score, cap)


def _zero_engagement_reason(total: int, has_startup: bool) -> str:
    if total == 0 and not has_startup:
        return "No battle answers were submitted."
    if total == 0 and has_startup:
        return "Scored from startup description only — no battle answers were given."
    return "No substantive battle answers were given."


# ---------------------------------------------------------------------------
# Local dimension scoring functions
# ---------------------------------------------------------------------------

def _score_clarity(signals: dict, engagement: int, total: int, cal: dict | None = None) -> tuple[int, str, str, list]:
    """Did the founder communicate what the product does and who it helps?"""
    cal = cal or {}
    floor = cal.get("attempted_answer_floor", 33)
    non_ans_max = cal.get("non_answer_max", 15)
    concrete_floor = cal.get("concrete_signal_floor", 52)

    has_tech = bool(signals.get("technical_mechanisms"))
    has_numbers = bool(signals.get("numbers") or signals.get("user_counts"))
    has_validation = bool(signals.get("validation"))
    has_vague_only = bool(signals.get("vague_claims")) and not has_tech and not has_numbers
    best_quotes = signals.get("best_user_quotes", [])
    quote = best_quotes[0][:160] if best_quotes else ""
    used: list[str] = []

    if engagement == 0 and signals.get("signal_count", 0) == 0:
        return 0, _zero_engagement_reason(total, False), quote, []

    score = floor
    parts: list[str] = []

    if has_tech and (has_numbers or has_validation):
        score = max(score, concrete_floor + 13)
        techs = signals.get("technical_mechanisms", [])[:2]
        used += techs
        parts.append(f"Technical mechanism described ({', '.join(techs)}) with supporting evidence.")
    elif has_tech:
        score = max(score, concrete_floor + 6)
        techs = signals.get("technical_mechanisms", [])[:2]
        used += techs
        parts.append(f"Technical mechanism explained: {', '.join(techs)}.")
    elif has_validation:
        score = max(score, concrete_floor + 3)
        vals = signals.get("validation", [])[:2]
        used += vals
        parts.append(f"Validation evidence present ({', '.join(vals)}) — product is real.")
    elif has_numbers:
        score = max(score, concrete_floor)
        nums = signals.get("numbers", [])[:2]
        used += nums
        parts.append(f"Concrete numbers ({', '.join(nums)}) suggest product has been built/used.")
    elif has_vague_only:
        vague_hi = cal.get("vague_on_topic_range", [floor, floor + 10])[1]
        score = _clamp(score, floor, vague_hi)
        parts.append("Answer was on-topic but used vague language without concrete specifics.")
    else:
        parts.append("Product described with some substance but limited concrete evidence.")

    reason = " ".join(parts)[:280]
    score = _apply_startup_context_cap(_clamp(score), engagement, cal)
    return score, reason, quote, list(dict.fromkeys(used))[:5]


def _score_problem_understanding(signals: dict, engagement: int, total: int, cal: dict | None = None) -> tuple[int, str, str, list]:
    """Did they name a specific user, pain, and provide evidence of understanding?"""
    cal = cal or {}
    floor = cal.get("attempted_answer_floor", 33)
    non_ans_max = cal.get("non_answer_max", 15)
    concrete_floor = cal.get("concrete_signal_floor", 52)

    has_validation = bool(signals.get("validation"))
    has_colleges = bool(signals.get("college_mentions"))
    has_user_counts = bool(signals.get("user_counts") or signals.get("numbers"))
    val_list = signals.get("validation", [])
    col_list = signals.get("college_mentions", [])
    num_list = (signals.get("user_counts", []) + signals.get("numbers", []))[:2]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (val_list[0] if val_list else (col_list[0] if col_list else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (val_list[:2] + col_list[:2])[:5]

    if engagement == 0 and signals.get("signal_count", 0) == 0:
        return 0, _zero_engagement_reason(total, False), quote[:160], []

    score = floor
    parts: list[str] = []

    if has_validation and has_colleges:
        score = max(score, concrete_floor + 20)
        parts.append(
            f"Validated with real users ({', '.join(val_list[:2])}) "
            f"at named campuses ({', '.join(col_list[:2])})."
        )
    elif has_validation:
        score = max(score, concrete_floor + 10)
        parts.append(f"Validation evidence: {', '.join(val_list[:2])}.")
    elif has_colleges:
        score = max(score, concrete_floor)
        parts.append(f"Campus/college context mentioned: {', '.join(col_list[:2])}.")
    elif has_user_counts:
        score = max(score, concrete_floor - 2)
        parts.append(f"User/number evidence present: {', '.join(num_list)}.")
    else:
        parts.append("Problem described but without user research or validation evidence.")

    score = _apply_startup_context_cap(_clamp(score), engagement, cal)
    return score, " ".join(parts)[:280], quote[:160] if isinstance(quote, str) else "", used


def _score_market_awareness(signals: dict, engagement: int, total: int, cal: dict | None = None) -> tuple[int, str, str, list]:
    """Did they demonstrate knowledge of market size, segment, or competitive landscape?"""
    cal = cal or {}
    floor = cal.get("attempted_answer_floor", 33)
    non_ans_max = cal.get("non_answer_max", 15)
    concrete_floor = cal.get("concrete_signal_floor", 52)

    has_numbers = bool(signals.get("numbers") or signals.get("user_counts"))
    has_competitors = bool(signals.get("competitors"))
    has_colleges = bool(signals.get("college_mentions"))
    nums = (signals.get("user_counts", []) + signals.get("numbers", []))[:3]
    comps = signals.get("competitors", [])[:3]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (nums[0] if nums else (comps[0] if comps else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (nums[:2] + comps[:2])[:5]

    if engagement == 0 and signals.get("signal_count", 0) == 0:
        return 0, _zero_engagement_reason(total, False), str(quote)[:160], []

    score = floor
    parts: list[str] = []

    if has_numbers and has_competitors:
        score = max(score, concrete_floor + 15)
        parts.append(
            f"Market numbers ({', '.join(nums[:2])}) and competitors named ({', '.join(comps[:2])})."
        )
    elif has_numbers and has_colleges:
        score = max(score, concrete_floor + 8)
        parts.append(
            f"User/market numbers ({', '.join(nums[:2])}) with campus context."
        )
    elif has_numbers:
        score = max(score, concrete_floor + 3)
        parts.append(f"Market/user numbers: {', '.join(nums[:2])}.")
    elif has_competitors:
        score = max(score, concrete_floor - 4)
        parts.append(
            f"Competitors identified ({', '.join(comps[:2])}) — indicates market awareness."
        )
    else:
        parts.append("Market described but without user counts, TAM, or competitor landscape.")

    score = _apply_startup_context_cap(_clamp(score), engagement, cal)
    return score, " ".join(parts)[:280], str(quote)[:160], used


def _score_differentiation(signals: dict, engagement: int, total: int, cal: dict | None = None) -> tuple[int, str, str, list]:
    """Did they explain why this beats alternatives (competitor + mechanism/moat)?"""
    cal = cal or {}
    floor = cal.get("attempted_answer_floor", 33)
    non_ans_max = cal.get("non_answer_max", 15)
    concrete_floor = cal.get("concrete_signal_floor", 52)

    has_competitors = bool(signals.get("competitors"))
    has_tech = bool(signals.get("technical_mechanisms"))
    comps = signals.get("competitors", [])[:3]
    techs = signals.get("technical_mechanisms", [])[:3]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (comps[0] if comps else (techs[0] if techs else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (comps[:2] + techs[:2])[:5]

    if engagement == 0 and signals.get("signal_count", 0) == 0:
        return 0, _zero_engagement_reason(total, False), str(quote)[:160], []

    score = floor
    parts: list[str] = []

    if has_competitors and has_tech:
        score = max(score, concrete_floor + 18)
        parts.append(
            f"Named competitors ({', '.join(comps[:2])}) with technical moat ({', '.join(techs[:2])})."
        )
    elif has_competitors:
        score = max(score, concrete_floor)
        parts.append(
            f"Competitors identified ({', '.join(comps[:2])}) but moat/mechanism not fully articulated."
        )
    elif has_tech:
        score = max(score, concrete_floor - 2)
        parts.append(
            f"Technical approach described ({', '.join(techs[:2])}) but no direct competitor comparison."
        )
    else:
        parts.append(
            "Differentiation not clearly supported — no competitors named and no technical mechanism stated."
        )

    score = _apply_startup_context_cap(_clamp(score), engagement, cal)
    return score, " ".join(parts)[:280], str(quote)[:160], used


def _score_business_model(signals: dict, engagement: int, total: int, cal: dict | None = None) -> tuple[int, str, str, list]:
    """Did they explain who pays, how much, and why?"""
    cal = cal or {}
    # Business model floor is intentionally lower — early-stage students often lack revenue
    partial_floor = cal.get("partial_signal_floor", 38)
    concrete_floor = cal.get("concrete_signal_floor", 52)
    non_ans_max = cal.get("non_answer_max", 15)
    biz_floor = max(partial_floor - 10, 12)  # lower than other dims by design

    has_pricing = bool(signals.get("pricing"))
    has_revenue = bool(signals.get("revenue_signals"))
    has_validation = bool(signals.get("validation"))
    pricing = signals.get("pricing", [])[:3]
    revenue = signals.get("revenue_signals", [])[:3]
    best_quotes = signals.get("best_user_quotes", [])
    quote = (pricing[0] if pricing else (revenue[0] if revenue else (best_quotes[0][:160] if best_quotes else "")))
    used: list[str] = (pricing[:2] + revenue[:2])[:5]

    if engagement == 0 and signals.get("signal_count", 0) == 0:
        return 0, _zero_engagement_reason(total, False), str(quote)[:160], []

    score = biz_floor
    parts: list[str] = []

    if has_pricing and has_revenue:
        score = max(score, concrete_floor + 16)
        parts.append(f"Pricing ({', '.join(pricing[:2])}) and revenue logic ({', '.join(revenue[:2])}) present.")
    elif has_pricing:
        score = max(score, concrete_floor)
        parts.append(f"Pricing mentioned: {', '.join(pricing[:2])}.")
    elif has_revenue:
        score = max(score, concrete_floor - 4)
        parts.append(f"Revenue/monetization signals: {', '.join(revenue[:2])}.")
    elif has_validation:
        score = max(score, partial_floor - 2)
        parts.append(
            "Traction/validation evidence present but no explicit pricing or revenue model stated."
        )
    else:
        parts.append("Business model not clearly stated — no pricing, revenue, or monetization mentioned.")

    score = _apply_startup_context_cap(_clamp(score), engagement, cal)
    return score, " ".join(parts)[:280], str(quote)[:160], used


def _score_objection_handling(signals: dict, engagement: int, total: int, cal: dict | None = None) -> tuple[int, str, str, list]:
    """Did they answer hard questions directly with evidence?"""
    cal = cal or {}
    floor = cal.get("attempted_answer_floor", 33)
    non_ans_max = cal.get("non_answer_max", 15)

    has_validation = bool(signals.get("validation"))
    has_numbers = bool(signals.get("numbers") or signals.get("user_counts"))
    has_tech = bool(signals.get("technical_mechanisms"))
    best_quotes = signals.get("best_user_quotes", [])
    quote = best_quotes[0][:160] if best_quotes else ""
    used: list[str] = (signals.get("validation", [])[:2] + signals.get("numbers", [])[:2])[:4]

    if total == 0 or engagement == 0:
        has_ctx = signals.get("signal_count", 0) > 0
        return 0, _zero_engagement_reason(total, has_ctx), quote, []

    engagement_rate = engagement / total
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

    # Floor: use profile floor if majority were substantive
    if engagement_rate > 0.5:
        score = max(score, floor - 3)

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

def _startup_summary_snippet(startup: dict) -> str:
    """Short excerpt from startup form when no battle answers exist."""
    for key in ("solution", "problem", "why_ai", "traction"):
        val = str(startup.get(key, "")).strip()
        if len(val) > 20:
            return val[:400]
    return ""


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
    signals: dict, startup: dict, cal: dict | None = None
) -> tuple[dict[str, Any], str, str, str]:
    """Return (scores_dict, best_answer, weakest_answer, why_weak).

    All 6 dimension scores are computed deterministically from extracted signals.
    No API calls. cal = scoring_calibration dict from the active difficulty profile.
    """
    cal = cal or {}
    all_answers = signals.get("all_user_answers", [])
    non_answers = signals.get("non_answers", [])
    best_quotes = signals.get("best_user_quotes", [])
    total = len(all_answers)
    engagement = total - len(non_answers)  # number of substantive answers

    scores = {
        "clarity": _dimension(
            *_score_clarity(signals, engagement, total, cal)
        ),
        "problem_understanding": _dimension(
            *_score_problem_understanding(signals, engagement, total, cal)
        ),
        "market_awareness": _dimension(
            *_score_market_awareness(signals, engagement, total, cal)
        ),
        "differentiation": _dimension(
            *_score_differentiation(signals, engagement, total, cal)
        ),
        "business_model": _dimension(
            *_score_business_model(signals, engagement, total, cal)
        ),
        "objection_handling": _dimension(
            *_score_objection_handling(signals, engagement, total, cal)
        ),
    }

    if engagement == 0 and total == 0:
        snippet = _startup_summary_snippet(startup)
        if snippet:
            best_answer = snippet
            weakest_answer = "No battle answers were submitted."
            why_weak = "The judge asked questions but no answers were given during the battle."
        else:
            best_answer = "No battle answers were submitted."
            weakest_answer = "No battle answers were submitted."
            why_weak = "No answers were recorded in this session."
    else:
        best_answer = (
            best_quotes[0]
            if best_quotes
            else (all_answers[0] if all_answers else "No battle answers were submitted.")
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
# "Path to 80+" score explanation builder (fully local — no API call)
# ---------------------------------------------------------------------------

_DIM_NAMES = {
    "clarity": "clarity",
    "problem_understanding": "problem understanding",
    "market_awareness": "market awareness",
    "differentiation": "differentiation",
    "business_model": "business model",
    "objection_handling": "objection handling",
}

_DIM_TO_RETRY_ADVICE = {
    "clarity": (
        "When answering questions about your product, name the specific thing you built, "
        "who uses it today, and one number that proves it works."
    ),
    "problem_understanding": (
        "Show you researched the problem — name a real user, a campus, or a specific pain point "
        "you observed firsthand. One validation data point changes everything."
    ),
    "market_awareness": (
        "Size the market with one real number and name at least two alternatives students use today. "
        "Judges want to know you understand the competitive landscape."
    ),
    "differentiation": (
        "Name your top two competitors, then explain the one thing they cannot easily copy from you. "
        "A technical mechanism, a relationship, or a data advantage all count."
    ),
    "business_model": (
        "Say exactly who pays, how much, and when the first payment happens. "
        "Even a rough plan ('₹499/student/month, collect at onboarding') is far stronger than silence."
    ),
    "objection_handling": (
        "When challenged, do not deflect. Answer the exact question with a number, a fact, or a concrete example. "
        "Judges remember founders who hold their ground under pressure."
    ),
}

_TONE_OPENER = {
    "practice": "You are closer than the score feels.",
    "judge": "Here is what the scorecard is actually telling you.",
    "investor": "Here is exactly what held this pitch back.",
}


def _build_score_explanation(
    overall: int,
    scores: dict[str, Any],
    weakest_answer: str,
    why_weak: str,
    signals: dict,
    session: dict,
    difficulty_profile: str = "practice",
) -> dict[str, Any]:
    """Build the 'Path to 80+' coaching section from local data only — no API call."""
    dim_items = sorted(scores.items(), key=lambda x: x[1]["score"])
    strong_dims = [(k, v) for k, v in scores.items() if v["score"] >= 70]
    weak_dims   = [(k, v) for k, v in dim_items if v["score"] < 55]
    blocker_dim, blocker_data = dim_items[0]  # lowest scoring

    strong_names  = [_DIM_NAMES.get(k, k) for k, _ in strong_dims]
    blocker_name  = _DIM_NAMES.get(blocker_dim, blocker_dim)
    blocker_score = blocker_data["score"]
    blocker_label = blocker_data["label"]

    tone_opener = _TONE_OPENER.get(difficulty_profile, _TONE_OPENER["practice"])

    # --- why_you_scored_this ---
    if strong_names:
        strong_str = " and ".join(strong_names[:2])
        why_scored = (
            f"{tone_opener} "
            f"Your {strong_str} answer{'s were' if len(strong_names) > 1 else ' was'} solid, "
            f"but your {blocker_name} answer brought the score down. "
            f"The judge scored {blocker_name} at {blocker_score} ({blocker_label}) "
            f"because {blocker_data.get('reason', 'it lacked concrete evidence')[:120]}."
        )
    else:
        why_scored = (
            f"{tone_opener} "
            f"Your {blocker_name} answer was the main drag on the score — "
            f"{blocker_score} ({blocker_label}). "
            f"{blocker_data.get('reason', 'It lacked concrete evidence')[:120]}."
        )

    # --- what_stopped_80 ---
    history = session.get("history", [])
    ai_messages = [m["content"] for m in history if m.get("role") == "assistant"]
    blocker_question = ai_messages[0][:180] if ai_messages else ""

    if blocker_question:
        what_stopped = (
            f"The biggest gap was in {blocker_name}. "
            f"The judge pressed on this with a question like: \"{blocker_question}\" "
            f"and the answer did not fully land. {why_weak}"
        )
    else:
        what_stopped = (
            f"The biggest gap was in {blocker_name} ({blocker_score}/100). "
            f"{why_weak} "
            f"A stronger answer here alone could push the overall score into the mid-70s."
        )

    # --- answer_to_retry ---
    all_answers = signals.get("all_user_answers", [])
    non_answers = signals.get("non_answers", [])

    # Pick the answer most associated with the blocker dimension
    original_answer = weakest_answer
    attack_tag_for_retry = blocker_name.replace(" ", "_")
    round_for_retry: int | None = None

    # Try to find the round number from history
    user_turns = [m for m in history if m.get("role") == "user"]
    if user_turns:
        worst_idx = None
        shortest_len = 9999
        for idx, m in enumerate(user_turns):
            content = m.get("content", "")
            if content in non_answers and (worst_idx is None or len(content) < shortest_len):
                worst_idx = idx
                shortest_len = len(content)
        if worst_idx is not None:
            round_for_retry = worst_idx + 1
            original_answer = user_turns[worst_idx].get("content", weakest_answer)
        else:
            round_for_retry = len(user_turns)

    retry_advice = _DIM_TO_RETRY_ADVICE.get(blocker_dim, "Give one concrete piece of evidence to back your claim.")

    # Sample stronger answer using signals from session
    numbers  = signals.get("numbers", []) + signals.get("user_counts", [])
    valid    = signals.get("validation", [])
    comps    = signals.get("competitors", [])
    pricing  = signals.get("pricing", [])
    startup  = session.get("startup", {})
    sname    = startup.get("name", "our product")

    sample_parts: list[str] = [f"A stronger answer would say: '{sname} "]
    if numbers:
        sample_parts.append(f"has {numbers[0]} ")
    if valid:
        sample_parts.append(f"validated through {valid[0]} ")
    if comps:
        sample_parts.append(f"— unlike {comps[0]}, we ")
    if pricing:
        sample_parts.append(f"charge {pricing[0]}")
    else:
        sample_parts.append("and our advantage is the specific data and relationships we have built'")
    sample_stronger_answer = "".join(sample_parts).strip()
    if not sample_stronger_answer.endswith("'"):
        sample_stronger_answer += "'"

    why_it_hurt = (
        f"This answer scored low on {blocker_name} because it {why_weak.lower()} "
        f"The judge needs one specific fact, number, or example to move on."
    )

    answer_to_retry = {
        "round": round_for_retry,
        "attack_tag": attack_tag_for_retry,
        "dimension": blocker_dim,
        "original_answer": original_answer[:300],
        "why_it_hurt": why_it_hurt[:300],
        "retry_advice": retry_advice,
        "sample_stronger_answer": sample_stronger_answer[:400],
    }

    # --- estimated_score_if_fixed ---
    if overall >= 80:
        # Already strong — advise path to 90
        gap_to_90 = 90 - overall
        estimated_new = _clamp(overall + min(gap_to_90, 8))
        improvement_reason = (
            f"Your pitch is already strong. To reach 90+, deepen the evidence in "
            f"{blocker_name} and {_DIM_NAMES.get(dim_items[1][0], 'your second weakest area')} "
            f"with specific numbers and a sharper competitive contrast."
        )
    else:
        # Estimate conservative improvement from fixing the main blocker
        blocker_weight = 1 / len(scores)
        point_gain = max(8, min(15, int((70 - blocker_score) * blocker_weight * 1.4)))
        estimated_new = _clamp(overall + point_gain, overall, 82)
        if len(strong_dims) >= 3:
            estimated_new = min(estimated_new + 3, 85)
        improvement_reason = (
            f"Fixing your {blocker_name} answer alone could add roughly {point_gain} points overall. "
            f"This would move your pitch from '{_score_label(overall)}' toward "
            f"'{_score_label(estimated_new)}' territory."
        )

    estimated_score_if_fixed = {
        "current_overall": overall,
        "estimated_new_overall": estimated_new,
        "reason": improvement_reason,
    }

    return {
        "why_you_scored_this": why_scored,
        "what_stopped_80": what_stopped,
        "answer_to_retry": answer_to_retry,
        "estimated_score_if_fixed": estimated_score_if_fixed,
    }


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
    difficulty_profile: str = "practice",
) -> list[dict[str, str]]:
    """Build messages for Nemotron coaching-only call.

    Nemotron generates only: improved_answer, improved_pitch, top_3_questions.
    All scoring is already done locally and passed as context.
    """
    startup = session.get("startup", {})
    coaching_style = get_coaching_style(difficulty_profile)
    difficulty_label = get_label(difficulty_profile)

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

    coaching_instruction = coaching_style.get(
        "instruction",
        "Be encouraging but honest. Show how to make the answer stronger with one specific number or proof point.",
    )
    coaching_example = coaching_style.get("example", "")

    system_content = (
        "Return ONLY valid JSON. Return one JSON object only.\n"
        "First character must be {. Last character must be }.\n"
        "Do not wrap in an array. No markdown. No explanation. No analysis. No reasoning.\n"
        "Keep each field short and complete. Do not end mid-sentence.\n\n"
        f"You are a startup pitch coach for a student founder. Difficulty profile: {difficulty_label}.\n\n"
        f"COACHING STYLE: {coaching_instruction}\n"
        + (f"TONE EXAMPLE: {coaching_example}\n\n" if coaching_example else "\n")
        + "RULES:\n"
        "  - Do NOT hallucinate traction, numbers, or facts not in the provided context.\n"
        "  - Do NOT re-score — scores are already computed.\n"
        "  - Use actual startup context and actual founder answers.\n"
        "  - If concrete signals exist, reference them in improved_answer and improved_pitch.\n"
        "  - Use 'your answer' or 'you said' — never 'you typed' (voice transcripts also arrive here).\n"
        "  - improved_answer: 3-5 sentences rewriting the weakest answer.\n"
        "  - improved_pitch: 4-6 sentences — one concise 60-second pitch.\n"
        "  - top_3_questions: exactly 3 strings.\n"
        "  - score_explanation: Path to 80+ coaching — keep each field SHORT and COMPLETE.\n"
        "    why_you_scored_this: max 2 sentences.\n"
        "    what_stopped_80: max 2 sentences.\n"
        "    answer_to_retry.retry_advice: ONE complete sentence only.\n"
        "    answer_to_retry.sample_stronger_answer: 3-4 sentences max.\n\n"
        "Return exactly this JSON schema — nothing else:\n"
        '{"improved_answer":"string","improved_pitch":"string","top_3_questions":["string","string","string"],'
        '"score_explanation":{"why_you_scored_this":"string","what_stopped_80":"string",'
        '"answer_to_retry":{"round":null,"attack_tag":"string","dimension":"string",'
        '"original_answer":"string","why_it_hurt":"string","retry_advice":"string",'
        '"sample_stronger_answer":"string"},'
        '"estimated_score_if_fixed":{"current_overall":0,"estimated_new_overall":0,"reason":"string"}}}'
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


def _ends_abruptly(text: str) -> bool:
    """Return True if text looks cut off mid-sentence."""
    t = text.strip()
    if not t:
        return True
    if t[-1] in ".!?":
        return False
    # Short fragment without terminal punctuation is likely truncated
    if len(t) < 50:
        return True
    # Longer text without punctuation may still be valid — only flag if very short last token
    last_word = t.split()[-1] if t.split() else ""
    return len(last_word) <= 2 and len(t) < 80


def _field_looks_truncated(field: str, text: str) -> bool:
    """Return True if a score_explanation text field appears incomplete."""
    t = text.strip()
    if not t:
        return True
    if field == "retry_advice":
        return len(t) < 20 or _ends_abruptly(t)
    if field in ("why_you_scored_this", "what_stopped_80"):
        return _ends_abruptly(t)
    if field == "sample_stronger_answer":
        return len(t) < 30 or _ends_abruptly(t)
    return _ends_abruptly(t)


def _parse_coaching_score_explanation(raw: Any) -> dict[str, Any] | None:
    """Parse score_explanation sub-object from coaching JSON."""
    if not isinstance(raw, dict):
        return None
    atr_raw = raw.get("answer_to_retry", {})
    esif_raw = raw.get("estimated_score_if_fixed", {})
    if not isinstance(atr_raw, dict):
        atr_raw = {}
    if not isinstance(esif_raw, dict):
        esif_raw = {}
    why = str(raw.get("why_you_scored_this", "")).strip()
    if not why:
        return None
    return {
        "why_you_scored_this": why,
        "what_stopped_80": str(raw.get("what_stopped_80", "")).strip(),
        "answer_to_retry": {
            "round": atr_raw.get("round"),
            "attack_tag": str(atr_raw.get("attack_tag", "")).strip(),
            "dimension": str(atr_raw.get("dimension", "")).strip(),
            "original_answer": str(atr_raw.get("original_answer", "")).strip()[:300],
            "why_it_hurt": str(atr_raw.get("why_it_hurt", "")).strip()[:300],
            "retry_advice": str(atr_raw.get("retry_advice", "")).strip(),
            "sample_stronger_answer": str(atr_raw.get("sample_stronger_answer", "")).strip()[:400],
        },
        "estimated_score_if_fixed": {
            "current_overall": esif_raw.get("current_overall"),
            "estimated_new_overall": esif_raw.get("estimated_new_overall"),
            "reason": str(esif_raw.get("reason", "")).strip(),
        },
    }


def _resolve_score_explanation(
    nemotron_se: dict[str, Any] | None,
    local_se: dict[str, Any],
    overall: int,
) -> dict[str, Any]:
    """Merge Nemotron score_explanation with local fallback — never keep truncated fields."""
    if not nemotron_se:
        return local_se

    result = {
        "why_you_scored_this": local_se.get("why_you_scored_this", ""),
        "what_stopped_80": local_se.get("what_stopped_80", ""),
        "answer_to_retry": dict(local_se.get("answer_to_retry", {})),
        "estimated_score_if_fixed": dict(local_se.get("estimated_score_if_fixed", {})),
    }

    for field in ("why_you_scored_this", "what_stopped_80"):
        n_val = str(nemotron_se.get(field, "")).strip()
        if n_val and not _field_looks_truncated(field, n_val):
            result[field] = n_val

    local_atr = local_se.get("answer_to_retry", {})
    n_atr = nemotron_se.get("answer_to_retry", {})
    merged_atr = dict(local_atr) if isinstance(local_atr, dict) else {}
    if isinstance(n_atr, dict):
        for key in ("round", "attack_tag", "dimension", "original_answer", "why_it_hurt"):
            n_val = n_atr.get(key)
            if key in ("original_answer", "why_it_hurt"):
                n_val = str(n_val or "").strip()
                if n_val and not _field_looks_truncated(key, n_val):
                    merged_atr[key] = n_val[:300]
            elif n_val is not None and str(n_val).strip():
                merged_atr[key] = n_val
        retry = str(n_atr.get("retry_advice", "")).strip()
        if retry and not _field_looks_truncated("retry_advice", retry):
            merged_atr["retry_advice"] = retry
        sample = str(n_atr.get("sample_stronger_answer", "")).strip()
        if sample and not _field_looks_truncated("sample_stronger_answer", sample):
            merged_atr["sample_stronger_answer"] = sample[:400]
    result["answer_to_retry"] = merged_atr

    local_esif = local_se.get("estimated_score_if_fixed", {})
    n_esif = nemotron_se.get("estimated_score_if_fixed", {})
    merged_esif = dict(local_esif) if isinstance(local_esif, dict) else {}
    if isinstance(n_esif, dict):
        est = n_esif.get("estimated_new_overall")
        reason = str(n_esif.get("reason", "")).strip()
        if isinstance(est, (int, float)) and not _field_looks_truncated("reason", reason):
            merged_esif["estimated_new_overall"] = _clamp(int(est), overall, 95)
        if reason and not _field_looks_truncated("reason", reason):
            merged_esif["reason"] = reason
    merged_esif["current_overall"] = overall
    result["estimated_score_if_fixed"] = merged_esif

    return result


def _parse_coaching_json(raw: str) -> dict[str, Any]:
    """Parse coaching JSON — best effort, may return partial fields."""
    parsed = parse_json_object(
        raw,
        string_fields=["improved_answer", "improved_pitch", "why_you_scored_this", "what_stopped_80"],
    )
    if not parsed:
        partial = extract_partial_string_fields(raw, ["improved_answer", "improved_pitch"])
        parsed = partial

    if not parsed:
        return {}

    improved_answer = str(parsed.get("improved_answer", "")).strip()
    improved_pitch = str(parsed.get("improved_pitch", "")).strip()
    raw_q = parsed.get("top_3_questions", [])

    if not raw_q:
        raw_q = extract_partial_string_list(raw, "top_3_questions", min_items=3)

    if isinstance(raw_q, list):
        questions = [str(q).strip() for q in raw_q if str(q).strip()][:3]
    else:
        questions = []

    result: dict[str, Any] = {}
    if improved_answer and not ends_abruptly(improved_answer):
        result["improved_answer"] = improved_answer
    if improved_pitch and not ends_abruptly(improved_pitch):
        result["improved_pitch"] = improved_pitch
    if questions:
        result["top_3_questions"] = questions

    se = _parse_coaching_score_explanation(parsed.get("score_explanation"))
    if se:
        result["score_explanation"] = se
    elif isinstance(parsed.get("score_explanation"), dict):
        se_partial = parsed["score_explanation"]
        if isinstance(se_partial, dict):
            partial_se: dict[str, Any] = {}
            for field in ("why_you_scored_this", "what_stopped_80"):
                val = str(se_partial.get(field, "")).strip()
                if val and not _field_looks_truncated(field, val):
                    partial_se[field] = val
            if partial_se:
                result["score_explanation"] = partial_se

    return result


def _coaching_source_label(nemotron: dict[str, Any], local: dict[str, Any]) -> str:
    """Classify how much coaching came from Nemotron vs local fallback."""
    core_keys = ("improved_answer", "improved_pitch", "top_3_questions")
    n_hits = sum(1 for k in core_keys if nemotron.get(k))
    if n_hits >= 3:
        return "nemotron"
    if n_hits > 0:
        return "partial_nemotron_local"
    return "local"


def _merge_coaching_with_local(
    nemotron: dict[str, Any] | None,
    local: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Merge Nemotron coaching with local fallback field-by-field."""
    nemotron = nemotron or {}
    merged = dict(local)
    for key in ("improved_answer", "improved_pitch"):
        val = str(nemotron.get(key, "")).strip()
        if val and not ends_abruptly(val):
            merged[key] = val
    n_q = nemotron.get("top_3_questions")
    if isinstance(n_q, list) and len(n_q) >= 3:
        merged["top_3_questions"] = [str(q).strip() for q in n_q[:3]]
    elif isinstance(n_q, list) and n_q:
        base = list(local.get("top_3_questions", []))
        for i, q in enumerate(n_q):
            if i < 3 and str(q).strip():
                if i < len(base):
                    base[i] = str(q).strip()
                else:
                    base.append(str(q).strip())
        while len(base) < 3:
            base.append("What concrete evidence can you give to support your strongest claim?")
        merged["top_3_questions"] = base[:3]
    if nemotron.get("score_explanation"):
        merged["score_explanation"] = nemotron["score_explanation"]
    return merged, _coaching_source_label(nemotron, local)


def _resolve_coaching_from_raw(
    coaching_raw: str,
    local: dict[str, Any],
    resolved_mode: str,
) -> tuple[dict[str, Any], str]:
    """Parse + repair Nemotron coaching, merging with local field-by-field."""
    nemotron = _parse_coaching_json(coaching_raw) if coaching_raw else {}
    if not nemotron.get("improved_answer") and not nemotron.get("improved_pitch") and coaching_raw:
        logger.warning("scoring_engine: coaching parse failed, trying repair")
        try:
            repair = model_router.generate_coaching_repair_response(coaching_raw, model_mode=resolved_mode)
            if repair.get("ok") and repair.get("content"):
                repaired = _parse_coaching_json(repair["content"])
                for k, v in repaired.items():
                    if v and not nemotron.get(k):
                        nemotron[k] = v
                if repaired:
                    logger.info("scoring_engine: repaired coaching JSON OK")
        except Exception as exc:
            logger.warning("scoring_engine: coaching repair raised — %s", exc)

    merged, source = _merge_coaching_with_local(nemotron, local)
    if source == "local":
        logger.warning("scoring_engine: coaching fallback to local (scoring still nemotron_full)")
    elif source == "partial_nemotron_local":
        logger.info("scoring_engine: partial Nemotron coaching merged with local fields")
    return merged, source


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
# Nemotron primary scoring path (Phase 8) — split into two smaller calls
#
# Call 1: scorecard_scoring — 6 dimension scores + best/weakest/why_weak
# Call 2: scorecard_coaching — improved_answer, improved_pitch, top_3_questions
#
# This split keeps each JSON payload small enough for long battles (9+ rounds).
# scorecard_source = "nemotron_full" when Call 1 succeeds, regardless of Call 2.
# ---------------------------------------------------------------------------

_SCORING_SCHEMA = (
    '{"scores":{'
    '"clarity":{"score":0,"reason":"","quote":"","signals_used":[]},'
    '"problem_understanding":{"score":0,"reason":"","quote":"","signals_used":[]},'
    '"market_awareness":{"score":0,"reason":"","quote":"","signals_used":[]},'
    '"differentiation":{"score":0,"reason":"","quote":"","signals_used":[]},'
    '"business_model":{"score":0,"reason":"","quote":"","signals_used":[]},'
    '"objection_handling":{"score":0,"reason":"","quote":"","signals_used":[]}},'
    '"best_answer":"","weakest_answer":"","why_weak":""}'
)


def _build_scoring_only_prompt(
    session: dict,
    signals: dict,
    local_reference: dict | None,
    difficulty_profile: str,
    difficulty_label: str,
) -> list[dict[str, str]]:
    """Build the Nemotron scoring-only prompt (Call 1).

    Returns scores for all 6 dims + best/weakest/why_weak.
    No coaching text, no score_explanation — keeps the JSON small.
    """
    startup = session.get("startup", {})
    history = session.get("history", [])

    startup_block = "\n".join([
        f"Startup: {startup.get('name', 'Unknown')}",
        f"Problem: {startup.get('problem', 'Not stated')}",
        f"Solution: {startup.get('solution', 'Not stated')}",
        f"Stage: {startup.get('stage', 'Not stated')}",
        f"Traction: {startup.get('traction', 'Not stated')}",
    ])

    # Battle history — truncate each turn to keep prompt lean
    ai_turns = [m for m in history if m.get("role") == "assistant"]
    user_turns = [m for m in history if m.get("role") == "user"]
    history_lines: list[str] = ["BATTLE Q&A:"]
    for i, (ai_msg, user_msg) in enumerate(zip(ai_turns, user_turns), start=1):
        history_lines.append(f"R{i} Judge: {ai_msg.get('content','')[:200]}")
        history_lines.append(f"R{i} Founder: {user_msg.get('content','')[:200]}")
    battle_block = "\n".join(history_lines)

    # Signals block — brief
    sig_parts: list[str] = []
    for key, label in [
        ("numbers", "Numbers"), ("validation", "Validation"),
        ("competitors", "Competitors"), ("pricing", "Pricing"),
        ("technical_mechanisms", "Tech"), ("non_answers", "Non-answers"),
    ]:
        items = signals.get(key, [])[:4]
        if items:
            sig_parts.append(f"{label}: {', '.join(str(x) for x in items)}")
    signals_block = "SIGNALS: " + " | ".join(sig_parts) if sig_parts else ""

    local_block = ""
    if local_reference and isinstance(local_reference.get("scores"), dict):
        ref_parts = []
        for dim in _REQUIRED_DIMS:
            d = local_reference["scores"].get(dim, {})
            ref_parts.append(f"{dim}={d.get('score','?')}")
        local_block = "LOCAL REF (hints only): " + ", ".join(ref_parts)

    profile_guidance = {
        "practice": (
            "This founder is a STUDENT practising. Judge intent and real signals generously. "
            "A genuine attempt that includes one concrete detail (a number, a named user, a "
            "real test result) should land 55+. Never punish casual phrasing, nerves, short "
            "answers, or imperfect grammar. Reserve low scores for non-answers or honest "
            "admissions of not knowing."
        ),
        "judge": "Balanced hackathon judging. Reward concrete evidence. Penalise deflection.",
        "investor": "Investor-grade. Vague answers on revenue/moat hurt significantly.",
    }.get(difficulty_profile, "Be fair and honest.")

    system_content = (
        "Return ONLY valid JSON. First character {. Last character }. No markdown. No explanation.\n\n"
        "You are scoring a real founder talking, often a student. Judge whether the answer "
        "contains the RIGHT KIND OF PROOF for the question — not how polished it sounds.\n\n"
        "SCORE WHAT MATTERS:\n"
        "  Score the PRESENCE and RELEVANCE of concrete signals (a real number, a named user, "
        "a test/pilot result, a named competitor with a reason, a pricing figure).\n"
        "  Do NOT reward length, fluency, grammar, jargon, or polish. A short, plain, or "
        "informal answer that carries one real proof point must score the SAME as a long "
        "polished answer with the same proof. Do not reward verbosity.\n"
        "  Example: 'we tested with 40 students and the quiz group did better' is REAL "
        "validation — score it as concrete evidence even though it is short and casual.\n\n"
        "RELEVANCE GUARD (do not let this be gamed):\n"
        "  A signal only counts for the dimension it actually addresses. Naming a competitor "
        "or saying a buzzword does NOT earn differentiation if the founder cannot say why they "
        "are better. If the founder says 'I don't know' / 'okay' / one word, or admits the "
        "issue is unsolved, score THAT dimension honestly low (10-25) even if keywords appear.\n\n"
        "BANDS:\n"
        "  Non-answer / 'I don't know' / one word = 10-25.\n"
        "  Relevant attempt but no concrete proof = 35-50.\n"
        "  At least one real, relevant proof point (even if short/casual) = 55-78.\n"
        "  Strong answer with specific, well-matched proof = 79-92.\n"
        "  Recovery rule: score the strongest relevant answer if the founder improved later.\n"
        "  Do NOT hallucinate facts not in the conversation.\n"
        "  Each reason: 1 sentence. Quote: short excerpt. signals_used: max 4 items.\n"
        "  best_answer and weakest_answer: copy the ACTUAL founder answer text verbatim.\n"
        "  NEVER use round labels like R1, R2, R4 — always paste the real answer sentence(s).\n\n"
        "The SIGNALS block below was extracted from the founder's answers — credit those real "
        "signals for the dimensions they fit, even when the wording was brief or informal.\n\n"
        f"PROFILE: {difficulty_label} — {profile_guidance}\n\n"
        "SCHEMA:\n" + _SCORING_SCHEMA
    )

    user_content = (
        f"{startup_block}\n\n"
        f"{battle_block}\n\n"
        f"{signals_block}\n"
        f"{local_block}\n\n"
        "Score each dimension based on what was ACTUALLY said. Return JSON only."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _normalize_scoring_json(parsed: dict) -> dict:
    """Fill missing reason fields so structurally valid JSON passes validation."""
    if not isinstance(parsed, dict):
        return parsed
    scores = parsed.get("scores")
    if not isinstance(scores, dict):
        return parsed
    for dim in _REQUIRED_DIMS:
        d = scores.get(dim)
        if not isinstance(d, dict):
            scores[dim] = {"score": 0, "reason": "No reasoning provided.", "quote": "", "signals_used": []}
            continue
        if not str(d.get("reason", "")).strip():
            score = d.get("score", 0)
            try:
                score_int = int(round(float(score)))
            except (TypeError, ValueError):
                score_int = 0
            d["reason"] = f"Score: {score_int} based on answer quality."
    return parsed


def _validate_scoring_json(parsed: dict) -> bool:
    """Return True if the scoring-only JSON has all required dimension fields."""
    if not isinstance(parsed, dict):
        return False
    scores = parsed.get("scores")
    if not isinstance(scores, dict) or len(scores) < 6:
        return False
    for dim in _REQUIRED_DIMS:
        d = scores.get(dim)
        if not isinstance(d, dict):
            return False
        score = d.get("score")
        if not isinstance(score, (int, float)):
            return False
        if not str(d.get("reason", "")).strip():
            return False
    return True


def _normalize_scoring_result(parsed: dict) -> tuple[dict[str, Any], str, str, str]:
    """Extract and normalize dimension scores from scoring-only JSON.

    Returns (scores_dict, best_answer, weakest_answer, why_weak).
    Backend computes labels from Nemotron scores.
    """
    raw_scores = parsed.get("scores", {})
    scores: dict[str, Any] = {}
    for dim in _REQUIRED_DIMS:
        d = raw_scores.get(dim, {})
        raw_score = d.get("score", 0)
        score = _clamp(int(round(float(raw_score))), 0, 100)
        scores[dim] = {
            "score": score,
            "label": _score_label(score),
            "reason": str(d.get("reason", "")).strip()[:280] or f"Score: {score}",
            "quote": str(d.get("quote", "")).strip()[:160],
            "signals_used": [str(s) for s in d.get("signals_used", [])][:5],
        }
    best_answer = str(parsed.get("best_answer", "")).strip()[:400]
    weakest_answer = str(parsed.get("weakest_answer", "")).strip()[:400]
    why_weak = str(parsed.get("why_weak", "")).strip()[:300]
    return scores, best_answer, weakest_answer, why_weak


def _call_nemotron_scoring(
    session: dict,
    signals: dict,
    local_reference: dict | None,
    difficulty_profile: str,
    difficulty_label: str,
    resolved_mode: str,
) -> tuple[dict[str, Any], str, str, str] | None:
    """Call Nemotron for dimension scores only (Call 1).

    Returns (scores, best_answer, weakest_answer, why_weak) on success, or None on failure.
    """
    messages = _build_scoring_only_prompt(
        session, signals, local_reference, difficulty_profile, difficulty_label
    )
    raw_content = ""
    try:
        result = model_router.generate_scoring_response(messages, model_mode=resolved_mode)
        if result.get("ok") and result.get("content"):
            raw_content = result["content"]
        else:
            logger.warning("scoring_engine: Nemotron scoring call not ok — %s", result.get("error"))
            return None
    except Exception as exc:
        logger.warning("scoring_engine: Nemotron scoring raised — %s", exc)
        return None

    parsed, extraction_used = parse_model_json(raw_content)
    if not isinstance(parsed, dict) or not parsed:
        parsed = safe_json_parse(raw_content)
        extraction_used = True

    if isinstance(parsed, dict) and parsed:
        parsed = _normalize_scoring_json(parsed)
        if _validate_scoring_json(parsed):
            logger.info(
                "scoring_engine: Nemotron scoring JSON parsed OK (content_len=%d extraction=%s preview=%r)",
                len(raw_content),
                extraction_used,
                sanitize_for_log(raw_content),
            )
            return _normalize_scoring_result(parsed)

    # Repair attempt
    logger.warning(
        "scoring_engine: Nemotron scoring parse failed, attempting repair "
        "(content_len=%d preview=%r)",
        len(raw_content),
        sanitize_for_log(raw_content),
    )
    try:
        repair = model_router.generate_scoring_repair_response(raw_content, model_mode=resolved_mode)
        if repair.get("ok") and repair.get("content"):
            repaired, _ = parse_model_json(repair["content"])
            if not isinstance(repaired, dict) or not repaired:
                repaired = safe_json_parse(repair["content"])
            if isinstance(repaired, dict) and repaired:
                repaired = _normalize_scoring_json(repaired)
            if isinstance(repaired, dict) and repaired and _validate_scoring_json(repaired):
                logger.info("scoring_engine: repaired scoring JSON OK")
                return _normalize_scoring_result(repaired)
    except Exception as exc:
        logger.warning("scoring_engine: scoring repair raised — %s", exc)

    logger.warning("scoring_engine: Nemotron scoring failed — will fall back to local scores")
    return None


# ---------------------------------------------------------------------------
# Main scorecard generator — Nemotron full scoring primary (Phase 8)
# ---------------------------------------------------------------------------

def generate_claim_based_scorecard(
    session: dict, model_mode: str | None = None
) -> dict[str, Any]:
    """Main scorecard generator — split Nemotron calls for reliability.

    Call 1 (scorecard_scoring): Nemotron judges all 6 dims from actual Q&A.
    Call 2 (scorecard_coaching): Nemotron generates coaching text + score_explanation.

    scorecard_source = "nemotron_full"   when Call 1 succeeds (regardless of Call 2).
    scorecard_source = "hybrid_claims_*" when Call 1 fails (fallback only).

    Returns a frontend-safe dict with all required fields on every path.
    """
    resolved_mode = model_mode or session.get("model_mode") or os.getenv(
        "DEFAULT_MODEL_MODE", "premium_nvidia"
    )
    difficulty_profile = normalize_difficulty(
        session.get("difficulty_profile") or session.get("difficulty") or "practice"
    )
    difficulty_label = get_label(difficulty_profile)
    cal = get_scoring_calibration(difficulty_profile)
    startup = session.get("startup", {})

    # Step 1: Extract signals — always needed for context + fallback
    try:
        signals = extract_concrete_signals(session)
    except Exception as exc:
        logger.warning("scoring_engine: signal extraction failed: %s", exc)
        signals = _empty_signals()

    engagement_info = _battle_engagement(signals)
    startup_signals = extract_startup_context_signals(session)
    has_startup = _has_startup_context(startup, startup_signals)
    if engagement_info["substantive_answers"] == 0:
        signals = _merge_signal_dicts(signals, startup_signals)

    concrete_signals_summary = {
        "numbers":              signals.get("numbers", [])[:6],
        "validation":           signals.get("validation", [])[:6],
        "competitors":          signals.get("competitors", [])[:6],
        "revenue_signals":      signals.get("revenue_signals", [])[:6],
        "technical_mechanisms": signals.get("technical_mechanisms", [])[:6],
    }

    # Step 2: Compute local scores as reference context + fallback
    local_reference: dict[str, Any] | None = None
    local_scores: dict[str, Any] | None = None
    local_best = ""
    local_weakest = ""
    local_why_weak = ""
    try:
        _ls, local_best, local_weakest, local_why_weak = _compute_local_scores(signals, startup, cal)
        local_scores = _ls
        local_reference = {"scores": local_scores, "best_answer": local_best, "weakest_answer": local_weakest}
    except Exception as exc:
        logger.warning("scoring_engine: local scoring failed: %s", exc)

    # Step 3: Nemotron scoring call (Call 1) — skip when no substantive battle answers
    nemotron_scoring_result = None
    skip_nemotron_scoring = engagement_info["substantive_answers"] == 0
    if skip_nemotron_scoring:
        logger.info(
            "scoring_engine: skipping Nemotron scoring — no substantive battle answers "
            "(user_turns=%d substantive=%d has_startup=%s)",
            engagement_info["user_turns"],
            engagement_info["substantive_answers"],
            has_startup,
        )
    elif resolved_mode == "premium_nvidia":
        nemotron_scoring_result = _call_nemotron_scoring(
            session, signals, local_reference,
            difficulty_profile, difficulty_label, resolved_mode,
        )

    if nemotron_scoring_result is not None:
        # Call 1 succeeded — scorecard_source is always "nemotron_full" from here
        scores, best_answer, weakest_answer, why_weak = nemotron_scoring_result

        # Practice fairness: lift any dimension up to its signal-justified local floor
        # so a short, genuine student answer is not dragged down by a prose-biased judge.
        scores = _apply_practice_signal_floor(scores, local_reference, difficulty_profile)

        # Resolve round refs (R2, R4) to actual founder answer text
        best_answer, weakest_answer, best_round, weakest_round = _resolve_best_weakest_answers(
            session, best_answer, weakest_answer, local_best, local_weakest,
        )
        if not why_weak and local_why_weak:
            why_weak = local_why_weak

        overall = round(sum(d["score"] for d in scores.values()) / len(scores))
        overall = _apply_practice_score_nudge(overall, signals, difficulty_profile)

        # Step 4: Nemotron coaching call
        local_coaching = _local_coaching(weakest_answer, startup, signals, scores)
        coaching_raw = ""
        try:
            coaching_messages = _build_coaching_prompt(
                session, signals, scores, best_answer, weakest_answer, why_weak,
                difficulty_profile=difficulty_profile,
            )
            coaching_result = model_router.generate_coaching_response(
                coaching_messages, model_mode=resolved_mode
            )
            if coaching_result.get("ok") and coaching_result.get("content"):
                coaching_raw = coaching_result["content"]
            else:
                logger.warning("scoring_engine: coaching call not ok — %s", coaching_result.get("error"))
        except Exception as exc:
            logger.warning("scoring_engine: coaching call raised — %s", exc)

        coaching, coaching_source = _resolve_coaching_from_raw(
            coaching_raw, local_coaching, resolved_mode
        )

        # Step 5: score_explanation — merge Nemotron coaching with local fallback (no truncated fields)
        try:
            local_score_explanation = _build_score_explanation(
                overall, scores, weakest_answer, why_weak, signals, session, difficulty_profile
            )
        except Exception as exc:
            logger.warning("scoring_engine: score_explanation build failed: %s", exc)
            local_score_explanation = {
                "why_you_scored_this": f"Your overall score is {overall}/100.",
                "what_stopped_80": "Focus on your weakest dimension to improve.",
                "answer_to_retry": {
                    "round": None, "attack_tag": "", "dimension": "",
                    "original_answer": weakest_answer[:200], "why_it_hurt": why_weak,
                    "retry_advice": "", "sample_stronger_answer": "",
                },
                "estimated_score_if_fixed": {
                    "current_overall": overall,
                    "estimated_new_overall": min(overall + 10, 82),
                    "reason": "Fixing your weakest answer could raise your overall score.",
                },
            }
        se_raw = coaching.get("score_explanation") if isinstance(coaching.get("score_explanation"), dict) else None
        score_explanation = _resolve_score_explanation(se_raw, local_score_explanation, overall)

        q3 = coaching.get("top_3_questions", [])
        while len(q3) < 3:
            q3.append("What concrete evidence can you give to support your strongest claim?")

        logger.info(
            "scoring_engine: nemotron_full complete — overall=%d signals=%d",
            overall, signals.get("signal_count", 0),
        )
        result = {
            "overall": overall,
            "overall_label": _score_label(overall),
            "scores": scores,
            "best_answer": best_answer,
            "weakest_answer": weakest_answer,
            "best_answer_round": best_round,
            "weakest_answer_round": weakest_round,
            "why_weak": why_weak,
            "improved_answer": coaching.get("improved_answer", ""),
            "improved_pitch": coaching.get("improved_pitch", ""),
            "top_3_questions": q3[:3],
            "concrete_signals_summary": concrete_signals_summary,
            "score_explanation": score_explanation,
            "model_ok": True,
            "provider": "nvidia",
            "model_mode": resolved_mode,
            "scorecard_source": "nemotron_full",
            "coaching_source": coaching_source,
            "difficulty_profile": difficulty_profile,
            "difficulty_label": difficulty_label,
        }
        result = _sync_overall_to_dimensions(result)
        result["overall"] = _apply_practice_score_nudge(
            int(result["overall"]), signals, difficulty_profile
        )
        result["overall_label"] = _score_label(result["overall"])
        return result

    # Step 6: Local claim-based path (Nemotron skipped or failed)
    if skip_nemotron_scoring:
        logger.info("scoring_engine: building local scorecard for zero-engagement battle")
    else:
        logger.warning("scoring_engine: Nemotron scoring failed; using claim-based fallback")

    if local_scores is None:
        return build_session_aware_fallback_scorecard(
            session, signals, "All scoring paths failed"
        )

    scores = local_scores
    best_answer, weakest_answer, best_round, weakest_round = _resolve_best_weakest_answers(
        session, local_best, local_weakest, local_best, local_weakest,
    )
    why_weak = local_why_weak
    overall = round(sum(d["score"] for d in scores.values()) / len(scores))
    overall = _apply_practice_score_nudge(overall, signals, difficulty_profile)

    coaching = None
    coaching_raw = ""
    local_coaching = _local_coaching(weakest_answer, startup, signals, scores)
    try:
        coaching_messages = _build_coaching_prompt(
            session, signals, scores, best_answer, weakest_answer, why_weak,
            difficulty_profile=difficulty_profile,
        )
        coaching_result = model_router.generate_coaching_response(
            coaching_messages, model_mode=resolved_mode
        )
        if coaching_result.get("ok") and coaching_result.get("content"):
            coaching_raw = coaching_result["content"]
    except Exception as exc:
        logger.warning("scoring_engine: fallback coaching raised — %s", exc)

    coaching, coaching_source = _resolve_coaching_from_raw(
        coaching_raw, local_coaching, resolved_mode
    )

    if skip_nemotron_scoring:
        if has_startup or signals.get("signal_count", 0) > 0:
            source = "startup_context_only"
        else:
            source = "no_battle_response"
        provider = "local+nvidia" if coaching_source != "local" else "local"
    elif coaching_source == "local":
        source = "hybrid_claims_local"
        provider = "local"
    else:
        source = "hybrid_claims_nemotron"
        provider = "local+nvidia"

    try:
        score_explanation = _build_score_explanation(
            overall, scores, weakest_answer, why_weak, signals, session, difficulty_profile
        )
    except Exception:
        score_explanation = {
            "why_you_scored_this": f"Your overall score is {overall}/100.",
            "what_stopped_80": "Focus on your weakest dimension to improve.",
            "answer_to_retry": {
                "round": None, "attack_tag": "", "dimension": "",
                "original_answer": weakest_answer[:200], "why_it_hurt": why_weak,
                "retry_advice": "", "sample_stronger_answer": "",
            },
            "estimated_score_if_fixed": {
                "current_overall": overall,
                "estimated_new_overall": min(overall + 10, 82),
                "reason": "Fixing your weakest answer could raise your overall score.",
            },
        }

    se_raw = coaching.get("score_explanation") if isinstance(coaching.get("score_explanation"), dict) else None
    score_explanation = _resolve_score_explanation(se_raw, score_explanation, overall)

    q3 = coaching.get("top_3_questions", [])
    while len(q3) < 3:
        q3.append("What concrete evidence can you give to support your strongest claim?")

    logger.info(
        "scoring_engine: fallback scorecard complete — overall=%d source=%s",
        overall, source,
    )
    return {
        "overall": overall,
        "overall_label": _score_label(overall),
        "scores": scores,
        "best_answer": best_answer,
        "weakest_answer": weakest_answer,
        "best_answer_round": best_round,
        "weakest_answer_round": weakest_round,
        "why_weak": why_weak,
        "improved_answer": coaching.get("improved_answer", ""),
        "improved_pitch": coaching.get("improved_pitch", ""),
        "top_3_questions": q3[:3],
        "concrete_signals_summary": concrete_signals_summary,
        "score_explanation": score_explanation,
        "model_ok": False,
        "provider": provider,
        "model_mode": resolved_mode,
        "scorecard_source": source,
        "coaching_source": coaching_source,
        "difficulty_profile": difficulty_profile,
        "difficulty_label": difficulty_label,
        "model_error": (
            "No battle answers were submitted."
            if skip_nemotron_scoring and not has_startup and signals.get("signal_count", 0) == 0
            else (
                "Scored from startup description only — complete the battle to earn full points."
                if skip_nemotron_scoring
                else "Nemotron scoring failed; used local scoring fallback."
            )
        ),
    }


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
    fallback_why_weak = "This answer lacked concrete evidence compared to your stronger responses."

    try:
        fb_explanation = _build_score_explanation(
            overall, scores, weakest_answer, fallback_why_weak, signals, session, "practice"
        )
    except Exception:
        fb_explanation = {
            "why_you_scored_this": f"Your overall score is {overall}/100.",
            "what_stopped_80": "Focus on your weakest dimension to improve.",
            "answer_to_retry": {
                "round": None, "attack_tag": "", "dimension": "",
                "original_answer": weakest_answer[:200],
                "why_it_hurt": fallback_why_weak, "retry_advice": "",
                "sample_stronger_answer": "",
            },
            "estimated_score_if_fixed": {
                "current_overall": overall,
                "estimated_new_overall": min(overall + 10, 82),
                "reason": "Fixing your weakest answer could raise your overall score.",
            },
        }

    return {
        "overall": overall,
        "overall_label": _score_label(overall),
        "scores": scores,
        "best_answer": best_answer,
        "weakest_answer": weakest_answer,
        "why_weak": fallback_why_weak,
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
        "score_explanation": fb_explanation,
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
