"""Deal scorecard + combined pitch/deal summary (Phase 9D)."""

from __future__ import annotations

import logging
from typing import Any

from core.deal_claim_extractor import (
    extract_deal_signals,
    is_substantive_move,
    is_one_word_ack,
)
from core.deal_persona_builder import build_compact_deal_context
from core.judge_settings import get_scoring_calibration, normalize_difficulty
from core.json_utils import (
    parse_model_json,
    parse_json_object,
    safe_json_parse,
    extract_partial_string_fields,
    extract_partial_string_list,
    ends_abruptly,
    sanitize_for_log,
)
from core import model_router

logger = logging.getLogger(__name__)

DEAL_DIMS = (
    "anchoring",
    "evidence",
    "concession_control",
    "alternatives",
    "value_articulation",
    "closing",
)

_DIM_LABELS = {
    "anchoring": "Anchoring",
    "evidence": "Evidence",
    "concession_control": "Concession Control",
    "alternatives": "Alternatives",
    "value_articulation": "Value Articulation",
    "closing": "Closing",
}


def _deal_score_label(score: int) -> str:
    if score >= 80:
        return "Strong"
    if score >= 60:
        return "Solid"
    if score >= 40:
        return "Developing"
    return "Weak"


def _clamp(n: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, n))


def _dim_entry(score: int, reason: str, quote: str = "") -> dict[str, Any]:
    return {
        "score": _clamp(score),
        "label": _deal_score_label(score),
        "reason": reason[:280],
        "quote": quote[:200],
    }


def _best_user_quote(deal_history: list[dict]) -> str:
    users = [h.get("message", "") for h in deal_history if h.get("role") == "user"]
    if not users:
        return ""
    return max(users, key=lambda t: len(t.split()))[:200]


def _weakest_user_quote(deal_history: list[dict], signals: dict) -> str:
    users = [h.get("message", "") for h in deal_history if h.get("role") == "user"]
    if not users:
        return ""
    if signals.get("weak_concession_signals"):
        for u in users:
            if any(w.lower() in u.lower() for w in signals["weak_concession_signals"]):
                return u[:200]
    return min(users, key=lambda t: len(t.split()))[:200]


def _move_signal_strength(message: str) -> int:
    """Rank a single founder message by how much negotiation substance it carries."""
    s = extract_deal_signals([{"role": "user", "message": message}])
    score = 0
    if s["evidence_signals"]:
        score += 2
    if s["specific_numbers"]:
        score += 2
    if s["counteroffers"] or s["tradeoffs"]:
        score += 2
    if s["anchor_points"]:
        score += 1
    if s["closing_signals"]:
        score += 1
    if s["alternative_signals"]:
        score += 1
    return score


def select_best_and_weakest_deal_moves(
    deal_history: list[dict],
    scores: dict,
    signals: dict,
) -> dict[str, str]:
    """Pick best/weakest founder moves from SUBSTANTIVE messages only.

    One-word acknowledgements ("sure", "ok", "yes", "fine") are never eligible as the
    weakest move unless they actually conceded a term. Returns human-readable sentences,
    never a bare quote, so the scorecard explains the move rather than dumping a word.
    """
    users = [str(h.get("message", "")).strip() for h in deal_history if h.get("role") == "user"]
    substantive = [u for u in users if is_substantive_move(u)]

    if not substantive:
        return {
            "best_move": "No substantive negotiation move was recorded.",
            "weakest_move": "No real counters were made — every reply was a bare acknowledgement.",
            "best_quote": "",
            "weakest_quote": "",
        }

    best_quote = max(substantive, key=_move_signal_strength)
    if _move_signal_strength(best_quote) == 0:
        best_quote = max(substantive, key=lambda t: len(t.split()))

    # Weakest: prefer a substantive message that conceded without extracting anything.
    weak_quote = ""
    for u in substantive:
        s = extract_deal_signals([{"role": "user", "message": u}])
        if s["weak_concession_signals"] and not (s["counteroffers"] or s["tradeoffs"]):
            weak_quote = u
            break
    if not weak_quote:
        candidates = [u for u in substantive if u != best_quote]
        if candidates:
            low = min(candidates, key=_move_signal_strength)
            if _move_signal_strength(low) <= 1:
                weak_quote = low

    best_move = f'Your strongest moment: "{best_quote[:200]}"'
    if weak_quote:
        weakest_move = (
            f'Watch this moment: "{weak_quote[:200]}" — you gave ground without '
            "anchoring a counter or extracting a tradeoff."
        )
    else:
        weakest_move = (
            "No major single weak move detected; the main weakness was that "
            "alternatives and leverage were underdeveloped."
        )

    return {
        "best_move": best_move,
        "weakest_move": weakest_move,
        "best_quote": best_quote,
        "weakest_quote": weak_quote,
    }


