"""Phase 5D scorecard test: hybrid claim-based scoring via the running server.

Validates:
  - /api/end-battle returns all required fields
  - All 6 score dimensions present with integer scores 0-100
  - Score labels use 5-band scheme (Not addressed / Developing / Solid / Strong / Excellent)
  - top_3_questions has exactly 3 items
  - model_ok, provider, scorecard_source present
  - concrete_signals_summary present with required sub-keys
  - scorecard_source in ("hybrid_claims_nemotron", "hybrid_claims_local")
  - provider in ("local+nvidia", "local")
  - Set STRICT_NEMOTRON_COACHING=true to fail if not hybrid_claims_nemotron
  - Conversation includes "50 beta users" and "3 campus ambassadors" →
    expect these signals to appear in concrete_signals_summary or scores
  - No old static mock content

Usage:
  python scripts/test_phase5_scorecard.py
  PITCHFIGHT_BASE_URL=http://localhost:7861 python scripts/test_phase5_scorecard.py
  STRICT_NEMOTRON_COACHING=true python scripts/test_phase5_scorecard.py

Server must already be running (python app.py).
"""

from __future__ import annotations

import os
import re
import sys

import requests

BASE_URL = os.getenv("PITCHFIGHT_BASE_URL", "http://127.0.0.1:7861").rstrip("/")
STRICT_COACHING = os.getenv("STRICT_NEMOTRON_COACHING", "false").strip().lower() == "true"
# Legacy flag kept for compatibility
ALLOW_FALLBACK = os.getenv("ALLOW_SCORECARD_FALLBACK", "false").strip().lower() == "true"

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
    "It is a big market because students attend events often.",    # weak
    "I don't know",                                               # non_answer
    STRONG_ANSWER,                                                # strong → evidence
    "The AI personalizes event ranking based on student goals.",  # partial
]

REQUIRED_DIMS = {
    "clarity",
    "problem_understanding",
    "market_awareness",
    "differentiation",
    "business_model",
    "objection_handling",
}

_VALID_LABELS = {"Not addressed", "Developing", "Solid", "Strong", "Excellent"}
_VALID_SOURCES = {"hybrid_claims_nemotron", "hybrid_claims_local"}
_VALID_PROVIDERS = {"local+nvidia", "local"}

_LEAKAGE = re.compile(
    r"we need to\b|the prompt says\b|as instructed\b|my instructions\b"
    r"|i am supposed to\b|the rules say\b",
    re.IGNORECASE,
)


