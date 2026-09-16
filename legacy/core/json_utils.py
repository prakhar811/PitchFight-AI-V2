"""JSON parsing utilities with safe fallbacks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences and trim surrounding whitespace."""
    if not text:
        return ""
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    # Strip lone opening/closing fence lines
    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _balanced_blocks(text: str, opener: str, closer: str) -> list[str]:
    """Return all balanced opener/closer blocks found in text."""
    blocks: list[str] = []
    for start in range(len(text)):
        if text[start] != opener:
            continue
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    blocks.append(text[start : index + 1])
                    break
    return blocks


def extract_largest_json_object(text: str) -> str | None:
    """Extract the largest parseable JSON object from mixed model output."""
    if not text:
        return None

    cleaned = strip_markdown_fences(text)
    candidates = _balanced_blocks(cleaned, "{", "}")
    if not candidates:
        return None

    # Prefer the largest block that parses cleanly
    for block in sorted(candidates, key=len, reverse=True):
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict):
                return block
        except json.JSONDecodeError:
            continue

    # Fall back to largest balanced block even if not yet parseable
    return max(candidates, key=len)


def extract_json_block(text: str) -> str | None:
    """Extract the largest JSON object block from text (legacy name, improved behavior)."""
    if not text:
        return None
    return extract_largest_json_object(text)


def sanitize_for_log(text: str, limit: int = 200) -> str:
    """Return a safe preview string for debug logs (no secrets, truncated)."""
    preview = strip_markdown_fences(text or "")
    preview = re.sub(r"\s+", " ", preview).strip()
    return preview[:limit]


def safe_json_parse(text: str, default: Any = None) -> Any:
    """Parse JSON from raw text, attempting block extraction on failure."""
    if default is None:
        default = {}

    if not text:
        return default

    cleaned = strip_markdown_fences(text)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    block = extract_largest_json_object(cleaned)
    if not block:
        return default
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return default


def ends_abruptly(text: str) -> bool:
    """Return True if text looks cut off mid-sentence."""
    t = (text or "").strip()
    if not t:
        return True
    if t[-1] in ".!?":
        return False
    if len(t) < 50:
        return True
    last_word = t.split()[-1] if t.split() else ""
    return len(last_word) <= 2 and len(t) < 80


def normalize_parsed_root(parsed: Any) -> dict[str, Any] | None:
    """Unwrap array-wrapped or nested model JSON into a single object."""
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and item:
                return item
    return None


def extract_partial_string_fields(text: str, keys: list[str]) -> dict[str, str]:
    """Best-effort regex extraction of string fields from truncated JSON."""
    if not text:
        return {}
    cleaned = strip_markdown_fences(text)
    found: dict[str, str] = {}
    for key in keys:
        pattern = rf'"{re.escape(key)}"\s*:\s*"((?:[^"\\]|\\.)*)"'
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            try:
                found[key] = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                found[key] = match.group(1).replace('\\"', '"').strip()
    return found


def extract_partial_string_list(text: str, key: str, min_items: int = 1) -> list[str]:
    """Extract a JSON string array field from truncated output."""
    if not text:
        return []
    cleaned = strip_markdown_fences(text)
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[([\s\S]*?)\]', cleaned)
    if not match:
        return []
    items: list[str] = []
    for item_match in re.finditer(r'"((?:[^"\\]|\\.)*)"', match.group(1)):
        try:
            items.append(json.loads(f'"{item_match.group(1)}"'))
        except json.JSONDecodeError:
            items.append(item_match.group(1).replace('\\"', '"').strip())
    return [i for i in items if i][:max(min_items, 8)]


def parse_json_object(
    text: str,
    reasoning_fallback: str | None = None,
    string_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Parse model output into a dict using multiple extraction strategies."""
    parsed, _ = parse_model_json(text, reasoning_fallback=reasoning_fallback)
    root = normalize_parsed_root(parsed)
    if root:
        return root

    partial = extract_partial_string_fields(text, string_fields or [])
    if partial:
        return partial

    fallback = safe_json_parse(text)
    root = normalize_parsed_root(fallback)
    return root if root else {}


def parse_model_json(
    text: str,
    reasoning_fallback: str | None = None,
) -> tuple[Any, bool]:
    """Parse model JSON output with extraction fallbacks.

    Returns (parsed_value, repair_needed).
    repair_needed is True when direct parse failed and extraction/reasoning was used.
    """
    default: dict[str, Any] = {}
    if not text and not reasoning_fallback:
        return default, False

    content = strip_markdown_fences(text or "")
    repair_needed = False

    if content:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed, False
            if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0], True
            if isinstance(parsed, list):
                return parsed, True
        except json.JSONDecodeError:
            repair_needed = True

        block = extract_largest_json_object(content)
        if block:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, (dict, list)):
                    return parsed, repair_needed
            except json.JSONDecodeError:
                pass

    if reasoning_fallback:
        fb = strip_markdown_fences(reasoning_fallback)
        block = extract_largest_json_object(fb)
        if block:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, (dict, list)):
                    logger.info(
                        "json_utils: parsed JSON from reasoning_content fallback (len=%d)",
                        len(fb),
                    )
                    return parsed, True
            except json.JSONDecodeError:
                pass

    return default, True


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