def calculate_deal_dimension_scores(
    deal_signals: dict,
    deal_history: list[dict],
    deal_context: dict,
    difficulty_profile: str,
) -> dict[str, dict[str, Any]]:
    """Local rule-based deal dimension scores."""
    cal = get_scoring_calibration(difficulty_profile)
    floor = cal.get("attempted_answer_floor", 33)
    user_turns = deal_signals.get("user_turns", 0)
    best_q = _best_user_quote(deal_history)
    weak_q = _weakest_user_quote(deal_history, deal_signals)

    if user_turns == 0:
        empty = _dim_entry(0, "No deal counters were submitted.", "")
        return {d: dict(empty) for d in DEAL_DIMS}

    anchors = deal_signals.get("anchor_points", [])
    numbers = deal_signals.get("specific_numbers", [])
    evidence = deal_signals.get("evidence_signals", [])
    weak_con = deal_signals.get("weak_concession_signals", [])
    concessions = deal_signals.get("concession_signals", [])
    alts = deal_signals.get("alternative_signals", [])
    value = deal_signals.get("value_signals", [])
    closing = deal_signals.get("closing_signals", [])
    counters = deal_signals.get("counteroffers", [])
    tradeoffs = deal_signals.get("tradeoffs", [])

    # Anchoring — repeated clear counters should not cap low.
    anchoring_score = floor
    if anchors and counters:
        anchoring_score = 78 if len(counters) >= 2 else 72
    elif anchors or counters:
        anchoring_score = 60
    elif numbers:
        anchoring_score = 50

    evidence_score = floor
    if evidence and numbers:
        evidence_score = 74
    elif evidence or numbers:
        evidence_score = 56

    # Concession control — reward trading concessions for conditions; only punish a
    # bare giveaway with no counter/tradeoff. A harmless "sure" never lands here.
    concession_score = 52
    if weak_con and not (counters or tradeoffs):
        concession_score = 32
    elif tradeoffs and not weak_con:
        concession_score = 76
    elif concessions and counters:
        concession_score = 70
    elif concessions or tradeoffs:
        concession_score = 60

    # Alternatives — credit implied leverage/options, not just exact BATNA wording.
    alt_score = 38
    if alts and (numbers or tradeoffs):
        alt_score = 76
    elif alts:
        alt_score = 66

    value_score = floor
    if value and numbers:
        value_score = 72
    elif value:
        value_score = 56

    closing_score = 32
    if closing and counters:
        closing_score = 76
    elif closing:
        closing_score = 66
    elif user_turns >= 3 and counters:
        closing_score = 50

    raw = {
        "anchoring": anchoring_score,
        "evidence": evidence_score,
        "concession_control": concession_score,
        "alternatives": alt_score,
        "value_articulation": value_score,
        "closing": closing_score,
    }
    # Synergy: a well-rounded negotiation (≥5 dimensions already solid) earns a small
    # lift so a genuinely strong founder can crest into the 80s instead of capping low.
    if sum(1 for v in raw.values() if v >= 60) >= 5:
        raw = {k: _clamp(v + 6) for k, v in raw.items()}
    anchoring_score = raw["anchoring"]
    evidence_score = raw["evidence"]
    concession_score = raw["concession_control"]
    alt_score = raw["alternatives"]
    value_score = raw["value_articulation"]
    closing_score = raw["closing"]

    return {
        "anchoring": _dim_entry(
            anchoring_score,
            "Clear term anchors and counteroffers strengthen your position."
            if anchors else "Terms were not anchored with specific numbers or structure.",
            best_q,
        ),
        "evidence": _dim_entry(
            evidence_score,
            "Evidence-backed counters build credibility."
            if evidence else "Deal counters lacked proof points from traction or pilots.",
            best_q,
        ),
        "concession_control": _dim_entry(
            concession_score,
            "You gave up too much too fast."
            if weak_con else "Concession pacing was acceptable for this stage.",
            weak_q or best_q,
        ),
        "alternatives": _dim_entry(
            alt_score,
            "BATNA or alternatives mentioned." if alts else "No alternatives or leverage cited.",
            best_q,
        ),
        "value_articulation": _dim_entry(
            value_score,
            "Value and ROI were articulated." if value else "Fair value and ROI were under-explained.",
            best_q,
        ),
        "closing": _dim_entry(
            closing_score,
            "Closing signals present." if closing else "No concrete closing step proposed.",
            best_q,
        ),
    }


