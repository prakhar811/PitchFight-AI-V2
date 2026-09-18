"""Shared Redis repository infrastructure: JSON serialization helpers.

Kept intentionally tiny — no generic Redis repository framework. Values are
stored as JSON strings, never pickle: inspectable, portable, and safe.
"""

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def to_json(value: Any) -> str:
    return json.dumps(value, default=_json_default)


def from_json(raw: str) -> Any:
    return json.loads(raw)
