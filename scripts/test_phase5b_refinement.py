"""Phase 5B/5D refinement test: 8+ rounds, soft limit, battle_phase, labels, no leakage.

Validates:
  - User can continue chatting past MAX_ROUNDS (no hard block)
  - soft_round_limit_reached appears at round >= MAX_ROUNDS
  - battle_phase progresses: explore (1-3), pressure (4-6), close (7+)
  - No instruction leakage in any ai_message
  - /api/end-battle returns hybrid claim-based scorecard with score labels
  - overall_label and per-dimension labels present
  - scorecard_source in ("hybrid_claims_nemotron", "hybrid_claims_local")

Usage:
  python scripts/test_phase5b_refinement.py
  ALLOW_SCORECARD_FALLBACK=true python scripts/test_phase5b_refinement.py
"""

from __future__ import annotations

import os
import re
import sys

import requests

BASE_URL = os.getenv("PITCHFIGHT_BASE_URL", "http://127.0.0.1:7861").rstrip("/")
ALLOW_FALLBACK = os.getenv("ALLOW_SCORECARD_FALLBACK", "false").strip().lower() == "true"
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

# 9 answers to go well past MAX_ROUNDS=6
ANSWERS = [
    "It is a pretty big market because students attend events often.",         # weak
    "I don't know",                                                             # non_answer
    STRONG_ANSWER,                                                              # strong
    "The AI ranks events based on student interest profiles.",                  # partial
    "We use embeddings and a ranking model trained on student behavior data.",  # strong
    "okay",                                                                     # non_answer
    "Our differentiation is the personalization layer no event aggregator has.",# partial
    "We plan to charge colleges $500/month for analytics and promotions.",      # partial (revenue)
    "We have 3 campus ambassadors onboarding 20 students each right now.",      # strong
]

REQUIRED_DIMS = {
    "clarity", "problem_understanding", "market_awareness",
    "differentiation", "business_model", "objection_handling",
}
_VALID_LABELS = {"Not addressed", "Developing", "Solid", "Strong", "Excellent"}

_LEAKAGE = re.compile(
    r"we need to\b|the prompt says\b|as instructed\b|my instructions\b"
    r"|i am supposed to\b|i should follow\b|the rules say\b|per the instructions?\b",
    re.IGNORECASE,
)


