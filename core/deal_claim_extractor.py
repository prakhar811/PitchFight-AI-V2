"""Deal negotiation signal extractor — local regex/keyword logic."""

from __future__ import annotations

import re
from typing import Any

_ANCHOR = re.compile(
    r"(?:\d+\.?\d*\s*%)"
    r"|(?:₹|rs\.?|\$|€)\s*[\d,.]+(?:\s*(?:lakhs?|crores?|cr|k|million|mn))?"
    r"|(?:\d+\s*(?:weeks?|months?|years?))"
    r"|(?:\d+\.?\d*\s*(?:equity|stake|ownership))"
    r"|(?:discount\s*(?:of\s*)?\d+\.?\d*\s*%)"
    r"|(?:pilot\s*(?:for\s*)?\d+\s*(?:weeks?|months?))",
    re.IGNORECASE,
)

_EVIDENCE = re.compile(
    r"\b(?:users?|patients?|hospitals?|pilots?|mou|loi|contract|deployed|revenue|"
    r"retention|roi|case study|reference|paying|customers?|clients?|traction)\b",
    re.IGNORECASE,
)

_CONCESSION = re.compile(
    r"\b(?:we can accept|willing to|flexible on|we can reduce|"
    r"open to|meet you halfway|compromise|we can move|we could give)\b",
    re.IGNORECASE,
)

# Weak concession = giving ground with no condition extracted. Bare "ok"/"sure" handled
# separately so a harmless acknowledgement is NOT treated as a weak concession.
_WEAK_CONCESSION = re.compile(
    r"\b(?:okay fine|whatever works|if you insist|i guess|that's okay too|"
    r"no problem,? we can do that|sure,? take it|you decide|accept whatever|"
    r"whatever (?:terms|you want)|fine,? we can accept)\b",
    re.IGNORECASE,
)

# Alternatives / leverage — credit natural phrasing, not just "BATNA".
_ALTERNATIVES = re.compile(
    r"\b(?:other investors?|another offer|other clients?|other (?:colleges?|campuses?|"
    r"mentors?|partners?|customers?|buyers?)|also talking to|also speaking|in talks with|"
    r"parallel (?:conversations?|talks)|multiple options|alternatives?|pipeline|"
    r"not dependent|don'?t depend|batna|backup(?: option| plan)?|another route|"
    r"we can still|we are also|we'?re also|we already have|we have other)\b",
    re.IGNORECASE,
)

_VALUE = re.compile(
    r"\b(?:roi|return on|value|fair terms|risk.?reward|worth it|payback|"
    r"cost.?benefit|margin|unit economics|saves?|reduces? cost|cost savings?|"
    r"efficien\w+|growth|upside|long.?term value)\b",
    re.IGNORECASE,
)

_CLOSING = re.compile(
    r"\b(?:term sheet|next step|follow.?up|finalize|schedule|move forward|"
    r"pilot agreement|sign|timeline|commit|let'?s proceed|shake on|proceed|"
    r"confirm(?: today)?|send (?:over )?(?:the )?(?:term sheet|paperwork|contract)|"
    r"lock (?:in|the metric)|close (?:this|the deal)|wrap (?:this )?up)\b",
    re.IGNORECASE,
)

_NUMBERS = re.compile(
    r"(?:₹|rs\.?|\$)\s*[\d,.]+(?:\s*(?:lakhs?|crores?|cr|k))?"
    r"|\b\d+\.?\d*\s*%"
    r"|\b\d[\d,]+\s*(?:users?|patients?|hospitals?|customers?)",
    re.IGNORECASE,
)

_COUNTEROFFER = re.compile(
    r"\b(?:counter|instead(?: of)?|how about|we propose|we'?d accept|offer of|"
    r"would take|we'?d take|at \d+\.?\d*\s*%|for \d+\.?\d*\s*%)\b",
    re.IGNORECASE,
)

