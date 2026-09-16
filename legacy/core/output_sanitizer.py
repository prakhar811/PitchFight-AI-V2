"""Sanitizer for Nemotron judge output to remove instruction leakage."""

from __future__ import annotations

import re

_LEAKAGE_PATTERNS = [
    r"we need to\b",
    r"the prompt says\b",
    r"the instruction says\b",
    r"as instructed\b",
    r"my instructions\b",
    r"according to my system prompt\b",
    r"according to the system prompt\b",
    r"i am supposed to\b",
    r"i should follow\b",
    r"the rules say\b",
    r"let'?s parse\b",
    r"^first[,\s]",
    r"\bneed to\b.*\binstructions?\b",
    r"we have to note\b",
    r"i should\b.*\binstructions?\b",
    r"per the instructions?\b",
    r"based on the instructions?\b",
    r"the schema requires\b",
    r"we must return json\b",
    r"need to output\b",
    r"first[,\s]+we need\b",
    r"i should\b",
]

_LEAKAGE_RE = re.compile(
    "|".join(_LEAKAGE_PATTERNS),
    re.IGNORECASE,
)

_SAFE_FALLBACK = (
    "What concrete evidence can you give me right now to back that claim?"
)


def check_leakage(text: str) -> dict:
    """Return a structured leakage check result.

    Returns:
        {"ok": True}  — no leakage detected
        {"ok": False, "matched_pattern": str, "excerpt": str}  — leakage found
    """
    if not text:
        return {"ok": True}
    m = _LEAKAGE_RE.search(text)
    if m:
        start = max(0, m.start() - 20)
        end = min(len(text), m.end() + 40)
        excerpt = text[start:end].replace("\n", " ").strip()
        return {
            "ok": False,
            "matched_pattern": m.group(0),
            "excerpt": excerpt,
        }
    return {"ok": True}


def sanitize_model_output(text: str) -> str:
    """Remove instruction-leakage lines from Nemotron judge output.

    Splits by sentence/line, drops any that contain leakage patterns,
    returns the joined remainder. If nothing survives, returns a safe
    fallback question.
    """
    if not text:
        return _SAFE_FALLBACK

    lines = text.splitlines()
    clean_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _LEAKAGE_RE.search(stripped):
            continue
        clean_lines.append(stripped)

    result = " ".join(clean_lines).strip()

    if len(result.split()) < 4:
        return _SAFE_FALLBACK

    return result
