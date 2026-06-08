"""Battle flow controller for PitchFight AI.

Controls Socratic judge pacing:
- Classifies each founder answer (strong / partial / weak / non_answer)
- Decides whether to follow up on the same attack tag or move to the next one
- Enforces MAX_ATTEMPTS_PER_ATTACK_TAG so no topic is drilled forever
- Maintains per-session battle state (tag_attempts, outcomes, completed_tags)

Voice mode note:
  Future voice mode will pass transcripts into the same classify_answer_quality()
  and decide_next_judge_action() functions without any changes here.
  This module never assumes keyboard input — it only sees text strings.
"""

from __future__ import annotations

import re
from typing import Any

from core.attack_tags import get_attack_tags

MAX_ATTEMPTS_PER_ATTACK_TAG = 2
MAX_FOLLOWUPS_PER_ATTACK_TAG = 1  # same as attempts - 1 (first is always a fresh question)

# ---------------------------------------------------------------------------
# Weak-signal patterns (rule-based, no extra API call)
# ---------------------------------------------------------------------------

_NON_ANSWER_PHRASES = {
    "ok", "okay", "idk", "i don't know", "dont know", "don't know",
    "not sure", "maybe", "no idea", "hmm", "i'm not sure", "im not sure",
    "i dont know", "i have no idea", "not really", "yeah", "sure",
    "fine", "alright", "whatever", "pass",
}

_VAGUE_WORDS = {
    "big", "huge", "large", "massive", "many", "everyone", "anybody",
    "helpful", "useful", "better", "good", "great", "nice", "amazing",
    "smart", "intelligent", "automatically", "seamlessly", "easily",
    "quickly", "simply", "pretty", "kind", "sort", "basically",
    "generally", "typically", "usually", "obviously", "clearly",
}

_STRONG_SIGNALS = [
    # Concrete numbers attached to evidence nouns
    r"\d+\s*%",                                                                      # 12%
    r"\d+\s*\w*\s*(users?|signups?|students?|schools?|campuses?|installs?|teams?|pilots?|ambassadors?|colleges?|universities)",
    r"\$\s*\d+",                                                                     # $50
    r"\d+\s*(k|m|b)\b",                                                             # 10k, 2m
    # Product and business metrics
    r"\b(dau|mau|wau|retention|churn|ltv|arpu|cac|nps)\b",
    r"\b(paying|waitlist|revenue|traction|mrr|arr)\b",
    # User research and validation
    r"\b(interviewed|surveyed|measured|validated|tested|piloted)\b",
    r"\b(user interview|data point|conversion rate|event.miss report)\b",
    # Named target segment (specific, not vague "everyone")
    r"\b(cs students?|engineering students?|stem students?|mba students?|undergrad|sophomore|freshman|senior year)\b",
    r"\b(iit|nit|bits|vit|college name|university name)\b",
    # Competitor differentiation
    r"\b(unlike\s+\w+|vs\.?\s+\w+|compared to\s+\w+|instead of\s+\w+|luma|lu\.ma|eventbrite|meetup|devfolio|unstop)\b",
    # Revenue or retention logic
    r"\b(monthly recurring|annual recurring|subscription|freemium|pay per|sponsor pays|college pays)\b",
    # Specific technical explanation (more than buzzwords)
    r"\b(embedding|vector|fine.?tun|retrieval|ranking model|cosine similarity|recommendation engine)\b",
]

_STRONG_PATTERN = re.compile(
    "|".join(_STRONG_SIGNALS),
    re.IGNORECASE,
)


def classify_answer_quality(answer: str) -> dict[str, Any]:
    """Classify a founder answer without making any API calls.

    Voice mode note:
      Accepts text from any source — typed input or voice transcript.
      The caller is responsible for converting audio to text before calling here.

    Returns:
        {
            "quality":  "strong" | "partial" | "weak" | "non_answer",
            "reason":   human-readable explanation,
            "signals":  list of matched evidence signals (may be empty),
        }
    """
    text = answer.strip()
    words = text.split()
    word_count = len(words)
    lower = text.lower()

    # --- non_answer: empty, trivially short, or known filler phrase ---
    if word_count < 4:
        return {
            "quality": "non_answer",
            "reason": "Answer is too short to evaluate.",
            "signals": [],
        }

    if lower in _NON_ANSWER_PHRASES or any(
        lower.startswith(p) or lower == p for p in _NON_ANSWER_PHRASES
    ):
        return {
            "quality": "non_answer",
            "reason": "Answer is a known non-response phrase.",
            "signals": [],
        }

    # --- strong: contains concrete evidence signals ---
    strong_hits = [m.group(0) for m in _STRONG_PATTERN.finditer(text)]
    if strong_hits:
        unique = list({h.strip().lower() for h in strong_hits if h.strip()})
        return {
            "quality": "strong",
            "reason": "Answer contains concrete evidence or data.",
            "signals": unique[:5],
        }

    # --- weak: short or dominated by vague terms ---
    lower_words = set(re.findall(r"\w+", lower))
    vague_overlap = lower_words & _VAGUE_WORDS
    vague_count = len(vague_overlap)
    vague_ratio = vague_count / max(word_count, 1)

    # A sentence is weak if it's short, has a high vague ratio,
    # OR contains 2+ vague adjectives that carry the main claim
    is_weak = word_count < 8 or vague_ratio >= 0.20 or (vague_count >= 2 and word_count < 20)

    if is_weak:
        return {
            "quality": "weak",
            "reason": (
                "Answer is too short or relies on vague claims without evidence."
                + (f" Vague words: {', '.join(sorted(vague_overlap)[:3])}." if vague_overlap else "")
            ),
            "signals": [],
        }

    # --- partial: answer has some content but no strong signals ---
    return {
        "quality": "partial",
        "reason": "Answer gives some reasoning but lacks concrete evidence or numbers.",
        "signals": [],
    }


