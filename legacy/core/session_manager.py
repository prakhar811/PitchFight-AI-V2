"""In-memory session manager for pitch battles."""

from __future__ import annotations

import re
import uuid
from typing import Any

SESSIONS: dict[str, dict[str, Any]] = {}


def create_session(
    startup: dict,
    persona: str,
    difficulty: str,
    input_mode: str,
) -> dict[str, Any]:
    """Create a new pitch battle session."""
    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "startup": startup,
        "persona": persona,
        "difficulty": difficulty,
        "input_mode": input_mode,
        "round": 1,
        "history": [],
        "voice_pitch": None,
        "pending_voice_turns": {},
        "confirmed_voice_turns": [],
    }
    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return a session by id, or None if missing."""
    return SESSIONS.get(session_id)


def append_user_message(session_id: str, message: str) -> None:
    """Append a user message to session history."""
    session = SESSIONS.get(session_id)
    if not session:
        return
    session["history"].append({"role": "user", "content": message})


def append_ai_message(session_id: str, message: str, attack_tag: str) -> None:
    """Append an AI opponent message to session history."""
    session = SESSIONS.get(session_id)
    if not session:
        return
    session["history"].append(
        {"role": "assistant", "content": message, "attack_tag": attack_tag}
    )


def increment_round(session_id: str) -> int:
    """Increment and return the current round number."""
    session = SESSIONS.get(session_id)
    if not session:
        return 0
    session["round"] = session.get("round", 1) + 1
    return session["round"]


def get_history(session_id: str) -> list[dict[str, Any]]:
    """Return conversation history for a session."""
    session = SESSIONS.get(session_id)
    if not session:
        return []
    return list(session.get("history", []))


def reset_session(session_id: str) -> bool:
    """Delete a session. Returns True if it existed."""
    if session_id in SESSIONS:
        del SESSIONS[session_id]
        return True
    return False


def set_voice_pitch(session_id: str, voice_pitch: dict[str, Any]) -> None:
    """Store opening voice pitch metadata on session."""
    session = SESSIONS.get(session_id)
    if session:
        session["voice_pitch"] = voice_pitch


def store_pending_voice_turn(session_id: str, turn_record: dict[str, Any]) -> None:
    """Store a pending (unconfirmed) voice turn."""
    session = SESSIONS.get(session_id)
    if not session:
        return
    pending = session.setdefault("pending_voice_turns", {})
    vid = turn_record.get("voice_turn_id", "")
    if vid:
        pending[vid] = turn_record


def confirm_voice_turn(
    session_id: str,
    voice_turn_id: str,
    final_transcript: str,
) -> bool:
    """Confirm a pending voice turn and move it to confirmed_voice_turns."""
    session = SESSIONS.get(session_id)
    if not session:
        return False
    pending = session.get("pending_voice_turns") or {}
    turn = pending.get(voice_turn_id)
    if not turn:
        return False
    turn = dict(turn)
    turn["transcript"] = str(final_transcript).strip()
    turn["confirmed"] = True
    turn["word_count"] = len(re.findall(r"\b\w+\b", turn["transcript"]))
    session.setdefault("confirmed_voice_turns", []).append(turn)
    del pending[voice_turn_id]
    return True


def get_pending_voice_turn(session_id: str, voice_turn_id: str) -> dict[str, Any] | None:
    """Return a pending voice turn by id."""
    session = SESSIONS.get(session_id)
    if not session:
        return None
    return (session.get("pending_voice_turns") or {}).get(voice_turn_id)
