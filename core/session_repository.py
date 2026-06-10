"""
MongoDB session repository for PitchFight AI.

Phase 9.5 rules:
- MongoDB is optional background persistence only.
- In-memory session_manager remains the live source of truth.
- Every repository operation is best-effort.
- MongoDB failure must never crash API handlers.
- Never store API keys, raw audio/base64, uploaded files, or model reasoning_content.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from core.db import get_sessions_collection, is_mongodb_enabled


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "nvidia_api_key",
    "openai_api_key",
    "secret",
    "password",
    "mongodb_uri",
    "mongo_uri",
    "uri",
    "audio",
    "audio_base64",
    "raw_audio",
    "base64_audio",
    "uploaded_file",
    "uploaded_files",
    "file_bytes",
    "raw_file",
    "reasoning_content",
}

MAX_STRING_LENGTH = 12000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(operation_name: str, fn: Callable[[], Any]) -> Any:
    """
    Execute a MongoDB operation safely.

    Never raise persistence errors into app/runtime flow.
    """
    if not is_mongodb_enabled():
        return None

    try:
        return fn()
    except (PyMongoError, Exception) as exc:
        print(
            "[MongoDB] Non-critical persistence warning "
            f"in {operation_name}: {type(exc).__name__}"
        )
        return None


def _get_collection() -> Optional[Collection]:
    return get_sessions_collection()


def _sanitize(value: Any) -> Any:
    """
    Recursively sanitize values before MongoDB storage.

    Removes secrets, raw audio/base64 payloads, raw files, and model reasoning traces.
    Converts unknown objects to strings.
    """
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}

        for key, item in value.items():
            key_str = str(key)
            key_lower = key_str.lower()

            if key_lower in SENSITIVE_KEYS:
                continue

            cleaned[key_str] = _sanitize(item)

        return cleaned

    if isinstance(value, list):
        return [_sanitize(item) for item in value]

    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]

    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH] + "...[truncated]"
        return value

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return str(value)


def _startup_context_from_session(session: dict) -> dict:
    startup = session.get("startup") or {}

    context = {
        "name": startup.get("name", ""),
        "problem": startup.get("problem", ""),
        "target_users": startup.get("target_users", ""),
        "solution": startup.get("solution", ""),
        "why_ai": startup.get("why_ai", ""),
        "traction": startup.get("traction", ""),
        "competitors": startup.get("competitors", ""),
        "ask": startup.get("ask", ""),
        "entry_mode": "voice_pitch" if session.get("voice_pitch") else "form",
    }

    # Preserve useful extra startup fields without storing secrets/raw payloads.
    extra = {
        key: value
        for key, value in startup.items()
        if key not in context
    }

    if extra:
        context["extra"] = _sanitize(extra)

    return _sanitize(context)


def _voice_pitch_entry_from_session(session: dict) -> dict:
    voice_pitch = session.get("voice_pitch") or {}

    if not voice_pitch:
        return {
            "used": False,
            "transcript": "",
            "delivery_observations": {
                "filler_words": [],
                "filler_word_count": 0,
                "pace": "",
                "clarity": "",
                "confidence_signal": "",
                "word_count": 0,
                "delivery_note": "",
            },
            "extraction_confidence": "",
        }

    transcript = voice_pitch.get("transcript", "") or ""
    observations = voice_pitch.get("delivery_observations") or {}

    filler_words = observations.get("filler_words") or []
    if not isinstance(filler_words, list):
        filler_words = [str(filler_words)]

    delivery_observations = {
        "filler_words": filler_words,
        "filler_word_count": len(filler_words),
        "pace": observations.get("pace", ""),
        "clarity": observations.get("clarity", ""),
        "confidence_signal": observations.get("confidence_signal", ""),
        "word_count": len(transcript.split()) if transcript else 0,
        "delivery_note": observations.get("delivery_note", ""),
    }

    return _sanitize(
        {
            "used": True,
            "transcript": transcript,
            "delivery_observations": delivery_observations,
            "extraction_confidence": voice_pitch.get("extraction_confidence", ""),
        }
    )


def _rounds_from_history(history: Any) -> list[dict]:
    if not isinstance(history, list):
        return []

    rounds: list[dict] = []

    for index, item in enumerate(history):
        if not isinstance(item, dict):
            continue

        rounds.append(
            _sanitize(
                {
                    "sequence": index + 1,
                    "round_number": item.get("round") or item.get("round_number") or None,
                    "role": item.get("role", ""),
                    "content": item.get("content", ""),
                    "attack_tag": item.get("attack_tag", ""),
                    "answer_quality": item.get("answer_quality", ""),
                    "timestamp": item.get("timestamp", ""),
                }
            )
        )

    return rounds


def _retry_drills_from_session(session: dict) -> list[dict]:
    retry_drills = session.get("retry_drills") or {}

    if isinstance(retry_drills, dict):
        drills = list(retry_drills.values())
    elif isinstance(retry_drills, list):
        drills = retry_drills
    else:
        drills = []

    cleaned_drills = []

    for drill in drills:
        if not isinstance(drill, dict):
            continue

        cleaned_drill = dict(drill)
        cleaned_drill.pop("voice_turn_id", None)
        cleaned_drills.append(_sanitize(cleaned_drill))

    return cleaned_drills


def _scorecard_for_storage(scorecard: dict) -> dict:
    if not isinstance(scorecard, dict):
        return {}

    cleaned = dict(scorecard)

    # Store judge verdict separately to avoid duplicated nested state.
    cleaned.pop("judge_verdict", None)

    return _sanitize(cleaned)


def _deal_phase_from_session(session: dict) -> dict:
    return _sanitize(
        {
            "activated": bool(session.get("deal_phase_active", False)),
            "deal_phase_id": session.get("deal_phase_id", ""),
            "deal_type": session.get("deal_type", ""),
            "deal_context": session.get("deal_context", {}) or {},
            "deal_round": session.get("deal_round", 0) or 0,
            "deal_history": session.get("deal_history", []) or [],
            "deal_scorecard": session.get("deal_scorecard", {}) or {},
            "combined_scorecard": session.get("combined_scorecard", {}) or {},
        }
    )


def _infer_status(session: dict) -> str:
    if session.get("combined_scorecard") or session.get("deal_scorecard"):
        return "completed"

    if session.get("latest_scorecard") and not session.get("deal_phase_active"):
        return "completed"

    return "active"


def _session_document(session: dict) -> dict:
    session_id = session.get("session_id")

    return _sanitize(
        {
            "_id": session_id,
            "meta": {
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "status": _infer_status(session),
                "mode": session.get("mode", "pitch_battle"),
                "input_mode": session.get("input_mode", "text"),
            },
            "config": {
                "opponent": session.get("persona", ""),
                "persona": session.get("persona", ""),
                "model_mode": session.get("model_mode", ""),
                "difficulty_profile": session.get("difficulty_profile")
                or session.get("difficulty")
                or "",
                "difficulty_label": session.get("difficulty_label", ""),
            },
            "startup_context": _startup_context_from_session(session),
            "voice_pitch_entry": _voice_pitch_entry_from_session(session),
            "rounds": _rounds_from_history(session.get("history", [])),
            "battle_summary": {
                "total_rounds": session.get("round", 0),
                "final_round": session.get("round", 0),
            },
            "scorecard": _scorecard_for_storage(session.get("latest_scorecard", {}) or {}),
            "retry_drills": _retry_drills_from_session(session),
            "judge_verdict": _sanitize(session.get("judge_verdict", {}) or {}),
            "deal_phase": _deal_phase_from_session(session),
        }
    )


def _set_with_touch(
    collection: Collection,
    session_id: str,
    fields: dict,
    *,
    status: Optional[str] = None,
) -> None:
    now = _utc_now()

    set_fields = _sanitize(fields)
    set_fields["meta.updated_at"] = now

    if status:
        set_fields["meta.status"] = status

    collection.update_one(
        {"_id": session_id},
        {
            "$setOnInsert": {
                "_id": session_id,
                "meta.created_at": now,
            },
            "$set": set_fields,
        },
        upsert=True,
    )


def save_session(session: dict) -> Any:
    """
    Save/initialize one PitchFight session document.

    Called after /api/start-session succeeds.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None:
            return None

        doc = _session_document(session)
        session_id = doc.get("_id")

        if not session_id:
            print("[MongoDB] save_session skipped: missing session_id.")
            return None

        meta = doc.pop("meta", {}) or {}
        doc_without_id = {key: value for key, value in doc.items() if key != "_id"}

        set_fields = dict(doc_without_id)
        set_fields["meta.updated_at"] = _utc_now()
        set_fields["meta.status"] = meta.get("status", "active")
        set_fields["meta.mode"] = meta.get("mode", "pitch_battle")
        set_fields["meta.input_mode"] = meta.get("input_mode", "text")

        return collection.update_one(
            {"_id": session_id},
            {
                "$setOnInsert": {
                    "_id": session_id,
                    "meta.created_at": meta.get("created_at", _utc_now()),
                },
                "$set": set_fields,
            },
            upsert=True,
        )

    return _safe("save_session", op)


