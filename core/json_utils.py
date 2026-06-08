"""JSON parsing utilities with safe fallbacks."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_block(text: str) -> str | None:
    """Extract the first JSON object or array block from text."""
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
    return None


def safe_json_parse(text: str, default: Any = None) -> Any:
    """Parse JSON from raw text, attempting block extraction on failure."""
    if default is None:
        default = {}

    if not text:
        return default

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        block = extract_json_block(text)
        if not block:
            return default
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            return default


def fallback_scorecard() -> dict[str, Any]:
    """Return a minimal scorecard when model JSON parsing fails."""
    return {
        "overall": 0,
        "scores": {},
        "best_answer": "No scorecard could be generated.",
        "weakest_answer": "",
        "improved_answer": "",
        "improved_pitch": "",
        "top_3_questions": [],
    }


_REQUIRED_SCORECARD_DIMS = {
    "clarity",
    "problem_understanding",
    "market_awareness",
    "differentiation",
    "business_model",
    "objection_handling",
}


def _coerce_score(value: Any) -> int:
    """Clamp a raw score value to integer 0–100."""
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 0


def _score_label(score: int) -> str:
    """Map an integer score 0–100 to a human-readable label.

    Phase 5C bands (claim-based calibration):
      0–30:   Not addressed
      31–50:  Developing
      51–70:  Solid
      71–85:  Strong
      86–100: Excellent
    """
    if score <= 30:
        return "Not addressed"
    if score <= 50:
        return "Developing"
    if score <= 70:
        return "Solid"
    if score <= 85:
        return "Strong"
    return "Excellent"


def _validate_dim(raw: Any) -> dict[str, Any]:
    """Normalise a raw score dimension into {score, label, reason, quote, signals_used}."""
    if not isinstance(raw, dict):
        return {
            "score": 0,
            "label": _score_label(0),
            "reason": "No data.",
            "quote": "",
            "signals_used": [],
        }
    score = _coerce_score(raw.get("score", 0))
    raw_signals = raw.get("signals_used", [])
    signals = (
        [str(s).strip() for s in raw_signals if str(s).strip()]
        if isinstance(raw_signals, list)
        else []
    )
    return {
        "score": score,
        "label": _score_label(score),
        "reason": str(raw.get("reason", "")).strip() or "No reasoning provided.",
        "quote": str(raw.get("quote", "")).strip(),
        "signals_used": signals[:8],
    }


def parse_scorecard_json(raw_text: str) -> dict[str, Any] | None:
    """Parse and validate Nemotron scorecard JSON.

    Fallback order:
      1. json.loads(raw_text)
      2. extract_json_block → json.loads
      3. safe_json_parse

    Returns a validated dict with all required keys, or None if parsing fails
    completely so the caller can fall back to mock_scorecard.

    Voice mode note:
      This function is input-source agnostic — it receives only the text
      output from the model and does not need to change for voice mode.
    """
    parsed = safe_json_parse(raw_text)
    if not parsed or not isinstance(parsed, dict):
        return None

    # Validate and normalise scores dict
    raw_scores = parsed.get("scores", {})
    if not isinstance(raw_scores, dict):
        raw_scores = {}

    scores: dict[str, Any] = {}
    for dim in _REQUIRED_SCORECARD_DIMS:
        scores[dim] = _validate_dim(raw_scores.get(dim))

    # overall: prefer explicit field, else average of dimension scores
    if "overall" in parsed and parsed["overall"] is not None:
        overall = _coerce_score(parsed["overall"])
    else:
        dim_scores = [scores[d]["score"] for d in _REQUIRED_SCORECARD_DIMS]
        overall = round(sum(dim_scores) / len(dim_scores)) if dim_scores else 0

    def _str(key: str, default: str = "") -> str:
        return str(parsed.get(key, default)).strip() or default

    def _list_of_str(key: str) -> list[str]:
        val = parsed.get(key, [])
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        return []

    top_3 = _list_of_str("top_3_questions")[:3]
    # Pad to 3 if model returned fewer
    while len(top_3) < 3:
        top_3.append("What concrete evidence do you have to support this claim?")

    return {
        "overall": overall,
        "overall_label": _score_label(overall),
        "scores": scores,
        "best_answer": _str("best_answer", "Not identified."),
        "weakest_answer": _str("weakest_answer", "Not identified."),
        "why_weak": _str("why_weak", ""),
        "improved_answer": _str("improved_answer", ""),
        "improved_pitch": _str("improved_pitch", ""),
        "top_3_questions": top_3,
    }