def post(path: str, body: dict, timeout: int = 180) -> dict:
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
    print(f"\nPhase 5B Refinement Test")
    print(f"Base URL       : {BASE_URL}")
    print(f"MAX_ROUNDS     : {MAX_ROUNDS}")
    print(f"Allow fallback : {ALLOW_FALLBACK}")
    print(f"Total answers  : {len(ANSWERS)} (well past MAX_ROUNDS)\n")

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
        print(f"  FAIL  Could not start session: {exc}")
        sys.exit(1)

    session_id = start.get("session_id")
    check("session_id present", bool(session_id))
    check("ai_message non-empty", bool(start.get("ai_message")))
    check("battle_complete=False at start", start.get("battle_complete") is False)
    check("can_continue=True at start", start.get("can_continue") is True)
    check("battle_phase present", bool(start.get("battle_phase")))
    check("start battle_phase=explore", start.get("battle_phase") == "explore",
          f"got {start.get('battle_phase')!r}")
    check("no leakage in opening", not _LEAKAGE.search(start.get("ai_message", "")))

    print(f"  session_id   : {session_id}")
    print(f"  attack_tag   : {start.get('attack_tag')}")
    print(f"  battle_phase : {start.get('battle_phase')}")
    print(f"  ai_message   : {start.get('ai_message', '')[:100]}...\n")

    # -------------------------------------------------------------------------
    # Steps 1..len(ANSWERS): send all answers, including past MAX_ROUNDS
    # -------------------------------------------------------------------------
    soft_limit_seen = False

    for i, answer in enumerate(ANSWERS):
        print(f"Step {i + 1}: POST /api/chat-round  answer={answer[:60]!r}")
        try:
            data = post("/api/chat-round", {"session_id": session_id, "user_message": answer})
        except Exception as exc:
            print(f"  FAIL  chat-round failed: {exc}")
            sys.exit(1)

        rnd   = data.get("round", 0)
        phase = data.get("battle_phase", "")
        sl    = data.get("soft_round_limit_reached", False)
        bc    = data.get("battle_complete", True)
        cc    = data.get("can_continue", False)
        na    = data.get("next_action", "")
        ai    = data.get("ai_message", "")

        print(f"  round={rnd}  phase={phase}  soft_limit={sl}  "
              f"battle_complete={bc}  can_continue={cc}")
        print(f"  ai_message: {ai[:100]}...\n")

        # Always must continue
        check("battle_complete=False (never hard-stopped)", bc is False, f"round={rnd}")
        check("can_continue=True (always)", cc is True, f"round={rnd}")
        check("next_action=continue (always)", na == "continue", f"got {na!r}")
        check("ai_message non-empty", bool(ai))
        check("no leakage in ai_message", not _LEAKAGE.search(ai),
              f"leakage at round {rnd}")

        # Soft limit
        if rnd >= MAX_ROUNDS:
            check("soft_round_limit_reached=True", sl is True, f"round={rnd}")
            if sl:
                soft_limit_seen = True
        else:
            check("soft_round_limit_reached=False", sl is False, f"round={rnd}")

        # Battle phase progression
        if 1 <= rnd <= 3:
            check(f"phase=explore at round {rnd}", phase == "explore", f"got {phase!r}")
        elif 4 <= rnd <= 6:
            check(f"phase=pressure at round {rnd}", phase == "pressure", f"got {phase!r}")
        elif rnd >= 7:
            check(f"phase=close at round {rnd}", phase == "close", f"got {phase!r}")

    check("soft_round_limit_reached appeared at least once", soft_limit_seen)

    # -------------------------------------------------------------------------
    # Final: POST /api/end-battle
    # -------------------------------------------------------------------------
    print(f"\nFinal: POST /api/end-battle (may take up to 3 minutes)")
    try:
        sc = post("/api/end-battle", {"session_id": session_id}, timeout=240)
    except Exception as exc:
        print(f"  FAIL  end-battle failed: {exc}")
        sys.exit(1)

    # Top-level fields
    check("overall present", "overall" in sc)
    check("overall_label present", "overall_label" in sc)
    check("scores present", "scores" in sc)
    check("scorecard_source present", "scorecard_source" in sc)
    check("model_ok present", "model_ok" in sc)

    overall = sc.get("overall", -1)
    check("overall 0-100", isinstance(overall, int) and 0 <= overall <= 100, f"got {overall!r}")
    check(
        "overall_label valid",
        sc.get("overall_label") in _VALID_LABELS,
        f"got {sc.get('overall_label')!r}",
    )

    # Dimension labels
    scores = sc.get("scores", {})
    check("all 6 dims present", REQUIRED_DIMS <= set(scores.keys()))
    for dim in REQUIRED_DIMS:
        d = scores.get(dim, {})
        check(f"{dim}.label valid", d.get("label") in _VALID_LABELS, f"got {d.get('label')!r}")
        dim_score = d.get("score", -1)
        check(f"{dim}.score 0-100", isinstance(dim_score, int) and 0 <= dim_score <= 100)

    # Scorecard source check (Phase 5D: hybrid architecture)
    source = sc.get("scorecard_source", "")
    _hybrid_sources = {"hybrid_claims_nemotron", "hybrid_claims_local"}
    check(
        "scorecard_source is hybrid",
        source in _hybrid_sources,
        f"got {source!r} — expected one of {_hybrid_sources}",
    )
    check(
        "provider is local or local+nvidia",
        sc.get("provider") in {"local+nvidia", "local"},
        f"got {sc.get('provider')!r}",
    )
    if source == "hybrid_claims_local":
        print(f"  NOTE: hybrid_claims_local — Nemotron coaching unavailable, local fallback used.")
        if sc.get("model_error"):
            print(f"  model_error: {sc.get('model_error')}")
    else:
        print("  NOTE: hybrid_claims_nemotron — Nemotron coaching succeeded.")

    print(f"\n--- Refinement Summary ---")
    print(f"  scorecard_source : {sc.get('scorecard_source')}")
    print(f"  overall          : {overall}  ({sc.get('overall_label')})")
    for dim in REQUIRED_DIMS:
        d = scores.get(dim, {})
        print(f"  {dim:<25}  {d.get('score', '?'):>3}  [{d.get('label', '?')}]")

    print("\nAll Phase 5B refinement checks passed.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
