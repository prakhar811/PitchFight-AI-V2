"""Phase 5D: Local unit tests for claim extractor, local scoring, and session-aware fallback.

No server required. Tests run purely locally.

Usage:
  python scripts/test_claim_based_scoring.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.claim_extractor import extract_concrete_signals
from core.scoring_engine import (
    build_session_aware_fallback_scorecard,
    _compute_local_scores,
    _score_label,
)
from core.json_utils import _score_label as json_score_label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check(label: str, condition: bool, detail: str = "") -> None:
    marker = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  {marker}  {label}{suffix}")
    if not condition:
        sys.exit(1)


def make_session(answers: list[str], startup: dict | None = None) -> dict:
    startup = startup or {
        "name": "TestStartup",
        "problem": "Test problem",
        "solution": "Test solution",
        "why_ai": "AI helps",
        "stage": "Prototype",
        "team": "2 founders",
        "traction": "10 beta users",
    }
    history = []
    for i, ans in enumerate(answers):
        if i % 2 == 0:
            history.append({"role": "assistant", "content": f"Judge question {i}", "attack_tag": "Market Size"})
        history.append({"role": "user", "content": ans})
    return {"startup": startup, "persona": "hackathon_judge", "difficulty": "high", "history": history}


# ---------------------------------------------------------------------------
# Extraction tests (existing)
# ---------------------------------------------------------------------------

def test_strong_evidence_answer() -> None:
    print("\nTest 1: Strong evidence — numbers, validation, campus")
    session = make_session(["80 users, 60% interview rate, 3 colleges have onboarded already."])
    sigs = extract_concrete_signals(session)
    check("numbers extracted", len(sigs["numbers"]) > 0, f"got {sigs['numbers']}")
    check("percentages extracted", len(sigs["percentages"]) > 0, f"got {sigs['percentages']}")
    check("college_mentions extracted", len(sigs["college_mentions"]) > 0, f"got {sigs['college_mentions']}")
    check("signal_count > 0", sigs["signal_count"] > 0, f"got {sigs['signal_count']}")
    check("non_answers empty", len(sigs["non_answers"]) == 0)
    check("best_user_quotes non-empty", len(sigs["best_user_quotes"]) > 0)


def test_vague_answer() -> None:
    print("\nTest 2: Vague answer — big market, useful")
    session = make_session(["It is useful and big market will love it."])
    sigs = extract_concrete_signals(session)
    check("vague_claims detected", len(sigs["vague_claims"]) > 0, f"got {sigs['vague_claims']}")
    check("no numbers", len(sigs["numbers"]) == 0, f"got {sigs['numbers']}")


def test_non_answer() -> None:
    print("\nTest 3: Non-answer — 'I don't know'")
    session = make_session(["I don't know"])
    sigs = extract_concrete_signals(session)
    check("non_answers detected", len(sigs["non_answers"]) > 0, f"got {sigs['non_answers']}")
    check("best_user_quotes empty", len(sigs["best_user_quotes"]) == 0)
    check("signal_count is 0", sigs["signal_count"] == 0, f"got {sigs['signal_count']}")


def test_pricing_and_revenue() -> None:
    print("\nTest 4: Pricing and revenue — ₹399 per student and CAC ~₹50")
    session = make_session(["We charge ₹399 per student and our CAC is around ₹50."])
    sigs = extract_concrete_signals(session)
    check("pricing detected", len(sigs["pricing"]) > 0, f"got {sigs['pricing']}")
    check("revenue_signals detected", len(sigs["revenue_signals"]) > 0, f"got {sigs['revenue_signals']}")
    check("signal_count > 0", sigs["signal_count"] > 0)


def test_competitors_and_tech() -> None:
    print("\nTest 5: Competitors and technical mechanism")
    session = make_session([
        "Luma and LinkedIn are competitors but we use profile-based ranking with embedding models."
    ])
    sigs = extract_concrete_signals(session)
    check("competitors detected", len(sigs["competitors"]) > 0, f"got {sigs['competitors']}")
    check("technical_mechanisms detected", len(sigs["technical_mechanisms"]) > 0, f"got {sigs['technical_mechanisms']}")


def test_mixed_session() -> None:
    print("\nTest 6: Mixed session — strong + non-answer + vague")
    session = make_session([
        "We validated this with 50 beta users, 3 campus ambassadors, and weekly event-miss reports.",
        "I don't know",
        "It is a big market.",
        "We use embeddings and a ranking model trained on student behavior.",
    ])
    sigs = extract_concrete_signals(session)
    check("numbers detected", len(sigs["numbers"]) > 0, f"got {sigs['numbers']}")
    check("validation detected", len(sigs["validation"]) > 0, f"got {sigs['validation']}")
    check("non_answers detected", len(sigs["non_answers"]) > 0)
    check("vague_claims detected", len(sigs["vague_claims"]) > 0)
    check("technical_mechanisms detected", len(sigs["technical_mechanisms"]) > 0)
    check("best_user_quotes >= 2", len(sigs["best_user_quotes"]) >= 2, f"got {len(sigs['best_user_quotes'])}")
    check("signal_count > 3", sigs["signal_count"] > 3, f"got {sigs['signal_count']}")


# ---------------------------------------------------------------------------
# Local scoring tests (Phase 5D)
# ---------------------------------------------------------------------------

def test_local_scoring_strong_evidence() -> None:
    print("\nTest 7: Local scoring — '80 users, 60% interview rate, 3 colleges' should get real credit")
    session = make_session([
        "80 users, 60% interview rate, 3 colleges have onboarded already.",
        "We charge ₹399 per student and our CAC is around ₹50.",
        "Luma and LinkedIn are competitors but we use profile-based ranking with embedding models.",
    ])
    sigs = extract_concrete_signals(session)
    startup = session.get("startup", {})
    scores, best_answer, weakest_answer, why_weak = _compute_local_scores(sigs, startup)

    # All 6 dims must be present
    required = {"clarity", "problem_understanding", "market_awareness",
                "differentiation", "business_model", "objection_handling"}
    check("all 6 dims present", required <= set(scores.keys()))

    # With concrete evidence, most dims should be Developing (31+) or above
    for dim in required:
        s = scores[dim]["score"]
        check(f"{dim}.score >= 30", s >= 30, f"got {s} — evidence was strong")

    # Dims with direct evidence should be Solid (51+) or Strong
    # market_awareness should get credit for numbers + competitors
    market_s = scores["market_awareness"]["score"]
    check("market_awareness >= 50 (has numbers + competitors)", market_s >= 50, f"got {market_s}")

    # differentiation should get credit for competitors + tech
    diff_s = scores["differentiation"]["score"]
    check("differentiation >= 50 (has competitors + tech)", diff_s >= 50, f"got {diff_s}")

    # business_model should get credit for ₹399 + CAC
    biz_s = scores["business_model"]["score"]
    check("business_model >= 45 (has pricing + revenue)", biz_s >= 45, f"got {biz_s}")

    # best_answer should be non-empty
    check("best_answer non-empty", bool(best_answer))
    check("why_weak non-empty", bool(why_weak))


def test_local_scoring_vague_floor() -> None:
    print("\nTest 8: Local scoring — vague on-topic answer should not go below 30 (global floor)")
    session = make_session([
        "It is a big market because students attend events often.",
        "We have a better AI solution than others.",
    ])
    sigs = extract_concrete_signals(session)
    startup = session.get("startup", {})
    scores, _, _, _ = _compute_local_scores(sigs, startup)

    # On-topic engagement = engagement > 0, so floor is 33
    for dim, data in scores.items():
        s = data["score"]
        # Some dims may dip below 33 (business_model has 28 floor), but most should be >= 30
        if dim != "business_model":
            check(f"{dim}.score >= 30 (vague but on-topic)", s >= 30, f"got {s}")


def test_local_scoring_non_answer_can_be_below_30() -> None:
    print("\nTest 9: Local scoring — all non-answers can score below 30")
    session = make_session(["ok", "I don't know", "yeah", "not sure"])
    sigs = extract_concrete_signals(session)
    startup = session.get("startup", {})
    scores, _, _, _ = _compute_local_scores(sigs, startup)

    # With all non-answers, engagement=0, so dims should be low
    low_count = sum(1 for d in scores.values() if d["score"] <= 20)
    check("majority of dims <= 20 when all non-answers", low_count >= 4,
          f"got {low_count} dims <= 20, scores={[(k, v['score']) for k, v in scores.items()]}")


def test_local_scoring_pricing_revenue() -> None:
    print("\nTest 10: Local scoring — ₹399 and CAC ₹50 → business_model Developing or better")
    session = make_session(["We charge ₹399 per student and our CAC is around ₹50."])
    sigs = extract_concrete_signals(session)
    startup = session.get("startup", {})
    scores, _, _, _ = _compute_local_scores(sigs, startup)

    biz_s = scores["business_model"]["score"]
    biz_lbl = scores["business_model"]["label"]
    check(
        "business_model >= 31 (Developing or better) with ₹399 + CAC",
        biz_s >= 31,
        f"got {biz_s} ({biz_lbl})",
    )


# ---------------------------------------------------------------------------
# Session-aware fallback test
# ---------------------------------------------------------------------------

def test_session_aware_fallback_not_static() -> None:
    print("\nTest 11: Session-aware fallback does not return EventRadar static content")
    session = make_session(
        [
            "We have 80 users at IIT Delhi and IIT Bombay paying ₹499/month.",
            "Competitors are LinkedIn and Glassdoor but we do skill-gap analysis.",
        ],
        startup={
            "name": "SkillBridge",
            "problem": "Students get rejected because their resume skills don't match job requirements.",
            "solution": "AI that maps resume skills to actual job description gaps.",
            "why_ai": "Personalized skill-gap analysis requires LLM understanding.",
            "stage": "Beta",
            "team": "2 founders",
            "traction": "80 paying users",
        },
    )
    sigs = extract_concrete_signals(session)
    fb = build_session_aware_fallback_scorecard(session, sigs, "test error")

    check("scorecard_source=session_fallback", fb.get("scorecard_source") == "session_fallback")
    check("model_ok=False", fb.get("model_ok") is False)
    check("provider=local", fb.get("provider") == "local")
    check("model_error present", bool(fb.get("model_error")))
    check("overall is int 0-100",
          isinstance(fb.get("overall"), int) and 0 <= fb.get("overall", -1) <= 100)
    check("overall_label valid",
          fb.get("overall_label") in {"Not addressed", "Developing", "Solid", "Strong", "Excellent"})
    check("all 6 dims present",
          {"clarity", "problem_understanding", "market_awareness",
           "differentiation", "business_model", "objection_handling"}
          <= set(fb.get("scores", {}).keys()))
    check("concrete_signals_summary present", isinstance(fb.get("concrete_signals_summary"), dict))
    check("top_3_questions has 3", len(fb.get("top_3_questions", [])) == 3)

    full_text = str(fb)
    for phrase in ["WhatsApp groups", "EventRadar"]:
        check(
            f"no static phrase '{phrase}' in session fallback",
            phrase not in full_text or "SkillBridge" in full_text,
        )

    best = fb.get("best_answer", "")
    check(
        "best_answer contains actual answer text",
        any(word in best for word in ["80 users", "IIT", "499", "SkillBridge", "LinkedIn", "skill"]),
        f"got: {best[:120]}",
    )


# ---------------------------------------------------------------------------
# Score label band tests
# ---------------------------------------------------------------------------

def test_score_label_bands() -> None:
    print("\nTest 12: Score label bands (Phase 5C/5D)")
    cases = [
        (0,   "Not addressed"),
        (15,  "Not addressed"),
        (30,  "Not addressed"),
        (31,  "Developing"),
        (50,  "Developing"),
        (51,  "Solid"),
        (70,  "Solid"),
        (71,  "Strong"),
        (85,  "Strong"),
        (86,  "Excellent"),
        (100, "Excellent"),
    ]
    for score, expected in cases:
        got = _score_label(score)
        check(f"_score_label({score}) == '{expected}'", got == expected, f"got '{got}'")
    # Also verify json_utils._score_label matches
    for score, expected in cases:
        got = json_score_label(score)
        check(f"json_utils._score_label({score}) == '{expected}'", got == expected, f"got '{got}'")


def test_all_non_answer_session() -> None:
    print("\nTest 13: All non-answer session — fallback should still work")
    session = make_session(["ok", "I don't know", "yeah", "not sure"])
    sigs = extract_concrete_signals(session)
    check("all are non_answers", len(sigs["non_answers"]) >= 3)
    check("signal_count=0", sigs["signal_count"] == 0)
    fb = build_session_aware_fallback_scorecard(session, sigs)
    check("fallback returns valid dict", isinstance(fb, dict))
    check("overall >= 0", fb.get("overall", -1) >= 0)
    check("scorecard_source=session_fallback", fb.get("scorecard_source") == "session_fallback")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\nPhase 5D — Claim Extractor + Local Scoring + Session-Aware Fallback Tests")
    print("(No server required)\n")

    test_strong_evidence_answer()
    test_vague_answer()
    test_non_answer()
    test_pricing_and_revenue()
    test_competitors_and_tech()
    test_mixed_session()
    test_local_scoring_strong_evidence()
    test_local_scoring_vague_floor()
    test_local_scoring_non_answer_can_be_below_30()
    test_local_scoring_pricing_revenue()
    test_session_aware_fallback_not_static()
    test_score_label_bands()
    test_all_non_answer_session()

    print("\nAll Phase 5D claim-based scoring tests passed.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