_TRADEOFF = re.compile(
    r"\b(?:in exchange|trade.?off|if you|in return|conditional on|provided that|"
    r"only if|i can agree if|we can (?:move|agree) if|milestone|vesting|cliff|"
    r"in turn|as long as|on the condition)\b",
    re.IGNORECASE,
)

# Bare one-word acknowledgements — must NOT count as substantive moves or weak concessions.
_ONE_WORD_ACK = frozenset({
    "sure", "ok", "okay", "yes", "fine", "yeah", "yep", "agreed", "cool",
    "alright", "right", "sounds good", "got it", "understood",
})

# Deal terms whose presence makes even a short message "substantive".
_DEAL_TERM = re.compile(
    r"(?:₹|rs\.?|\$|€|\d+\s*%|\bequity\b|\bstake\b|\bpilot\b|\bmilestone\b|"
    r"\bvaluation\b|\btranche\b|\bdiscount\b|\bmonths?\b|\bweeks?\b|\bsign\b|"
    r"\bterm sheet\b|\bcounter\b)",
    re.IGNORECASE,
)


def is_one_word_ack(message: str) -> bool:
    """True if the message is a bare acknowledgement with no deal term (e.g. 'sure', 'ok')."""
    t = (message or "").strip().lower().rstrip(".!?")
    t = re.sub(r"[^a-z ]", "", t).strip()
    if not t:
        return True
    if _DEAL_TERM.search(message or ""):
        return False
    return t in _ONE_WORD_ACK


def is_substantive_move(message: str) -> bool:
    """True if a founder message is a real negotiation move worth judging.

    Substantive = longer than 20 characters OR contains a concrete deal term.
    Bare one-word acknowledgements ('sure', 'ok', 'yes', 'fine') are NOT substantive.
    """
    t = (message or "").strip()
    if not t or is_one_word_ack(t):
        return False
    if len(t) > 20:
        return True
    if _DEAL_TERM.search(t):
        return True
    return len(t.split()) >= 4


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        k = item.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(item.strip())
    return out


def _match_all(pattern: re.Pattern[str], text: str) -> list[str]:
    return _dedup([m.group(0).strip() for m in pattern.finditer(text or "")])


def extract_deal_signals(deal_history: list[dict], deal_context: dict | None = None) -> dict[str, Any]:
    """Extract negotiation signals from deal history and context."""
    texts: list[str] = []
    user_texts: list[str] = []
    for entry in deal_history or []:
        msg = str(entry.get("message", "")).strip()
        if msg:
            texts.append(msg)
            if entry.get("role") == "user":
                user_texts.append(msg)

    ctx = deal_context or {}
    for key in ("ask", "opening_offer", "founder_position", "judge_position"):
        val = str(ctx.get(key, "")).strip()
        if val:
            texts.append(val)

    combined = " ".join(texts)
    user_combined = " ".join(user_texts)

    return {
        "anchor_points":           _match_all(_ANCHOR, user_combined),
        "evidence_signals":        _match_all(_EVIDENCE, user_combined),
        "concession_signals":      _match_all(_CONCESSION, user_combined),
        "weak_concession_signals": _match_all(_WEAK_CONCESSION, user_combined),
        "alternative_signals":     _match_all(_ALTERNATIVES, user_combined),
        "value_signals":           _match_all(_VALUE, user_combined),
        "closing_signals":         _match_all(_CLOSING, user_combined),
        "specific_numbers":        _match_all(_NUMBERS, user_combined),
        "counteroffers":           _match_all(_COUNTEROFFER, user_combined),
        "tradeoffs":               _match_all(_TRADEOFF, user_combined),
        "user_turns":              len(user_texts),
        "signal_count": (
            len(_match_all(_ANCHOR, user_combined))
            + len(_match_all(_EVIDENCE, user_combined))
            + len(_match_all(_NUMBERS, user_combined))
        ),
    }