def update_round(session_id: str, round_data: Any) -> Any:
    """
    Append one or more battle round/history entries.

    Called after /api/chat-round succeeds.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        if isinstance(round_data, list):
            entries = [_sanitize(item) for item in round_data if isinstance(item, dict)]
        elif isinstance(round_data, dict):
            entries = [_sanitize(round_data)]
        else:
            entries = []

        if not entries:
            return None

        now = _utc_now()

        return collection.update_one(
            {"_id": session_id},
            {
                "$setOnInsert": {
                    "_id": session_id,
                    "meta.created_at": now,
                    "meta.status": "active",
                },
                "$set": {
                    "meta.updated_at": now,
                },
                "$push": {
                    "rounds": {
                        "$each": entries,
                    }
                },
            },
            upsert=True,
        )

    return _safe("update_round", op)


def update_battle_summary(session_id: str, summary: dict) -> Any:
    """
    Save final pitch battle summary.

    Called after /api/end-battle.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        return _set_with_touch(
            collection,
            session_id,
            {
                "battle_summary": _sanitize(summary or {}),
            },
        )

    return _safe("update_battle_summary", op)


def save_scorecard(session_id: str, scorecard: dict) -> Any:
    """
    Save latest pitch scorecard.

    Called after scorecard generation succeeds.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        return _set_with_touch(
            collection,
            session_id,
            {
                "scorecard": _scorecard_for_storage(scorecard or {}),
            },
        )

    return _safe("save_scorecard", op)


def save_retry_drill(session_id: str, drill: dict) -> Any:
    """
    Save or replace one retry drill in retry_drills array.

    Called after retry weakest question start/submit succeeds.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id or not isinstance(drill, dict):
            return None

        cleaned_drill = dict(drill)
        cleaned_drill.pop("voice_turn_id", None)
        cleaned_drill = _sanitize(cleaned_drill)

        retry_id = cleaned_drill.get("retry_id")
        now = _utc_now()

        if retry_id:
            collection.update_one(
                {"_id": session_id},
                {
                    "$pull": {
                        "retry_drills": {
                            "retry_id": retry_id,
                        }
                    },
                    "$set": {
                        "meta.updated_at": now,
                    },
                },
                upsert=False,
            )

        return collection.update_one(
            {"_id": session_id},
            {
                "$setOnInsert": {
                    "_id": session_id,
                    "meta.created_at": now,
                    "meta.status": "active",
                },
                "$set": {
                    "meta.updated_at": now,
                },
                "$push": {
                    "retry_drills": cleaned_drill,
                },
            },
            upsert=True,
        )

    return _safe("save_retry_drill", op)


