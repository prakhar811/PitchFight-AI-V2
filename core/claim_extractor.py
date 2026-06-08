"""Concrete claim and signal extractor for PitchFight AI scorecard.

Extracts evidence signals from founder answers using regex/rule-based logic.
No API calls — fast, local, deterministic.

Used by scoring_engine.py to:
  1. Enrich the Nemotron scoring prompt with pre-extracted signal data
  2. Build session-aware fallback scorecards when model scoring fails
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_NUMBER_METRIC = re.compile(
    r"\b\d[\d,]*\.?\d*\s*"
    r"(?:%|percent|users?|students?|signups?|schools?|campuses?|"
    r"colleges?|installs?|ambassadors?|interviews?|pilots?|teams?|"
    r"paying|members?|founders?|customers?|clients?|respondents?|"
    r"participants?|responses?)\b"
    r"|\b\d[\d,]+\b",
    re.IGNORECASE,
)

_PERCENTAGE = re.compile(
    r"\b\d+\.?\d*\s*%|\b\d+\.?\d*\s*percent\b",
    re.IGNORECASE,
)

_CURRENCY = re.compile(
    r"[₹$€£¥]\s*\d[\d,.]*"
    r"|\b\d[\d,.]*\s*(?:rupees?|dollars?|usd|inr|cad|euros?)\b"
    r"|\brs\.?\s*\d[\d,.]*\b",
    re.IGNORECASE,
)

_USER_COUNT = re.compile(
    r"\b\d+\s*(?:beta\s+)?users?\b"
    r"|\b\d+\s*(?:beta\s+)?signups?\b"
    r"|\b\d+\s*students?\b"
    r"|\b\d+\s*members?\b"
    r"|\b\d+\s*paying\b"
    r"|\b\d+\s*customers?\b",
    re.IGNORECASE,
)

_VALIDATION = re.compile(
    r"\b(?:beta|pilot|prototype|mvp|tested|validated|launched|surveyed|"
    r"interviewed|user research|focus group|waitlist|signups?|onboarding|"
    r"usability test|field test|user test|a/b test|experiment)\b"
    r"|\bevent.?miss reports?\b"
    r"|\bcampus ambassadors?\b",
    re.IGNORECASE,
)

_COLLEGE_CAMPUS = re.compile(
    r"\b(?:campus(?:es)?|colleges?|universities|university|iit|nit|bits|vit|"
    r"mit|stanford|oxford|ambassadors?|chapters?)\b",
    re.IGNORECASE,
)

_COMPETITORS = re.compile(
    r"\b(?:luma|lu\.ma|eventbrite|devfolio|unstop|meetup|linkedin|facebook|"
    r"whatsapp|google|notion|airtable|twitter|x\.com|slack|discord|"
    r"internshala|naukri|glassdoor|monster)\b"
    r"|\b(?:competitors?|alternatives?)\b"
    r"|\bunlike\s+\w+\b"
    r"|\bvs\.?\s+\w+\b",
    re.IGNORECASE,
)

_TECH_MECHANISM = re.compile(
    r"\b(?:embedding|vector|fine.?tun|retrieval|ranking model|cosine similarity|"
    r"recommendation engine|nlp|llm|transformer|gpt|bert|neural|classifier|"
    r"semantic search|knowledge graph|rag|inference|profile matching|"
    r"skill.based|personali[sz]ation|latency|throughput|model|algorithm|"
    r"api|webhook|scraping|crawler|pipeline)\b",
    re.IGNORECASE,
)

_REVENUE = re.compile(
    r"\b(?:revenue|mrr|arr|subscription|freemium|pay per|college pays|"
    r"sponsor pays|b2b|b2c|saas|monetize|price|pricing|charge|conversion|"
    r"cac|ltv|arpu|monthly plan|annual plan|tier|upsell|markup|margin|"
    r"transaction fee|commission|licensing|enterprise)\b",
    re.IGNORECASE,
)

_RETENTION = re.compile(
    r"\b(?:retention|churn|dau|mau|wau|weekly active|daily active|"
    r"returning users?|re.engagement|habit|repeat|sticky|lock.in|"
    r"notification|reminder|follow.?up|engagement rate)\b",
    re.IGNORECASE,
)

_GTM = re.compile(
    r"\b(?:gtm|go.to.market|acquisition|channel|referral|viral|"
    r"word.of.mouth|ambassador|campus rep|partnership|integration|"
    r"distribution|onboard|launch|rollout|phase\s*\d)\b",
    re.IGNORECASE,
)

_VAGUE_PHRASES = re.compile(
    r"\bbig market\b|\bhuge market\b|\blarge market\b"
    r"|\beveryone\b|\banybody\b"
    r"|\buseful for\b|\bhelpful for\b|\bgood for\b|\bgreat for\b"
    r"|\bai will\b|\bai can\b"
    r"|\bautomatically\b|\bseamlessly\b|\beasily\b|\bquickly\b"
    r"|\bbasically\b|\bgenerally\b|\btypically\b|\bobviously\b",
    re.IGNORECASE,
)

_NON_ANSWER_EXACT: frozenset[str] = frozenset({
    "ok", "okay", "idk", "i don't know", "dont know", "don't know",
    "not sure", "maybe", "no idea", "hmm", "i'm not sure", "im not sure",
    "i dont know", "i have no idea", "not really", "yeah", "sure",
    "fine", "alright", "whatever", "pass", "i'll think about it",
    "we'll figure it out", "good question",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_all(pattern: re.Pattern, text: str) -> list[str]:
    return [m.group(0).strip() for m in pattern.finditer(text)]


def _dedup(lst: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in lst:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _is_non_answer(text: str) -> bool:
    stripped = text.strip().lower()
    if not stripped or len(stripped.split()) < 4:
        return True
    return stripped in _NON_ANSWER_EXACT or any(
        stripped.startswith(p) for p in _NON_ANSWER_EXACT
    )


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_concrete_signals(session: dict) -> dict[str, Any]:
    """Extract evidence signals from all user turns in a session.

    Processes only user-role messages. No API calls.

    Returns:
        {
            "numbers":              list[str],   # raw number matches
            "percentages":          list[str],
            "pricing":              list[str],   # currency amounts
            "user_counts":          list[str],   # "50 beta users", etc.
            "validation":           list[str],   # tested / piloted / surveyed
            "college_mentions":     list[str],   # campus / college / IIT etc.
            "competitors":          list[str],   # named competitors
            "technical_mechanisms": list[str],   # embedding / ranking model etc.
            "revenue_signals":      list[str],   # subscription / pricing / CAC
            "retention_signals":    list[str],   # churn / DAU / retention
            "gtm_signals":          list[str],   # referral / ambassador / launch
            "non_answers":          list[str],   # evasion/non-answer turns
            "vague_claims":         list[str],   # buzzword phrases
            "best_user_quotes":     list[str],   # up to 5 most signal-dense answers
            "all_user_answers":     list[str],   # every user message
            "signal_count":         int,         # total unique signals found
        }
    """
    history = session.get("history", [])
    user_answers = [
        e["content"].strip()
        for e in history
        if e.get("role") == "user" and e.get("content", "").strip()
    ]

    all_numbers: list[str] = []
    all_pct: list[str] = []
    all_pricing: list[str] = []
    all_user_counts: list[str] = []
    all_validation: list[str] = []
    all_colleges: list[str] = []
    all_competitors: list[str] = []
    all_tech: list[str] = []
    all_revenue: list[str] = []
    all_retention: list[str] = []
    all_gtm: list[str] = []
    all_vague: list[str] = []
    non_answer_turns: list[str] = []
    answer_scores: list[tuple[int, str]] = []

    for ans in user_answers:
        if _is_non_answer(ans):
            non_answer_turns.append(ans)
            answer_scores.append((0, ans))
            continue

        nums    = _match_all(_NUMBER_METRIC, ans)
        pcts    = _match_all(_PERCENTAGE, ans)
        prices  = _match_all(_CURRENCY, ans)
        ucounts = _match_all(_USER_COUNT, ans)
        val     = _match_all(_VALIDATION, ans)
        cols    = _match_all(_COLLEGE_CAMPUS, ans)
        comps   = _match_all(_COMPETITORS, ans)
        techs   = _match_all(_TECH_MECHANISM, ans)
        revs    = _match_all(_REVENUE, ans)
        rets    = _match_all(_RETENTION, ans)
        gtms    = _match_all(_GTM, ans)
        vagues  = _match_all(_VAGUE_PHRASES, ans)

        all_numbers.extend(nums)
        all_pct.extend(pcts)
        all_pricing.extend(prices)
        all_user_counts.extend(ucounts)
        all_validation.extend(val)
        all_colleges.extend(cols)
        all_competitors.extend(comps)
        all_tech.extend(techs)
        all_revenue.extend(revs)
        all_retention.extend(rets)
        all_gtm.extend(gtms)
        all_vague.extend(vagues)

        # Signal density score for ranking quotes
        density = (
            len(nums) + len(pcts) + len(prices) + len(ucounts) +
            len(val) + len(cols) + len(comps) + len(techs) + len(revs)
        )
        answer_scores.append((density, ans))

    # Sort by density descending; take top 5 non-trivial answers
    sorted_answers = sorted(answer_scores, key=lambda x: x[0], reverse=True)
    best_quotes = [ans for score, ans in sorted_answers if score > 0][:5]

    total_signals = (
        len(_dedup(all_numbers)) + len(_dedup(all_pct)) +
        len(_dedup(all_pricing)) + len(_dedup(all_user_counts)) +
        len(_dedup(all_validation)) + len(_dedup(all_colleges)) +
        len(_dedup(all_competitors)) + len(_dedup(all_tech)) +
        len(_dedup(all_revenue))
    )

    return {
        "numbers":               _dedup(all_numbers),
        "percentages":           _dedup(all_pct),
        "pricing":               _dedup(all_pricing),
        "user_counts":           _dedup(all_user_counts),
        "validation":            _dedup(all_validation),
        "college_mentions":      _dedup(all_colleges),
        "competitors":           _dedup(all_competitors),
        "technical_mechanisms":  _dedup(all_tech),
        "revenue_signals":       _dedup(all_revenue),
        "retention_signals":     _dedup(all_retention),
        "gtm_signals":           _dedup(all_gtm),
        "non_answers":           non_answer_turns,
        "vague_claims":          _dedup(all_vague),
        "best_user_quotes":      best_quotes,
        "all_user_answers":      user_answers,
        "signal_count":          total_signals,
    }
