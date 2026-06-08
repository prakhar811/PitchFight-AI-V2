"""Phase 4 stability test: full battle lifecycle via the running server.

Validates:
  - Battle runs cleanly from start to and beyond MAX_ROUNDS
  - Strong answer causes move_next_tag with different attack_tag
  - No attack_tag exceeds 2 attempts
  - At round >= MAX_ROUNDS: soft_round_limit_reached=True, battle_complete=False, can_continue=True
  - Chat continues working after MAX_ROUNDS (no hard block)
  - /api/end-battle returns a scorecard dict (even if mock)
  - Every ai_message is non-empty throughout
  - No ai_message contains instruction leakage patterns

Usage:
  python scripts/test_phase4_battle_stability.py
  PITCHFIGHT_BASE_URL=http://localhost:7861 python scripts/test_phase4_battle_stability.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

import requests

BASE_URL = os.getenv("PITCHFIGHT_BASE_URL", "http://127.0.0.1:7861").rstrip("/")
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "6"))

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

# Sequence designed to exercise all branches: weak → non_answer → strong → partial → weak → strong
ANSWER_SEQUENCE = [
    "It is a pretty big market because students attend events often.",   # weak
    "I don't know",                                                       # non_answer
    STRONG_ANSWER,                                                        # strong → move_next_tag
    "The AI ranks events based on student interest profiles.",            # partial
    "okay fine",                                                          # non_answer
    "We use embeddings and a ranking model trained on student behavior.", # strong (technical)
    "It is useful and helpful for everyone.",                             # weak — beyond MAX_ROUNDS
]

_LEAKAGE_PATTERNS = re.compile(
    r"we need to\b|the prompt says\b|as instructed\b|my instructions\b"
    r"|i am supposed to\b|i should follow\b|the rules say\b|per the instructions?\b",
    re.IGNORECASE,
)


def post(path: str, body: dict, timeout: int = 90) -> dict:
    resp = requests.post(f"{BASE_URL}{path}", json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def check(label: str, condition: bool, detail: str = "") -> None:
    marker = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  {marker}  {label}{suffix}")
    if not condition:
        sys.exit(1)


def main() -> None:
    print(f"\nPhase 4 Battle Stability Test (Soft Round Limit)")
    print(f"Base URL  : {BASE_URL}")
    print(f"MAX_ROUNDS: {MAX_ROUNDS}\n")

    # -------------------------------------------------------------------------
    # Step 0: Start session
    # -------------------------------------------------------------------------
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
    check("round == 1", start.get("round") == 1, f"got {start.get('round')}")
    check("judge_action == opening_question", start.get("judge_action") == "opening_question")
    check("battle_complete=False at start", start.get("battle_complete") is False)
    check("can_continue=True at start", start.get("can_continue") is True)

    opening_tag = start.get("attack_tag")
    print(f"  opening_tag  : {opening_tag}")
    print(f"  battle_phase : {start.get('battle_phase')}")
    print(f"  ai_message   : {start['ai_message'][:100]}...\n")

    check(
        "start ai_message has no leakage",
        not _LEAKAGE_PATTERNS.search(start.get("ai_message", "")),
        "instruction leakage detected in opening message",
    )

    # -------------------------------------------------------------------------
    # Steps 1..MAX_ROUNDS+1: chat rounds (one beyond soft limit)
    # -------------------------------------------------------------------------
    tag_attempt_counts: dict[str, int] = defaultdict(int)
    tag_attempt_counts[opening_tag] += 1

    rounds: list[dict] = []
    strong_round_idx: int | None = None

    answers_to_send = ANSWER_SEQUENCE[: MAX_ROUNDS + 1]  # include one beyond soft limit

    for i, answer in enumerate(answers_to_send):
        print(f"Step {i + 1}: POST /api/chat-round  answer={answer[:60]!r}")
        try:
            data = post("/api/chat-round", {
                "session_id": session_id,
                "user_message": answer,
            })
        except Exception as exc:
            print(f"  FAIL  Request failed: {exc}")
            sys.exit(1)

        atag     = data.get("attack_tag", "")
        aq       = data.get("answer_quality", "")
        ja       = data.get("judge_action", "")
        prev_tag = data.get("previous_attack_tag", "")
        rnd      = data.get("round", 0)
        bc       = data.get("battle_complete", True)
        cc       = data.get("can_continue", False)
        na       = data.get("next_action", "")
        sl       = data.get("soft_round_limit_reached", False)
        phase    = data.get("battle_phase", "")

        if atag not in ("Round Limit", "Session Error", ""):
            tag_attempt_counts[atag] += 1

        print(f"  round                   : {rnd}")
        print(f"  battle_phase            : {phase}")
        print(f"  attack_tag              : {atag}")
        print(f"  prev_tag                : {prev_tag}")
        print(f"  answer_quality          : {aq}")
        print(f"  judge_action            : {ja}")
        print(f"  battle_complete         : {bc}  can_continue: {cc}  next_action: {na}")
        print(f"  soft_round_limit_reached: {sl}")
        print(f"  model_ok                : {data.get('model_ok')}  provider: {data.get('provider')}")
        print(f"  ai_message              : {data.get('ai_message', '')[:100]}...\n")

        # Required fields
        check("session_id echoed", data.get("session_id") == session_id)
        check("ai_message non-empty", bool(data.get("ai_message")), "empty ai_message")
        check("attack_tag present", bool(atag))
        check("provider present", bool(data.get("provider")))
        check("model_mode present", bool(data.get("model_mode")))

        # battle_complete must always be False (soft limit only)
        check("battle_complete always False", bc is False, f"got {bc!r}")
        check("can_continue always True", cc is True, f"got {cc!r}")
        check("next_action always continue", na == "continue", f"got {na!r}")

        # Soft limit flag
        if rnd >= MAX_ROUNDS:
            check("soft_round_limit_reached=True at/after MAX_ROUNDS", sl is True, f"got {sl!r}")
            check(
                "recommended_action=end_battle when soft limit",
                data.get("recommended_action") == "end_battle",
                f"got {data.get('recommended_action')!r}",
            )
        else:
            check("soft_round_limit_reached=False before MAX_ROUNDS", sl is False, f"got {sl!r}")

        # Valid answer quality and judge action on normal rounds
        if atag not in ("Round Limit",):
            check(
                "answer_quality valid",
                aq in ("strong", "partial", "weak", "non_answer"),
                f"got {aq!r}",
            )
            check(
                "judge_action valid",
                ja in ("follow_up_same_tag", "move_next_tag", "move_after_limit"),
                f"got {ja!r}",
            )

        # No leakage
        ai_msg = data.get("ai_message", "")
        check(
            "ai_message has no instruction leakage",
            not _LEAKAGE_PATTERNS.search(ai_msg),
            "instruction leakage detected",
        )

        # battle_phase progression
        if rnd <= 3:
            check("battle_phase=explore in rounds 1-3", phase == "explore", f"got {phase!r}")
        elif rnd <= 6:
            check("battle_phase=pressure in rounds 4-6", phase == "pressure", f"got {phase!r}")
        else:
            check("battle_phase=close in rounds 7+", phase == "close", f"got {phase!r}")

        # Strong answer invariant
        if aq == "strong" and strong_round_idx is None:
            strong_round_idx = i
            check("Strong answer → judge_action is move_next_tag", ja == "move_next_tag", f"got {ja!r}")
            check("Strong answer → attack_tag changed", atag != prev_tag, f"both are {atag!r}")
            check("Strong answer → topic_satisfied is True", data.get("topic_satisfied") is True)

        rounds.append(data)

    # -------------------------------------------------------------------------
    # Invariant: no attack_tag exceeded 2 attempts
    # -------------------------------------------------------------------------
    print("Invariant: no attack_tag exceeded MAX_ATTEMPTS_PER_ATTACK_TAG (2)")
    for tag, count in tag_attempt_counts.items():
        if tag in ("Round Limit", "Session Error", ""):
            continue
        check(f"  tag '{tag}' attempts <= 2", count <= 2, f"got {count}")

    # -------------------------------------------------------------------------
    # /api/end-battle — must return a scorecard dict (mock is fine)
    # -------------------------------------------------------------------------
    print("\nStep final: POST /api/end-battle")
    try:
        scorecard = post("/api/end-battle", {"session_id": session_id})
    except Exception as exc:
        print(f"  FAIL  end-battle request failed: {exc}")
        sys.exit(1)

    print(f"  overall         : {scorecard.get('overall')}")
    print(f"  overall_label   : {scorecard.get('overall_label')}")
    print(f"  scorecard_source: {scorecard.get('scorecard_source')}")
    print(f"  keys            : {list(scorecard.keys())}")

    check("end-battle returns dict", isinstance(scorecard, dict))
    check("no error in end-battle", "error" not in scorecard, f"error={scorecard.get('error')}")
    check("overall score present", "overall" in scorecard, f"keys={list(scorecard.keys())}")
    check("overall_label present", "overall_label" in scorecard)
    check("scorecard_source present", "scorecard_source" in scorecard)

    print("\nAll Phase 4 stability checks passed.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