def determine_deal_outcome(scores: dict, deal_history: list[dict], signals: dict) -> str:
    """Return deal outcome label."""
    s = {k: int(v.get("score", 0)) for k, v in scores.items()}
    user_turns = signals.get("user_turns", 0)
    if user_turns == 0:
        return "no_deal"

    if signals.get("weak_concession_signals") and s["concession_control"] < 40:
        return "weak_concession"

    if (
        s["anchoring"] >= 65
        and s["evidence"] >= 60
        and s["concession_control"] >= 55
        and s["closing"] >= 55
    ):
        return "strong_win"

    if s["closing"] >= 50 and s["value_articulation"] >= 50:
        return "favorable_partial"

    if s["concession_control"] >= 45 and s["anchoring"] >= 45:
        return "balanced"

    if s["closing"] < 35 and s["value_articulation"] < 40:
        return "no_deal"

    return "balanced"


_DEAL_OUTCOME_LABELS = frozenset({
    "strong_win", "favorable_partial", "balanced", "weak_concession", "no_deal",
})


def _is_human_deal_summary(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) < 25:
        return False
    normalized = t.lower().replace(" ", "_").replace("-", "_")
    if normalized in _DEAL_OUTCOME_LABELS:
        return False
    return not ends_abruptly(t)


_OUTCOME_SUMMARIES = {
    "strong_win": "You held your position with evidence and moved toward concrete terms.",
    "favorable_partial": "You negotiated acceptably but left some value on the table.",
    "balanced": "A mixed negotiation — some strong counters alongside a few gaps.",
    "weak_concession": "You conceded too quickly without extracting tradeoffs in return.",
    "no_deal": "No closing path emerged — terms were not defended strongly enough.",
}


def humanize_deal_outcome(outcome: str) -> str:
    """Return a human-readable sentence for a deal outcome label."""
    return _OUTCOME_SUMMARIES.get(outcome, _OUTCOME_SUMMARIES["balanced"])


# ---------------------------------------------------------------------------
# Nemotron semantic scoring (Call 1) — primary judge for the 6 deal dimensions
# ---------------------------------------------------------------------------

_DEAL_SCORING_SCHEMA = (
    '{"scores":{'
    '"anchoring":{"score":0,"reason":"","quote":""},'
    '"evidence":{"score":0,"reason":"","quote":""},'
    '"concession_control":{"score":0,"reason":"","quote":""},'
    '"alternatives":{"score":0,"reason":"","quote":""},'
    '"value_articulation":{"score":0,"reason":"","quote":""},'
    '"closing":{"score":0,"reason":"","quote":""}},'
    '"deal_outcome":"strong_win|favorable_partial|balanced|weak_concession|no_deal",'
    '"best_move":"","weakest_move":""}'
)


