"""
MongoDB connection utilities for PitchFight AI.

Phase 9.5 rule:
- MongoDB is optional background persistence only.
- In-memory session_manager remains the live source of truth.
- If MongoDB is disabled, missing, or unavailable, the app must continue normally.
- Never print MongoDB URI, password, API keys, or secrets.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError


load_dotenv()

_client: Optional[MongoClient] = None
_db: Optional[Database] = None
_connected: bool = False

_warned_disabled: bool = False
_warned_missing_uri: bool = False
_warned_connection_failed: bool = False


def is_mongodb_enabled() -> bool:
    """
    Return True only when MongoDB persistence is explicitly enabled.

    Expected env:
        MONGODB_ENABLED=true
    """
    return os.getenv("MONGODB_ENABLED", "false").strip().lower() == "true"


def get_db() -> Optional[Database]:
    """
    Return the MongoDB database instance if enabled and reachable.

    Returns None when:
    - MONGODB_ENABLED is not true
    - MONGODB_URI is missing
    - MongoDB connection/ping fails

    This function must never raise DB errors into the main app.
    """
    global _client, _db, _connected
    global _warned_disabled, _warned_missing_uri, _warned_connection_failed

    if not is_mongodb_enabled():
        if not _warned_disabled:
            print("[MongoDB] Disabled. Persistence skipped.")
            _warned_disabled = True
        return None

    if _db is not None and _connected:
        return _db

    uri = os.getenv("MONGODB_URI", "").strip()
    db_name = os.getenv("MONGODB_DB_NAME", "pitchfight_db").strip() or "pitchfight_db"

    if not uri:
        if not _warned_missing_uri:
            print("[MongoDB] MONGODB_URI missing. Persistence skipped.")
            _warned_missing_uri = True
        return None

    try:
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")

        _db = _client[db_name]
        _connected = True

        print(f"[MongoDB] Connected to database: {db_name}")
        return _db

    except (ServerSelectionTimeoutError, PyMongoError, Exception) as exc:
        _connected = False
        _db = None

        if not _warned_connection_failed:
            print(
                "[MongoDB] Connection unavailable. "
                f"App will continue without persistence. Reason: {type(exc).__name__}"
            )
            _warned_connection_failed = True

        return None


def get_sessions_collection() -> Optional[Collection]:
    """
    Return the main sessions collection.

    Target:
        pitchfight_db.sessions
    """
    db = get_db()
    if db is None:
        return None

    return db["sessions"]


def is_connected() -> bool:
    """
    Return True if MongoDB is enabled and currently reachable.
    """
    db = get_db()
    return db is not None and _connected
