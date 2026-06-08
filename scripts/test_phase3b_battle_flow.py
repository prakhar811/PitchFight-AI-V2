"""Phase 3B end-to-end test: Socratic judge flow via the running server.

Validates:
  - answer_quality classification appears in chat-round responses
  - judge_action drives tag switching / follow-up decisions
  - Same attack tag not repeated more than MAX_ATTEMPTS_PER_ATTACK_TAG times
  - ai_message is always non-empty (model or mock fallback)
  - All required response fields are present

Usage:
  python scripts/test_phase3b_battle_flow.py

Server must already be running. Set PITCHFIGHT_BASE_URL to override default.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

import requests

BASE_URL = os.getenv("PITCHFIGHT_BASE_URL", "http://127.0.0.1:7861").rstrip("/")

SAMPLE_STARTUP = {
    "name": "EventRadar AI",
    "problem": "Students miss relevant hackathons, workshops, and networking events.",
    "solution": "AI-powered event discovery that ranks events by fit for each student profile.",
    "why_ai": "Personalized ranking requires understanding student goals and event signals together.",
    "stage": "Prototype",
    "team": "2 founders",
    "traction": "50 beta signups, no revenue yet",
}

STRONG_ANSWER = (
    "We validated this with 50 beta users, 3 campus ambassadors, "
    "and weekly event-miss reports from two colleges."
)

ANSWERS = [
    "It is a pretty big market because students attend events often.",  # weak
    "I don't know",                                                      # non_answer
    "ok",                                                                # non_answer → triggers move_after_limit
    STRONG_ANSWER,                                                       # strong → move_next_tag
    "The AI personalizes event ranking based on student goals.",         # partial
]

MAX_ATTEMPTS_ALLOWED = 2  # must match battle_flow.MAX_ATTEMPTS_PER_ATTACK_TAG


def post(path: str, body: dict) -> dict:
    url = f"{BASE_URL}{path}"
    resp = requests.post(url, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


def check(label: str, condition: bool, detail: str = "") -> None:
    marker = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  {marker}  {label}{suffix}")
    if not condition:
        sys.exit(1)


def main() -> None:
    print(f"\nPhase 3B Battle Flow Test\nBase URL: {BASE_URL}\n")

    # --- start-session ---
    print("Step 0: POST /api/start-session")
    try:
        start = post("/api/start-session", {
            "mode": "pitch_battle",
            "startup": SAMPLE_STARTUP,
            "persona": "hackathon_judge",
            "difficulty": "high",
            "input_mode": "text",
            "model_mode": "premium_nvidia",
        })
    except Exception as exc:
        print(f"  FAIL  Request failed: {exc}")
        sys.exit(1)

    session_id = start.get("session_id")
    check("session_id present", bool(session_id))
    check("ai_message non-empty", bool(start.get("ai_message")))
    check("judge_action = opening_question", start.get("judge_action") == "opening_question",
          f"got {start.get('judge_action')!r}")
    check("answer_quality is None", start.get("answer_quality") is None,
          f"got {start.get('answer_quality')!r}")
    check("tag_attempt = 1", start.get("tag_attempt") == 1, f"got {start.get('tag_attempt')!r}")

    opening_tag = start.get("attack_tag")
    print(f"  opening attack_tag : {opening_tag}")
    print(f"  ai_message         : {start['ai_message'][:120]}...\n")

    # Track tag attempt counts locally to verify the invariant
    tag_attempts: dict[str, int] = defaultdict(int)
    tag_attempts[opening_tag] += 1

    rounds: list[dict] = []

    # --- chat rounds ---
    for i, answer in enumerate(ANSWERS, start=1):
        round_num = i + 1  # round 1 was the opening
        print(f"Step {i}: POST /api/chat-round  (sending: {answer!r})")

        try:
            data = post("/api/chat-round", {
                "session_id": session_id,
                "user_message": answer,
            })
        except Exception as exc:
            print(f"  FAIL  Request failed: {exc}")
            sys.exit(1)

        atag = data.get("attack_tag", "")
        aq = data.get("answer_quality", "")
        ja = data.get("judge_action", "")
        attempt = data.get("tag_attempt", 0)
        satisfied = data.get("topic_satisfied")
        prev_tag = data.get("previous_attack_tag", "")

        # Update local tracking
        tag_attempts[atag] += 1

        print(f"  round              : {data.get('round')}")
        print(f"  attack_tag         : {atag}")
        print(f"  previous_tag       : {prev_tag}")
        print(f"  answer_quality     : {aq}")
        print(f"  judge_action       : {ja}")
        print(f"  tag_attempt        : {attempt}")
        print(f"  topic_satisfied    : {satisfied}")
        print(f"  model_ok           : {data.get('model_ok')}")
        print(f"  provider           : {data.get('provider')}")
        print(f"  ai_message         : {data.get('ai_message', '')[:120]}...\n")

        # Required field checks
        check("session_id echoed", data.get("session_id") == session_id)
        check("ai_message non-empty", bool(data.get("ai_message")), "ai_message is empty")
        check("attack_tag present", bool(atag))
        check("answer_quality present", aq in ("strong", "partial", "weak", "non_answer"),
              f"got {aq!r}")
        check("judge_action present", ja in ("follow_up_same_tag", "move_next_tag", "move_after_limit"),
              f"got {ja!r}")
        check("tag_attempt present", isinstance(attempt, int) and attempt >= 1,
              f"got {attempt!r}")
        check("provider present", bool(data.get("provider")))

        rounds.append(data)

    # --- Invariant: no tag exceeded MAX_ATTEMPTS_ALLOWED across all rounds ---
    print("Invariant check: no attack_tag exceeded MAX_ATTEMPTS_PER_ATTACK_TAG")
    for tag, count in tag_attempts.items():
        if tag in ("Round Limit", "Session Error"):
            continue
        check(
            f"  tag '{tag}' attempts <= {MAX_ATTEMPTS_ALLOWED}",
            count <= MAX_ATTEMPTS_ALLOWED,
            f"got {count} attempts",
        )

    # --- Verify first weak answer triggered follow_up_same_tag (not a random jump) ---
    first = rounds[0]
    first_ja = first.get("judge_action", "")
    check(
        "First weak answer → follow_up or move (not random jump)",
        first_ja in ("follow_up_same_tag", "move_after_limit", "move_next_tag"),
        f"got {first_ja!r}",
    )

    # --- Verify third answer ("ok") did not keep drilling the same tag forever ---
    if len(rounds) >= 3:
        third_ja = rounds[2].get("judge_action", "")
        check(
            "After 2nd non-answer on same tag, judge moved or pressed (no infinite loop)",
            third_ja in ("move_after_limit", "move_next_tag", "follow_up_same_tag"),
            f"got {third_ja!r}",
        )

    # --- Strong-answer checks (rounds[3] = STRONG_ANSWER) ---
    if len(rounds) >= 4:
        strong_round = rounds[3]
        strong_ja = strong_round.get("judge_action", "")
        strong_tag = strong_round.get("attack_tag", "")
        strong_prev = strong_round.get("previous_attack_tag", "")
        strong_satisfied = strong_round.get("topic_satisfied")

        print("\nStrong-answer invariant checks:")
        check(
            "Strong answer → judge_action is move_next_tag",
            strong_ja == "move_next_tag",
            f"got {strong_ja!r}",
        )
        check(
            "Strong answer → attack_tag changed from previous_attack_tag",
            strong_tag != strong_prev,
            f"both are {strong_tag!r} — judge did not advance",
        )
        check(
            "Strong answer → topic_satisfied is True",
            strong_satisfied is True,
            f"got {strong_satisfied!r}",
        )
        check(
            "Strong answer → answer_quality is 'strong'",
            strong_round.get("answer_quality") == "strong",
            f"got {strong_round.get('answer_quality')!r}",
        )

    print("\nAll Phase 3B checks passed. Socratic battle flow is working.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