def save_judge_verdict(session_id: str, verdict: dict) -> Any:
    """
    Save judge verdict separately from scorecard.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        return _set_with_touch(
            collection,
            session_id,
            {
                "judge_verdict": _sanitize(verdict or {}),
            },
        )

    return _safe("save_judge_verdict", op)


def update_deal_round(session_id: str, deal_round: Any) -> Any:
    """
    Append one or more deal-phase history entries.

    Called after /api/start-deal-phase and /api/deal-round.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        if isinstance(deal_round, list):
            entries = [_sanitize(item) for item in deal_round if isinstance(item, dict)]
        elif isinstance(deal_round, dict):
            entries = [_sanitize(deal_round)]
        else:
            entries = []

        if not entries:
            return None

        now = _utc_now()

        return collection.update_one(
            {"_id": session_id},
            {
                "$setOnInsert": {
                    "_id": session_id,
                    "meta.created_at": now,
                },
                "$set": {
                    "meta.updated_at": now,
                    "meta.status": "active",
                    "deal_phase.activated": True,
                },
                "$push": {
                    "deal_phase.deal_history": {
                        "$each": entries,
                    }
                },
            },
            upsert=True,
        )

    return _safe("update_deal_round", op)


def save_deal_scorecard(
    session_id: str,
    deal_scorecard: dict,
    combined_scorecard: dict,
) -> Any:
    """
    Save final deal scorecard and combined pitch + deal scorecard.

    Called after /api/end-deal succeeds.
    """
    def op() -> Any:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        return _set_with_touch(
            collection,
            session_id,
            {
                "deal_phase.activated": False,
                "deal_phase.deal_scorecard": _sanitize(deal_scorecard or {}),
                "deal_phase.combined_scorecard": _sanitize(combined_scorecard or {}),
            },
            status="completed",
        )

    return _safe("save_deal_scorecard", op)


def get_session(session_id: str) -> Optional[dict]:
    """
    Optional read helper.
    """
    def op() -> Optional[dict]:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        return collection.find_one({"_id": session_id})

    return _safe("get_session", op)


def get_recent_sessions(limit: int = 10) -> list[dict]:
    """
    Optional read helper for debugging/history screens later.
    """
    def op() -> list[dict]:
        collection = _get_collection()
        if collection is None:
            return []

        safe_limit = max(1, min(int(limit), 50))

        return list(
            collection.find({})
            .sort("meta.created_at", -1)
            .limit(safe_limit)
        )

    result = _safe("get_recent_sessions", op)
    return result or []


def get_session_scorecard(session_id: str) -> Optional[dict]:
    """
    Optional read helper.
    """
    def op() -> Optional[dict]:
        collection = _get_collection()
        if collection is None or not session_id:
            return None

        doc = collection.find_one(
            {"_id": session_id},
            {
                "_id": 1,
                "scorecard": 1,
                "judge_verdict": 1,
                "deal_phase.deal_scorecard": 1,
                "deal_phase.combined_scorecard": 1,
            },
        )

        return doc

    return _safe("get_session_scorecard", op)
