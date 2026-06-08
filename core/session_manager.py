"""In-memory session manager for pitch battles."""

from __future__ import annotations

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