def _build_deal_scoring_prompt(
    session: dict,
    signals: dict,
    local_scores: dict,
) -> list[dict[str, str]]:
    """Build the scoring-only messages for Nemotron (compact context, full founder turns)."""
    ctx = build_compact_deal_context(session)
    deal_history = session.get("deal_history") or []

    # Full founder turns (these are what we score); judge turns truncated for context.
    transcript_lines: list[str] = []
    for h in deal_history:
        role = "FOUNDER" if h.get("role") == "user" else "JUDGE"
        msg = str(h.get("message", "")).strip()
        if not msg:
            continue
        if role == "FOUNDER":
            transcript_lines.append(f"FOUNDER: {msg[:400]}")
        else:
            transcript_lines.append(f"JUDGE: {msg[:160]}")
    transcript = "\n".join(transcript_lines[-14:])

    hints = (
        f"anchors={signals.get('anchor_points', [])[:4]} "
        f"numbers={signals.get('specific_numbers', [])[:4]} "
        f"evidence={signals.get('evidence_signals', [])[:4]} "
        f"alternatives={signals.get('alternative_signals', [])[:4]} "
        f"tradeoffs={signals.get('tradeoffs', [])[:4]} "
        f"closing={signals.get('closing_signals', [])[:4]}"
    )

    system = (
        "You are an experienced startup negotiation judge scoring a founder's DEAL "
        "negotiation. Score SEMANTICALLY based on what the founder actually argued — "
        "not on keyword matching. Return ONLY one JSON object. First character {, last }. "
        "No markdown. No reasoning. No array.\n\n"
        "Score each of 6 dimensions 0-100:\n"
        "  anchoring — did they anchor specific terms/numbers and hold a clear position?\n"
        "  evidence — did they back terms with proof (traction, pilots, metrics)?\n"
        "  concession_control — did they trade concessions for conditions, or give ground freely?\n"
        "  alternatives — did they show leverage/options? Credit this even when phrased "
        "naturally ('we're also talking to other partners', 'we're not dependent on this') "
        "without the word BATNA.\n"
        "  value_articulation — did they explain ROI / why the terms are fair?\n"
        "  closing — did they push toward a concrete next step or commitment?\n\n"
        "Scoring rules:\n"
        "- Do NOT punish a harmless one-word acknowledgement like 'sure' or 'ok' unless it "
        "clearly conceded a term.\n"
        "- Pick weakest_move from a SUBSTANTIVE negotiation moment, never the shortest message.\n"
        "- Allow 80+ when the founder anchors, proves, keeps concession control, shows "
        "alternatives, articulates value, and closes.\n"
        "- Do not over-score vague confidence with no specifics.\n"
        "- quote must be copied from an actual FOUNDER message. Do not invent quotes.\n"
        "- Each reason: one short sentence.\n\n"
        f"REQUIRED JSON SCHEMA:\n{_DEAL_SCORING_SCHEMA}"
    )

    user = (
        f"Deal type: {ctx.get('deal_type_label', '')}\n"
        f"Founder ask: {ctx.get('ask', '')}\n"
        f"Judge opening offer: {ctx.get('opening_offer', '')}\n"
        f"Local signal hints (reference only, may be incomplete): {hints}\n"
        f"Local reference scores (do not just copy — judge for yourself): "
        f"{ {k: v.get('score') for k, v in local_scores.items()} }\n\n"
        f"NEGOTIATION TRANSCRIPT:\n{transcript}\n\n"
        "Score the 6 dimensions now. Output the JSON object only."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_deal_scores(parsed: Any) -> dict[str, Any]:
    """Locate the 6-dimension scores dict, tolerant of model JSON shape.

    The model sometimes nests scores under "scores" and sometimes (after lossy JSON
    extraction) the dimensions land at the root. Handle both so a valid scorecard is
    never thrown away over a wrapper key.
    """
    if not isinstance(parsed, dict):
        return {}
    raw = parsed.get("scores")
    if isinstance(raw, dict) and any(d in raw for d in DEAL_DIMS):
        return raw
    if any(d in parsed for d in DEAL_DIMS):
        return {d: parsed[d] for d in DEAL_DIMS if d in parsed}
    return {}


def _validate_deal_scoring(parsed: Any) -> bool:
    """True if all 6 dims have a numeric score AND the scores are not all zero.

    Rejecting an all-zero result is deliberate: it filters out the empty repair
    skeleton (every score 0) so we fall back to local scoring instead of emitting a
    bogus overall of 0 for a real negotiation.
    """
    scores = _extract_deal_scores(parsed)
    if not scores:
        return False
    total = 0.0
    for dim in DEAL_DIMS:
        entry = scores.get(dim)
        if not isinstance(entry, dict):
            return False
        try:
            total += float(entry.get("score"))
        except (TypeError, ValueError):
            return False
    return total > 0


def _normalize_deal_scoring(
    parsed: dict,
    deal_history: list[dict],
    signals: dict,
) -> dict[str, Any]:
    """Clamp scores, attach labels, validate outcome, and resolve best/weakest moves."""
    raw = _extract_deal_scores(parsed)
    scores: dict[str, dict[str, Any]] = {}
    for dim in DEAL_DIMS:
        entry = raw.get(dim, {}) if isinstance(raw.get(dim), dict) else {}
        try:
            val = int(round(float(entry.get("score", 0))))
        except (TypeError, ValueError):
            val = 0
        reason = str(entry.get("reason", "")).strip() or "Judged from the negotiation transcript."
        quote = str(entry.get("quote", "")).strip()
        scores[dim] = _dim_entry(val, reason, quote)

    outcome = str(parsed.get("deal_outcome", "")).strip().lower().replace(" ", "_")
    if outcome not in _DEAL_OUTCOME_LABELS:
        outcome = determine_deal_outcome(scores, deal_history, signals)

    # Best/weakest: trust the model only if its text is substantive; else derive locally.
    local_moves = select_best_and_weakest_deal_moves(deal_history, scores, signals)
    best_move = str(parsed.get("best_move", "")).strip()
    weakest_move = str(parsed.get("weakest_move", "")).strip()
    if len(best_move) < 12 or is_one_word_ack(best_move):
        best_move = local_moves["best_move"]
    if len(weakest_move) < 12 or is_one_word_ack(weakest_move):
        weakest_move = local_moves["weakest_move"]

    overall = round(sum(s["score"] for s in scores.values()) / len(scores))
    return {
        "scores": scores,
        "deal_outcome": outcome,
        "best_move": best_move[:300],
        "weakest_move": weakest_move[:300],
        "overall": overall,
        "overall_label": _deal_score_label(overall),
    }


def call_nemotron_deal_scoring(
    session: dict,
    signals: dict,
    local_scorecard: dict,
) -> dict[str, Any] | None:
    """Call 1 — Nemotron semantic scoring. Returns normalized scores or None on failure."""
    messages = _build_deal_scoring_prompt(session, signals, local_scorecard.get("scores", {}))
    model_mode = session.get("model_mode", "premium_nvidia")
    result = model_router.generate_deal_scoring_response(messages, model_mode=model_mode)

    if not result.get("ok") or not result.get("content"):
        logger.warning("deal_scoring: Nemotron scoring call failed — %s", result.get("error"))
        return None

    parsed = safe_json_parse(result["content"])
    if not _validate_deal_scoring(parsed):
        logger.warning(
            "deal_scoring: scoring JSON invalid, trying repair preview=%r",
            sanitize_for_log(result["content"]),
        )
        repair = model_router.generate_deal_scoring_repair_response(
            result["content"], model_mode=model_mode
        )
        if repair.get("ok") and repair.get("content"):
            parsed = safe_json_parse(repair["content"])

    if not _validate_deal_scoring(parsed):
        logger.warning("deal_scoring: scoring fallback used — Nemotron scores unavailable")
        return None

    return _normalize_deal_scoring(parsed, session.get("deal_history", []), signals)


def _parse_deal_coaching_json(raw: str) -> dict[str, Any]:
    """Best-effort parse of deal coaching JSON."""
    parsed = parse_json_object(
        raw,
        string_fields=[
            "deal_outcome_summary", "best_move", "weakest_move",
            "improved_response", "combined_summary", "next_best_action",
        ],
    )
    if not parsed:
        parsed = extract_partial_string_fields(raw, [
            "deal_outcome_summary", "best_move", "weakest_move",
            "improved_response", "combined_summary", "next_best_action",
        ])

    result: dict[str, Any] = {}
    for key in (
        "deal_outcome_summary", "best_move", "weakest_move",
        "improved_response", "combined_summary", "next_best_action",
    ):
        val = str(parsed.get(key, "")).strip()
        if not val:
            continue
        if key == "deal_outcome_summary" and not _is_human_deal_summary(val):
            continue
        if ends_abruptly(val) and key in ("best_move", "weakest_move", "next_best_action"):
            continue
        if ends_abruptly(val) and key == "improved_response" and len(val) < 40:
            continue
        result[key] = val

    q3 = parsed.get("top_3_prep_points")
    if not isinstance(q3, list) or len(q3) < 3:
        q3 = extract_partial_string_list(raw, "top_3_prep_points", min_items=3)
    if isinstance(q3, list):
        items = [str(q).strip() for q in q3 if str(q).strip() and not ends_abruptly(str(q))]
        if items:
            result["top_3_prep_points"] = items[:3]
    return result


def _merge_deal_coaching(local: dict[str, Any], nemotron: dict[str, Any]) -> tuple[dict[str, Any], str]:
    merged = dict(local)
    hits = 0
    for key in (
        "deal_outcome_summary", "best_move", "weakest_move",
        "improved_response", "combined_summary", "next_best_action",
    ):
        val = str(nemotron.get(key, "")).strip()
        if val:
            merged[key] = val[:400 if key == "improved_response" else 300]
            hits += 1
    n_q = nemotron.get("top_3_prep_points")
    if isinstance(n_q, list) and len(n_q) >= 3:
        merged["top_3_prep_points"] = [str(q).strip() for q in n_q[:3]]
        hits += 1
    if hits >= 5:
        return merged, "nemotron"
    if hits > 0:
        return merged, "partial_nemotron_local"
    return merged, "local"


def build_local_deal_coaching(
    session: dict,
    scores: dict,
    signals: dict,
    outcome: str,
) -> dict[str, Any]:
    """Local coaching text when Nemotron unavailable."""
    deal_context = session.get("deal_context") or {}
    moves = select_best_and_weakest_deal_moves(
        session.get("deal_history", []), scores, signals
    )
    weakest_dim = min(scores.items(), key=lambda x: x[1]["score"])[0]

    return {
        "deal_outcome_summary": humanize_deal_outcome(outcome),
        "best_move": moves["best_move"],
        "weakest_move": moves["weakest_move"],
        "improved_response": (
            f"A stronger {weakest_dim.replace('_', ' ')} counter would anchor specific terms, "
            "cite one proof point, and propose a tradeoff instead of conceding."
        ),
        "top_3_prep_points": [
            "Anchor every counter with a specific number or term.",
            "Cite one pilot metric before conceding on price or equity.",
            "Always propose a tradeoff — never concede without getting something back.",
        ],
        "combined_summary": "",
        "next_best_action": f"Practice {weakest_dim.replace('_', ' ')} in your next deal drill.",
    }


def call_nemotron_deal_coaching(
    session: dict,
    local_scorecard: dict,
    signals: dict,
) -> dict[str, Any] | None:
    """Nemotron coaching for deal scorecard."""
    deal_context = session.get("deal_context") or {}
    history_text = "\n".join(
        f"{h.get('role', '').upper()}: {h.get('message', '')[:200]}"
        for h in (session.get("deal_history") or [])[-12:]
    )

    system = (
        "You are a startup negotiation coach. Return ONLY valid JSON.\n"
        "Return one JSON object only. First character must be {. Last character must be }.\n"
        "No markdown. No reasoning. No array wrapper.\n"
        "Keep each field short and complete. Do not end mid-sentence.\n"
        "Use only provided deal history and signals. Do not hallucinate terms reached.\n"
        "deal_outcome_summary must be a human-readable explanation (2 sentences max), "
        "NOT a label like weak_concession or strong_win.\n\n"
        "FIELD LIMITS:\n"
        "  deal_outcome_summary: 2 sentences max\n"
        "  best_move: 1 sentence\n"
        "  weakest_move: 1 sentence\n"
        "  improved_response: 3-5 sentences\n"
        "  each top_3_prep_points item: 1 sentence\n"
        "  combined_summary: 2 sentences max\n"
        "  next_best_action: 1 sentence\n\n"
        "REQUIRED JSON:\n"
        '{"deal_outcome_summary":"","best_move":"","weakest_move":"",'
        '"improved_response":"","top_3_prep_points":["","",""],'
        '"combined_summary":"","next_best_action":""}'
    )

    user = (
        f"Deal type: {deal_context.get('deal_type', '')}\n"
        f"Deal outcome: {local_scorecard.get('deal_outcome', '')}\n"
        f"Overall deal score: {local_scorecard.get('overall', 0)}\n"
        f"Dimension scores: {local_scorecard.get('scores', {})}\n"
        f"Signals: {signals}\n\n"
        f"Deal history:\n{history_text}\n"
    )

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    model_mode = session.get("model_mode", "premium_nvidia")
    result = model_router.generate_deal_scorecard_coaching_response(messages, model_mode=model_mode)

    if not result.get("ok") or not result.get("content"):
        return None

    raw = result["content"]
    local_coaching = build_local_deal_coaching(
        session,
        local_scorecard.get("scores", {}),
        signals,
        local_scorecard.get("deal_outcome", "balanced"),
    )
    nemotron = _parse_deal_coaching_json(raw)
    if not nemotron.get("deal_outcome_summary"):
        logger.warning("deal_scoring: coaching parse failed, trying repair preview=%r", sanitize_for_log(raw))
        repair = model_router.generate_deal_scorecard_repair_response(raw, model_mode=model_mode)
        if repair.get("ok") and repair.get("content"):
            repaired = _parse_deal_coaching_json(repair["content"])
            for k, v in repaired.items():
                if v and not nemotron.get(k):
                    nemotron[k] = v

    merged, coaching_source = _merge_deal_coaching(local_coaching, nemotron)
    if coaching_source == "local":
        logger.warning("deal_scoring: coaching using local fallback preview=%r", sanitize_for_log(raw))
        return None

    q3 = list(merged.get("top_3_prep_points") or local_coaching["top_3_prep_points"])
    while len(q3) < 3:
        q3.append("Anchor terms with specific numbers.")
    merged["top_3_prep_points"] = q3[:3]
    merged["coaching_source"] = coaching_source
    return merged


def build_combined_scorecard(
    session: dict,
    pitch_scorecard: dict,
    deal_scorecard: dict,
    coaching: dict | None = None,
) -> dict[str, Any]:
    """Build combined pitch + deal summary."""
    pitch_overall = int(pitch_scorecard.get("overall", 0) or 0)
    deal_overall = int(deal_scorecard.get("overall", 0) or 0)
    combined = round(pitch_overall * 0.6 + deal_overall * 0.4)

    if pitch_overall >= 70 and deal_overall >= 70:
        profile = "Strong pitcher, strong negotiator"
    elif pitch_overall >= 65 and deal_overall < 55:
        profile = "Strong pitcher, developing negotiator"
    elif pitch_overall < 55 and deal_overall >= 65:
        profile = "Developing pitcher, strong negotiator"
    elif pitch_overall >= 50 and deal_overall >= 50:
        profile = "Promising founder, needs sharper proof and negotiation control"
    else:
        profile = "Early-stage founder, needs stronger fundamentals before investor conversations"

    if combined >= 80:
        combined_label = "Strong"
    elif combined >= 60:
        combined_label = "Solid"
    elif combined >= 40:
        combined_label = "Developing"
    else:
        combined_label = "Weak"

    coaching = coaching or {}
    summary = coaching.get("combined_summary") or (
        f"Pitch scored {pitch_overall}/100; deal negotiation scored {deal_overall}/100. "
        f"Combined read: {profile}."
    )

    return {
        "pitch_overall": pitch_overall,
        "deal_overall": deal_overall,
        "combined_overall": combined,
        "combined_label": combined_label,
        "founder_profile": profile,
        "summary": summary[:500],
        "next_best_action": coaching.get(
            "next_best_action",
            "Practice anchoring terms before your next investor conversation.",
        )[:200],
    }


def build_local_deal_scorecard(session: dict, deal_signals: dict) -> dict[str, Any]:
    """Full local deal scorecard without Nemotron."""
    difficulty = session.get("difficulty_profile") or normalize_difficulty(
        session.get("difficulty", "practice")
    )
    deal_context = session.get("deal_context") or {}
    deal_history = session.get("deal_history") or []

    scores = calculate_deal_dimension_scores(
        deal_signals, deal_history, deal_context, difficulty
    )
    outcome = determine_deal_outcome(scores, deal_history, deal_signals)
    overall = round(sum(s["score"] for s in scores.values()) / len(scores))

    coaching = build_local_deal_coaching(session, scores, deal_signals, outcome)

    return {
        "overall": overall,
        "overall_label": _deal_score_label(overall),
        "deal_outcome": outcome,
        "scores": scores,
        "deal_outcome_summary": coaching["deal_outcome_summary"],
        "best_move": coaching["best_move"],
        "weakest_move": coaching["weakest_move"],
        "improved_response": coaching["improved_response"],
        "top_3_prep_points": coaching["top_3_prep_points"],
        "concrete_signals_summary": {
            "anchor_points": deal_signals.get("anchor_points", [])[:5],
            "evidence_signals": deal_signals.get("evidence_signals", [])[:5],
            "specific_numbers": deal_signals.get("specific_numbers", [])[:5],
            "closing_signals": deal_signals.get("closing_signals", [])[:5],
        },
        "scorecard_source": "hybrid_deal_local",
        "provider": "local",
        "model_ok": False,
    }


def build_negotiation_transcript(session: dict) -> list[dict[str, Any]]:
    """Structured transcript for the 'View Negotiation Conversation' UI."""
    transcript: list[dict[str, Any]] = []
    for h in session.get("deal_history", []) or []:
        transcript.append({
            "round": h.get("round"),
            "role": "judge" if h.get("role") == "judge" else "founder",
            "message": str(h.get("message", "")),
            "negotiation_tag": h.get("negotiation_tag", ""),
            "answer_quality": h.get("answer_quality", ""),
            "action": h.get("action", ""),
            "input_mode": h.get("input_mode", "") or "text",
        })
    return transcript


def generate_deal_scorecard(session: dict) -> dict[str, Any]:
    """Generate deal scorecard + combined summary using a split Nemotron call.

    Call 1 (deal_scorecard_scoring) is the PRIMARY judge for the 6 dimension scores and
    determines scorecard_source. Call 2 (deal_scorecard_coaching) only adds coaching text;
    its failure falls back to local coaching but never downgrades scorecard_source.
    """
    if not session.get("deal_phase_active") and not session.get("deal_history"):
        return {"error": "No deal phase found. Complete a deal negotiation first."}

    session["deal_phase_active"] = False

    deal_signals = extract_deal_signals(
        session.get("deal_history", []),
        session.get("deal_context"),
    )

    # Local scorecard: reference context for the model + safety fallback.
    scorecard = build_local_deal_scorecard(session, deal_signals)

    # --- Call 1: Nemotron semantic scoring (determines scorecard_source) ---
    nem_scoring = call_nemotron_deal_scoring(session, deal_signals, scorecard)
    if nem_scoring is not None:
        scorecard["scores"] = nem_scoring["scores"]
        scorecard["overall"] = nem_scoring["overall"]
        scorecard["overall_label"] = nem_scoring["overall_label"]
        scorecard["deal_outcome"] = nem_scoring["deal_outcome"]
        scorecard["best_move"] = nem_scoring["best_move"]
        scorecard["weakest_move"] = nem_scoring["weakest_move"]
        scorecard["deal_outcome_summary"] = humanize_deal_outcome(nem_scoring["deal_outcome"])
        scorecard["scorecard_source"] = "nemotron_full"
        scorecard["provider"] = "nvidia"
        scorecard["model_ok"] = True
    else:
        scorecard["scorecard_source"] = "hybrid_deal_local"
        scorecard["provider"] = "local"
        scorecard["model_ok"] = False
        scorecard["model_error"] = "Nemotron deal scoring failed; used local scoring fallback."

    # --- Call 2: Nemotron coaching text (non-fatal; never downgrades source) ---
    coaching = call_nemotron_deal_coaching(session, scorecard, deal_signals)
    if coaching:
        if coaching.get("deal_outcome_summary"):
            scorecard["deal_outcome_summary"] = coaching["deal_outcome_summary"]
        scorecard["improved_response"] = coaching.get("improved_response", scorecard["improved_response"])
        scorecard["top_3_prep_points"] = coaching.get("top_3_prep_points", scorecard["top_3_prep_points"])
        # Only adopt the model's move text if it is substantive and we don't already
        # have a semantic-scoring move (scoring-path moves are preferred).
        if nem_scoring is None:
            if coaching.get("best_move") and not is_one_word_ack(coaching["best_move"]):
                scorecard["best_move"] = coaching["best_move"]
            if coaching.get("weakest_move") and not is_one_word_ack(coaching["weakest_move"]):
                scorecard["weakest_move"] = coaching["weakest_move"]
        scorecard["coaching_source"] = coaching.get("coaching_source", "nemotron")
    else:
        coaching = build_local_deal_coaching(
            session, scorecard["scores"], deal_signals, scorecard["deal_outcome"]
        )
        scorecard["coaching_source"] = "local"

    pitch_scorecard = session.get("latest_scorecard") or {}
    combined = build_combined_scorecard(session, pitch_scorecard, scorecard, coaching)

    transcript = build_negotiation_transcript(session)
    session["deal_scorecard"] = scorecard
    session["combined_scorecard"] = combined

    return {
        "session_id": session.get("session_id", ""),
        "deal_scorecard": scorecard,
        "combined_scorecard": combined,
        "negotiation_transcript": transcript,
    }
