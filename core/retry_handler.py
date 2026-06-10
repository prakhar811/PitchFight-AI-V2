"""Retry weakest-question drill handler (Phase 8)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from core.claim_extractor import extract_concrete_signals
from core.judge_settings import get_label, normalize_difficulty
from core.json_utils import parse_model_json, sanitize_for_log, _score_label
from core.scoring_engine import _sync_overall_to_dimensions
from core import model_router
from core.deal_verdict import build_judge_verdict

logger = logging.getLogger(__name__)

_VALID_VERDICTS = frozenset({"improved", "slightly_improved", "needs_more_work"})

_NON_ANSWER_RE = re.compile(
    r"^(ok|yeah|yes|no|idk|i don'?t know|not sure|maybe|n/?a)\.?$",
    re.IGNORECASE,
)

_DIM_RETRY_QUESTIONS: dict[str, str] = {
    "clarity": (
        "Explain your product again in one clear sentence. "
        "Who is it for, what does it do, and what outcome does it create?"
    ),
    "problem_understanding": (
        "Give one specific example that proves this user pain is real and repeated."
    ),
    "market_awareness": (
        "Name your first target segment and one number that proves this market is worth starting with."
    ),
    "differentiation": (
        "Why would someone choose your product over existing alternatives? "
        "Give one concrete mechanism or proof point."
    ),
    "business_model": (
        "Who pays, how much do they pay, and why does the math work?"
    ),
    "objection_handling": (
        "Answer the judge's objection directly using one specific number, example, or proof point."
    ),
}


def build_local_retry_question(answer_to_retry: dict) -> str:
    """Build a coaching retry question from dimension when original judge text is missing."""
    dim = str(answer_to_retry.get("dimension", "")).strip().lower()
    return _DIM_RETRY_QUESTIONS.get(
        dim,
        _DIM_RETRY_QUESTIONS["objection_handling"],
    )


def _find_original_question(
    session: dict,
    round_num: int | None,
    attack_tag: str,
) -> str:
    """Locate the judge question that prompted the weak answer."""
    history = session.get("history", [])
    if round_num and int(round_num) > 0:
        target = int(round_num)
        user_count = 0
        for idx, msg in enumerate(history):
            if msg.get("role") != "user":
                continue
            user_count += 1
            if user_count == target:
                for j in range(idx - 1, -1, -1):
                    if history[j].get("role") == "assistant":
                        return str(history[j].get("content", "")).strip()
                break

    tag_norm = str(attack_tag or "").lower().replace("_", " ").strip()
    if tag_norm:
        for msg in reversed(history):
            if msg.get("role") != "assistant":
                continue
            msg_tag = str(msg.get("attack_tag", "")).lower().replace("_", " ").strip()
            if msg_tag and (tag_norm in msg_tag or msg_tag in tag_norm):
                return str(msg.get("content", "")).strip()

    for msg in reversed(history):
        if msg.get("role") == "assistant":
            return str(msg.get("content", "")).strip()
    return ""


def _dimension_score(scorecard: dict, dimension: str) -> int:
    scores = scorecard.get("scores") or {}
    dim_data = scores.get(dimension) or {}
    try:
        return int(dim_data.get("score", 30))
    except (TypeError, ValueError):
        return 30


def start_retry_drill(session: dict) -> dict[str, Any]:
    """Prepare a retry drill from the latest scorecard answer_to_retry."""
    scorecard = session.get("latest_scorecard")
    if not scorecard:
        return {"error": "No scorecard found. End a battle before retrying."}

    se = scorecard.get("score_explanation") or {}
    atr = se.get("answer_to_retry") or {}
    dimension = str(atr.get("dimension", "")).strip()
    if not dimension:
        return {"error": "No answer to retry found in scorecard."}

    session_id = str(session.get("session_id", ""))
    attack_tag = str(atr.get("attack_tag", ""))
    round_num = atr.get("round")
    original_answer = str(atr.get("original_answer", ""))
    why_it_hurt = str(atr.get("why_it_hurt", ""))
    sample_stronger = str(atr.get("sample_stronger_answer", ""))

    original_question = _find_original_question(session, round_num, attack_tag)
    retry_question = original_question or build_local_retry_question(atr)

    difficulty_profile = session.get("difficulty_profile") or normalize_difficulty(
        session.get("difficulty", "practice")
    )
    difficulty_label = session.get("difficulty_label") or get_label(difficulty_profile)

    retry_id = str(uuid.uuid4())
    drill = {
        "retry_id": retry_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "scorecard_path_to_80",
        "dimension": dimension,
        "attack_tag": attack_tag,
        "original_question": original_question,
        "retry_question": retry_question,
        "original_answer": original_answer,
        "why_it_hurt": why_it_hurt,
        "sample_stronger_answer": sample_stronger,
        "input_mode": "",
        "retry_answer": "",
        "result": {},
        "dimension_score_before": _dimension_score(scorecard, dimension),
    }
    session.setdefault("retry_drills", {})[retry_id] = drill

    return {
        "session_id": session_id,
        "retry_id": retry_id,
        "retry_question": retry_question,
        "original_question": original_question,
        "original_answer": original_answer,
        "dimension": dimension,
        "attack_tag": attack_tag,
        "why_it_hurt": why_it_hurt,
        "sample_stronger_answer": sample_stronger,
        "difficulty_profile": difficulty_profile,
        "difficulty_label": difficulty_label,
    }


def _answer_has_signals(text: str) -> bool:
    sigs = extract_concrete_signals({
        "history": [{"role": "user", "content": text}],
        "startup": {},
    })
    return sigs.get("signal_count", 0) > 0 or bool(re.search(r"\d", text))


def build_local_retry_fallback(
    original_answer: str,
    retry_answer: str,
    dimension: str,
    dimension_before: int = 30,
) -> dict[str, Any]:
    """Local comparison when Nemotron is unavailable."""
    original = original_answer.strip()
    retry = retry_answer.strip()
    before = max(0, min(100, int(dimension_before)))

    if not retry or _NON_ANSWER_RE.match(retry) or len(retry.split()) < 4:
        after = before
        verdict = "needs_more_work"
        what_improved = "The retry answer was too brief or did not address the question."
        still_missing = "A specific fact, number, user example, or mechanism is still missing."
        tip = build_local_retry_question({"dimension": dimension})
    elif _answer_has_signals(retry) and len(retry) > len(original) + 8:
        gain = min(26, max(12, len(retry.split()) // 2))
        after = min(before + gain, 78)
        verdict = "improved" if gain >= 12 else "slightly_improved"
        what_improved = "You added concrete evidence or specifics that were missing before."
        still_missing = (
            "Tighten the answer further with one sharper proof point tied to the judge's question."
            if after < 55 else "Good progress — add one more proof point to make it investor-ready."
        )
        tip = f"Lead with your strongest number or example when answering {dimension.replace('_', ' ')} questions."
    elif len(retry) > len(original) + 4:
        after = min(before + 8, 58)
        verdict = "slightly_improved" if after > before else "needs_more_work"
        what_improved = "The retry answer is more complete, but proof is still thin."
        still_missing = "Add one number, named user segment, or competitor contrast."
        tip = build_local_retry_question({"dimension": dimension})
    else:
        after = before if len(retry) <= len(original) else min(before + 5, 50)
        verdict = "needs_more_work" if after == before else "slightly_improved"
        what_improved = "Some extra detail was added, but the core objection may still be open."
        still_missing = "Answer the exact question with one verifiable fact or example."
        tip = build_local_retry_question({"dimension": dimension})

    overall_lift = max(0, min(15, int((after - before) * 0.45)))
    if overall_lift < 4 and after > before:
        overall_lift = 4

    return {
        "comparison": {
            "old_answer_summary": original[:200] or "No substantive prior answer.",
            "new_answer_summary": retry[:200],
            "what_improved": what_improved,
            "still_missing": still_missing,
            "specific_tip": tip,
            "estimated_dimension_before": before,
            "estimated_dimension_after": after,
            "estimated_overall_lift": overall_lift,
            "verdict": verdict,
        },
        "next_practice_prompt": build_local_retry_question({"dimension": dimension}),
    }


def _build_retry_comparison_messages(
    session: dict,
    drill: dict,
    retry_answer: str,
) -> list[dict[str, str]]:
    startup = session.get("startup", {}) or {}
    scorecard = session.get("latest_scorecard") or {}
    difficulty_profile = session.get("difficulty_profile") or "practice"
    difficulty_label = session.get("difficulty_label") or get_label(difficulty_profile)
    dim = drill.get("dimension", "")
    dim_before = drill.get("dimension_score_before", _dimension_score(scorecard, dim))

    startup_lines = [
        f"Name: {startup.get('name', '')}",
        f"Problem: {startup.get('problem', '')}",
        f"Solution: {startup.get('solution', '')}",
        f"Traction: {startup.get('traction', '')}",
    ]

    system = (
        "You are a startup pitch coach comparing an old weak answer to a new retry answer.\n"
        "You are NOT rescoring the whole battle — only one dimension.\n"
        "Be specific and coaching-oriented. Do not overpraise. Do not hallucinate facts.\n"
        "Use only the provided text. Return ONLY valid JSON.\n\n"
        "REQUIRED JSON:\n"
        '{"comparison":{"old_answer_summary":"","new_answer_summary":"","what_improved":"",'
        '"still_missing":"","specific_tip":"","estimated_dimension_before":0,'
        '"estimated_dimension_after":0,"estimated_overall_lift":0,'
        '"verdict":"improved|slightly_improved|needs_more_work"},'
        '"next_practice_prompt":""}\n\n'
        "Rules:\n"
        f"- estimated_dimension_before should be near {dim_before}.\n"
        "- estimated_dimension_after must be realistic (do not jump above 75 unless strong proof).\n"
        "- estimated_overall_lift usually 3–12 points.\n"
        "- Each text field: 1–2 sentences max.\n"
        "- next_practice_prompt: one coaching question only.\n"
        "- verdict must be improved, slightly_improved, or needs_more_work."
    )

    user = (
        f"Difficulty: {difficulty_label} ({difficulty_profile})\n"
        f"Dimension: {dim}\n"
        f"Attack tag: {drill.get('attack_tag', '')}\n\n"
        f"Startup context:\n" + "\n".join(startup_lines) + "\n\n"
        f"Original judge question:\n{drill.get('original_question') or drill.get('retry_question', '')}\n\n"
        f"Retry question:\n{drill.get('retry_question', '')}\n\n"
        f"Original weak answer:\n{drill.get('original_answer', '')}\n\n"
        f"Why it hurt:\n{drill.get('why_it_hurt', '')}\n\n"
        f"Sample stronger direction:\n{drill.get('sample_stronger_answer', '')}\n\n"
        f"New retry answer:\n{retry_answer}\n"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _normalize_comparison_result(
    parsed: dict,
    drill: dict,
    original_answer: str,
    retry_answer: str,
) -> dict[str, Any]:
    comp = parsed.get("comparison") if isinstance(parsed.get("comparison"), dict) else parsed
    if not isinstance(comp, dict):
        raise ValueError("missing comparison object")

    before = drill.get("dimension_score_before", 30)
    try:
        est_before = int(comp.get("estimated_dimension_before", before))
    except (TypeError, ValueError):
        est_before = before
    try:
        est_after = int(comp.get("estimated_dimension_after", est_before))
    except (TypeError, ValueError):
        est_after = est_before

    est_before = max(0, min(100, est_before))
    est_after = max(est_before, min(82, est_after))
    if est_after < est_before:
        est_after = est_before

    verdict = str(comp.get("verdict", "needs_more_work")).strip().lower()
    if verdict not in _VALID_VERDICTS:
        verdict = "slightly_improved" if est_after > est_before else "needs_more_work"

    try:
        lift = int(comp.get("estimated_overall_lift", 0))
    except (TypeError, ValueError):
        lift = max(0, int((est_after - est_before) * 0.35))
    lift = max(0, min(15, lift))
    if est_after > est_before and lift < 4:
        lift = 4

    return {
        "comparison": {
            "old_answer_summary": str(comp.get("old_answer_summary", original_answer[:200]))[:300],
            "new_answer_summary": str(comp.get("new_answer_summary", retry_answer[:200]))[:300],
            "what_improved": str(comp.get("what_improved", ""))[:300],
            "still_missing": str(comp.get("still_missing", ""))[:300],
            "specific_tip": str(comp.get("specific_tip", ""))[:300],
            "estimated_dimension_before": est_before,
            "estimated_dimension_after": est_after,
            "estimated_overall_lift": lift,
            "verdict": verdict,
        },
        "next_practice_prompt": str(
            parsed.get("next_practice_prompt")
            or build_local_retry_question({"dimension": drill.get("dimension", "")})
        )[:300],
    }


def call_nemotron_retry_comparison(
    session: dict,
    drill: dict,
    retry_answer: str,
    model_mode: str | None = None,
) -> dict[str, Any] | None:
    """Call Nemotron to compare old vs new retry answer. Returns None on failure."""
    messages = _build_retry_comparison_messages(session, drill, retry_answer)
    resolved = model_mode or session.get("model_mode") or "premium_nvidia"
    result = model_router.generate_retry_comparison_response(messages, model_mode=resolved)
    if not result.get("ok") or not result.get("content"):
        logger.warning("retry_handler: Nemotron comparison failed — %s", result.get("error"))
        return None

    raw = result["content"]
    parsed, _ = parse_model_json(raw)
    if not isinstance(parsed, dict) or not parsed:
        repair = model_router.generate_retry_comparison_repair_response(raw, model_mode=resolved)
        if repair.get("ok") and repair.get("content"):
            parsed, _ = parse_model_json(repair["content"])
    if not isinstance(parsed, dict) or not parsed:
        logger.warning(
            "retry_handler: comparison JSON parse failed preview=%r",
            sanitize_for_log(raw),
        )
        return None

    try:
        return _normalize_comparison_result(
            parsed, drill, drill.get("original_answer", ""), retry_answer
        )
    except ValueError as exc:
        logger.warning("retry_handler: comparison normalize failed — %s", exc)
        return None


def apply_retry_to_scorecard(
    session: dict,
    drill: dict,
    comparison: dict,
) -> dict[str, Any] | None:
    """Apply retry improvement to stored scorecard so UI reflects the new score."""
    scorecard = session.get("latest_scorecard")
    if not scorecard or not isinstance(scorecard, dict):
        return None

    dim = str(drill.get("dimension", "")).strip()
    if not dim:
        return None

    try:
        after_dim = int(comparison.get("estimated_dimension_after", 0))
        lift = int(comparison.get("estimated_overall_lift", 0))
    except (TypeError, ValueError):
        return None

    verdict = str(comparison.get("verdict", "")).lower()
    if verdict == "needs_more_work" and after_dim <= int(drill.get("dimension_score_before", 0)):
        return scorecard

    scores = scorecard.get("scores") or {}
    dim_data = scores.get(dim)

    # Capture the overall and dimension-sum BEFORE the update so we can apply the
    # improvement as a delta. This preserves any offset baked into the displayed overall
    # (e.g. the Practice nudge) instead of silently dropping it on a pure-mean recompute —
    # which previously made a real dimension gain look like "overall didn't change".
    old_overall = int(scorecard.get("overall", 0) or 0)
    n_dims = len(scores) or 1
    old_sum = sum(int(v.get("score", 0)) for v in scores.values())

    updated = False
    if isinstance(dim_data, dict) and after_dim > int(dim_data.get("score", 0)):
        dim_data = dict(dim_data)
        dim_data["score"] = after_dim
        dim_data["label"] = _score_label(after_dim)
        improved = str(comparison.get("what_improved", "")).strip()
        if improved:
            dim_data["reason"] = improved[:280]
        retry_text = str(drill.get("retry_answer", "")).strip()
        if retry_text:
            dim_data["quote"] = retry_text[:200]
        scores[dim] = dim_data
        scorecard["scores"] = scores
        updated = True

    if updated:
        new_sum = sum(int(v.get("score", 0)) for v in scores.values())
        delta = round((new_sum - old_sum) / n_dims)
        new_overall = max(0, min(100, old_overall + delta))
        scorecard["overall"] = new_overall
        scorecard["overall_label"] = _score_label(new_overall)
        # Real lift the UI can trust (matches the overall it now displays).
        actual_lift = new_overall - old_overall
    else:
        new_overall = old_overall
        actual_lift = 0

    se = dict(scorecard.get("score_explanation") or {})
    esif = dict(se.get("estimated_score_if_fixed") or {})
    esif["current_overall"] = new_overall
    esif["estimated_new_overall"] = min(95, max(new_overall + 4, int(esif.get("estimated_new_overall", new_overall))))
    se["estimated_score_if_fixed"] = esif
    atr = dict(se.get("answer_to_retry") or {})
    if drill.get("retry_answer"):
        atr["original_answer"] = str(drill["retry_answer"])[:300]
    se["answer_to_retry"] = atr
    scorecard["score_explanation"] = se

    if drill.get("retry_answer"):
        scorecard["weakest_answer"] = str(drill["retry_answer"])[:400]

    scorecard["retry_applied"] = True
    scorecard["retry_dimension"] = dim
    scorecard["retry_overall_lift"] = actual_lift
    session["latest_scorecard"] = scorecard
    return scorecard


def evaluate_retry_answer(
    session: dict,
    retry_id: str,
    retry_answer: str,
    input_mode: str = "text",
    voice_turn_id: str = "",
) -> dict[str, Any]:
    """Evaluate a retry answer and store the result on the session."""
    session_id = str(session.get("session_id", ""))
    drills = session.get("retry_drills") or {}
    drill = drills.get(retry_id)
    if not drill:
        return {"error": "Retry drill not found. Start a new retry from the scorecard."}

    answer = str(retry_answer or "").strip()
    if not answer:
        return {"error": "Retry answer cannot be empty."}

    drill["retry_answer"] = answer
    drill["input_mode"] = input_mode or "text"
    if voice_turn_id:
        drill["voice_turn_id"] = voice_turn_id

    comparison_result = call_nemotron_retry_comparison(session, drill, answer)
    if comparison_result is None:
        comparison_result = build_local_retry_fallback(
            drill.get("original_answer", ""),
            answer,
            drill.get("dimension", "objection_handling"),
            drill.get("dimension_score_before", 30),
        )

    drill["result"] = comparison_result
    comp = comparison_result.get("comparison", {})
    updated_scorecard = apply_retry_to_scorecard(session, drill, comp)

    response: dict[str, Any] = {
        "session_id": session_id,
        "retry_id": retry_id,
        "dimension": drill.get("dimension", ""),
        "attack_tag": drill.get("attack_tag", ""),
        "original_question": drill.get("original_question", ""),
        "retry_question": drill.get("retry_question", ""),
        "original_answer": drill.get("original_answer", ""),
        "retry_answer": answer,
        "comparison": comp,
        "next_practice_prompt": comparison_result.get("next_practice_prompt", ""),
    }
    if updated_scorecard:
        response["updated_scorecard"] = updated_scorecard
        try:
            verdict = build_judge_verdict(session, updated_scorecard, local_only=True)
            session["judge_verdict"] = verdict
            response["judge_verdict"] = verdict
        except Exception as exc:
            logger.warning("retry_handler: could not refresh judge verdict — %s", exc)
    return response