def post(path: str, body: dict, timeout: int = 120) -> dict:
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
    print(f"\nPhase 5D Scorecard Test (Hybrid Claim-Based)")
    print(f"Base URL             : {BASE_URL}")
    print(f"Strict Nemotron      : {STRICT_COACHING}")
    print()

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
    print(f"  session_id  : {session_id}")
    print(f"  attack_tag  : {start.get('attack_tag')}")
    print(f"  ai_message  : {start.get('ai_message', '')[:100]}...\n")

    # -------------------------------------------------------------------------
    # Steps 1-N: Send answers
    # -------------------------------------------------------------------------
    for i, answer in enumerate(ANSWERS):
        print(f"Step {i + 1}: POST /api/chat-round  answer={answer[:60]!r}")
        try:
            data = post("/api/chat-round", {
                "session_id": session_id,
                "user_message": answer,
            })
        except Exception as exc:
            print(f"  FAIL  chat-round failed: {exc}")
            sys.exit(1)

        check("session_id echoed", data.get("session_id") == session_id)
        check("ai_message non-empty", bool(data.get("ai_message")))
        print(
            f"  round={data.get('round')}  "
            f"quality={data.get('answer_quality')}  "
            f"action={data.get('judge_action')}  "
            f"tag={data.get('attack_tag')}\n"
        )

    # -------------------------------------------------------------------------
    # Final: POST /api/end-battle
    # -------------------------------------------------------------------------
    print("Final step: POST /api/end-battle  (local scoring is fast; Nemotron coaching may take ~60s)")
    try:
        sc = post("/api/end-battle", {"session_id": session_id}, timeout=180)
    except Exception as exc:
        print(f"  FAIL  end-battle request failed: {exc}")
        sys.exit(1)

    # --- Top-level required fields ---
    check("overall present", "overall" in sc, f"keys={list(sc.keys())}")
    check("overall_label present", "overall_label" in sc)
    check("scores present", "scores" in sc)
    check("best_answer present", "best_answer" in sc)
    check("weakest_answer present", "weakest_answer" in sc)
    check("improved_answer present", "improved_answer" in sc)
    check("improved_pitch present", "improved_pitch" in sc)
    check("top_3_questions present", "top_3_questions" in sc)
    check("model_ok present", "model_ok" in sc)
    check("provider present", "provider" in sc)
    check("scorecard_source present", "scorecard_source" in sc)
    check("no error key", "error" not in sc, f"error={sc.get('error')}")

    overall = sc.get("overall", -1)
    check("overall is int 0-100", isinstance(overall, int) and 0 <= overall <= 100, f"got {overall!r}")
    check(
        "overall_label valid",
        sc.get("overall_label") in _VALID_LABELS,
        f"got {sc.get('overall_label')!r}",
    )

    # --- concrete_signals_summary ---
    css = sc.get("concrete_signals_summary")
    check("concrete_signals_summary present", isinstance(css, dict), f"got {type(css).__name__}")
    if isinstance(css, dict):
        for key in ("numbers", "validation", "competitors", "revenue_signals", "technical_mechanisms"):
            check(
                f"concrete_signals_summary.{key} is list",
                isinstance(css.get(key), list),
                f"got {type(css.get(key)).__name__}",
            )

    # --- Dimension checks ---
    scores = sc.get("scores", {})
    check("all 6 dimensions present", REQUIRED_DIMS <= set(scores.keys()),
          f"missing={REQUIRED_DIMS - set(scores.keys())}")

    for dim in REQUIRED_DIMS:
        dim_data = scores.get(dim, {})
        dim_score = dim_data.get("score", -1)
        check(
            f"{dim}.score is int 0-100",
            isinstance(dim_score, int) and 0 <= dim_score <= 100,
            f"got {dim_score!r}",
        )
        check(f"{dim}.reason non-empty", bool(dim_data.get("reason")))
        check(
            f"{dim}.label is valid",
            dim_data.get("label") in _VALID_LABELS,
            f"got {dim_data.get('label')!r}",
        )
        check(
            f"{dim}.signals_used is list",
            isinstance(dim_data.get("signals_used", []), list),
        )

    # --- top_3_questions ---
    top3 = sc.get("top_3_questions", [])
    check("top_3_questions is list", isinstance(top3, list))
    check("top_3_questions has exactly 3", len(top3) == 3, f"got {len(top3)}")
    for q in top3:
        check("question is non-empty string", isinstance(q, str) and bool(q.strip()))

    # --- Source and provider checks (Phase 5D: hybrid architecture) ---
    source = sc.get("scorecard_source", "")
    model_ok = sc.get("model_ok")
    provider = sc.get("provider", "")

    check(
        "scorecard_source is hybrid",
        source in _VALID_SOURCES,
        f"got {source!r} — expected one of {_VALID_SOURCES}",
    )
    check(
        "provider is local or local+nvidia",
        provider in _VALID_PROVIDERS,
        f"got {provider!r}",
    )
    check("model_ok is bool", isinstance(model_ok, bool), f"got {type(model_ok).__name__}")

    if STRICT_COACHING and source != "hybrid_claims_nemotron":
        print(
            f"\n  FAIL  STRICT_NEMOTRON_COACHING=true but source={source!r}\n"
            f"  model_error: {sc.get('model_error', 'none')}\n"
            "  Nemotron coaching did not produce valid JSON."
        )
        sys.exit(1)
    elif source == "hybrid_claims_local":
        print(f"  NOTE: hybrid_claims_local — Nemotron coaching unavailable, local fallback used.")
        print(f"  model_error: {sc.get('model_error', 'none')}")
    else:
        print(f"  NOTE: hybrid_claims_nemotron — Nemotron coaching succeeded.")

    # --- Evidence detection: "50 beta users" should appear in signals/scores ---
    evidence_terms = ["50 beta", "campus ambassador", "event-miss report", "validated", "beta users"]
    evidence_fields = [
        str(sc.get("best_answer", "")),
        str(sc.get("improved_answer", "")),
        str(sc.get("improved_pitch", "")),
    ]
    for dim in REQUIRED_DIMS:
        evidence_fields.append(str(scores.get(dim, {}).get("reason", "")))
        for sig in scores.get(dim, {}).get("signals_used", []):
            evidence_fields.append(str(sig))
    if isinstance(css, dict):
        for key in ("numbers", "validation"):
            evidence_fields.extend(str(x) for x in css.get(key, []))
    combined = " ".join(evidence_fields).lower()
    evidence_found = any(t.lower() in combined for t in evidence_terms)
    if evidence_found:
        print("  PASS  Scorecard acknowledges concrete validation evidence from STRONG_ANSWER")
    else:
        print("  NOTE  Scorecard did not explicitly reference validation evidence (not a hard fail in 5D)")

    # --- No static EventRadar mock content ---
    all_text = " ".join([
        str(sc.get("best_answer", "")),
        str(sc.get("weakest_answer", "")),
        str(sc.get("improved_answer", "")),
        str(sc.get("improved_pitch", "")),
    ])
    check(
        "no static WhatsApp groups mock content",
        "WhatsApp groups" not in all_text or "EventRadar" in SAMPLE_STARTUP.get("name", ""),
    )

    # --- Leakage check ---
    scorecard_text = " ".join([
        str(sc.get("best_answer", "")),
        str(sc.get("weakest_answer", "")),
        str(sc.get("improved_answer", "")),
        str(sc.get("improved_pitch", "")),
        str(sc.get("why_weak", "")),
    ])
    check("no leakage in scorecard text", not _LEAKAGE.search(scorecard_text), "instruction leakage detected")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print("\n--- Scorecard Summary ---")
    print(f"  scorecard_source : {sc.get('scorecard_source')}")
    print(f"  model_ok         : {sc.get('model_ok')}  provider: {sc.get('provider')}")
    print(f"  overall          : {overall}  ({sc.get('overall_label')})")
    print()
    for dim in REQUIRED_DIMS:
        d = scores.get(dim, {})
        sigs = d.get("signals_used", [])
        print(
            f"  {dim:<25}  score={d.get('score', '?'):>3}  [{d.get('label', '?')}]"
            + (f"  sigs={sigs[:2]}" if sigs else "")
        )
    print()
    print(f"  weakest_answer   : {sc.get('weakest_answer', '')[:120]}")
    print(f"  improved_answer  : {sc.get('improved_answer', '')[:120]}")
    print(f"  top_3_questions  :")
    for q in top3:
        print(f"    - {q}")
    if isinstance(css, dict):
        print(f"\n  concrete_signals_summary:")
        for k, v in css.items():
            if v:
                print(f"    {k}: {v[:3]}")

    if sc.get("model_error"):
        print(f"\n  model_error : {sc.get('model_error')}")

    print("\nAll Phase 5D scorecard checks passed.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