# ---------------------------------------------------------------------------
# Battle state helpers
# ---------------------------------------------------------------------------

def _init_battle_state(session: dict) -> dict:
    """Return existing battle_state or create a fresh one."""
    if "battle_state" not in session:
        session["battle_state"] = {
            "tag_attempts": {},      # {attack_tag: int}
            "tag_outcomes": {},      # {attack_tag: "resolved" | "unresolved"}
            "last_answer_quality": {},
            "last_judge_action": {},
            "completed_tags": [],
        }
    return session["battle_state"]


def init_opening_state(session: dict, opening_attack_tag: str) -> None:
    """Initialize battle_state at session start with the opening tag attempt."""
    state = _init_battle_state(session)
    state["tag_attempts"][opening_attack_tag] = 1
    state["last_judge_action"] = {
        "judge_action": "opening_question",
        "next_attack_tag": opening_attack_tag,
        "previous_attack_tag": None,
        "attempt_number_for_tag": 1,
        "topic_satisfied": None,
        "transition_note": "Opening question.",
    }


def decide_next_judge_action(
    session: dict,
    current_attack_tag: str,
    answer_quality: str,
    persona: str,
) -> dict[str, Any]:
    """Decide what the judge should do next based on answer quality and tag history.

    Returns:
        {
            "judge_action":           "follow_up_same_tag" | "move_next_tag" | "move_after_limit",
            "next_attack_tag":        str,
            "previous_attack_tag":    str,
            "attempt_number_for_tag": int,
            "topic_satisfied":        bool,
            "transition_note":        str,
        }
    """
    state = _init_battle_state(session)
    tag_attempts: dict[str, int] = state.get("tag_attempts", {})

    current_attempts = tag_attempts.get(current_attack_tag, 1)

    # --- Strong answer: topic done, advance ---
    if answer_quality == "strong":
        state["tag_outcomes"][current_attack_tag] = "resolved"
        if current_attack_tag not in state["completed_tags"]:
            state["completed_tags"].append(current_attack_tag)

        next_tag = _pick_next_tag(persona, state)
        tag_attempts[next_tag] = tag_attempts.get(next_tag, 0) + 1

        return {
            "judge_action": "move_next_tag",
            "next_attack_tag": next_tag,
            "previous_attack_tag": current_attack_tag,
            "attempt_number_for_tag": tag_attempts[next_tag],
            "topic_satisfied": True,
            "transition_note": (
                f"Founder addressed {current_attack_tag} adequately. Moving to {next_tag}."
            ),
        }

    # --- Weak / partial / non_answer ---
    if current_attempts < MAX_ATTEMPTS_PER_ATTACK_TAG:
        # Follow up on the same tag
        tag_attempts[current_attack_tag] = current_attempts + 1

        return {
            "judge_action": "follow_up_same_tag",
            "next_attack_tag": current_attack_tag,
            "previous_attack_tag": current_attack_tag,
            "attempt_number_for_tag": current_attempts + 1,
            "topic_satisfied": False,
            "transition_note": (
                f"Answer was {answer_quality}. Pressing harder on {current_attack_tag} "
                f"(attempt {current_attempts + 1}/{MAX_ATTEMPTS_PER_ATTACK_TAG})."
            ),
        }

    # --- Limit reached: mark unresolved, move on ---
    state["tag_outcomes"][current_attack_tag] = "unresolved"
    if current_attack_tag not in state["completed_tags"]:
        state["completed_tags"].append(current_attack_tag)

    next_tag = _pick_next_tag(persona, state)
    tag_attempts[next_tag] = tag_attempts.get(next_tag, 0) + 1

    return {
        "judge_action": "move_after_limit",
        "next_attack_tag": next_tag,
        "previous_attack_tag": current_attack_tag,
        "attempt_number_for_tag": tag_attempts[next_tag],
        "topic_satisfied": False,
        "transition_note": (
            f"Max attempts reached for {current_attack_tag} — moving to {next_tag}."
        ),
    }


def update_battle_state(
    session: dict,
    attack_tag: str,
    answer_quality: dict[str, Any],
    judge_action: dict[str, Any],
) -> dict[str, Any]:
    """Persist answer quality and judge action into session battle_state."""
    state = _init_battle_state(session)
    state["last_answer_quality"] = answer_quality
    state["last_judge_action"] = judge_action
    return state


def get_current_attack_tag(session: dict) -> str | None:
    """Return the attack tag from the last AI message stored in history."""
    history = session.get("history", [])
    for entry in reversed(history):
        if entry.get("role") == "assistant" and entry.get("attack_tag"):
            return entry["attack_tag"]
    return None


# ---------------------------------------------------------------------------
# Internal: pick the next tag not yet exhausted
# ---------------------------------------------------------------------------

def _pick_next_tag(persona: str, state: dict) -> str:
    """Select the next attack tag, preferring unused ones."""
    all_tags = get_attack_tags(persona)
    tag_attempts: dict[str, int] = state.get("tag_attempts", {})
    completed: list[str] = state.get("completed_tags", [])

    # Prefer tags not yet attempted
    for tag in all_tags:
        if tag not in tag_attempts:
            return tag

    # Fall back to tags with lowest attempts that aren't in completed
    remaining = [t for t in all_tags if t not in completed]
    if remaining:
        return min(remaining, key=lambda t: tag_attempts.get(t, 0))

    # All tags exhausted — cycle from the beginning
    return all_tags[0] if all_tags else "General Pressure"
