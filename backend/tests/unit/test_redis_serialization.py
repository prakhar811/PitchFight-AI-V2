"""Unit tests for the Redis JSON serialization helpers. No Redis involved."""

import uuid
from datetime import datetime, timezone
from enum import Enum

import pytest

from app.repositories.redis_base import from_json, to_json


class _Color(str, Enum):
    RED = "RED"
    BLUE = "BLUE"


def test_round_trips_primitives() -> None:
    for value in ["a string", 42, 3.14, True, False, None]:
        assert from_json(to_json(value)) == value


def test_round_trips_list_and_dict() -> None:
    value = {"a": [1, 2, {"b": "c"}], "d": None}
    assert from_json(to_json(value)) == value


def test_uuid_serializes_to_canonical_string() -> None:
    value = uuid.uuid4()
    assert from_json(to_json(value)) == str(value)


def test_datetime_serializes_to_utc_iso8601() -> None:
    value = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    assert from_json(to_json(value)) == "2026-01-01T12:30:00+00:00"


def test_enum_serializes_to_its_value() -> None:
    assert from_json(to_json(_Color.RED)) == "RED"


def test_nested_uuid_and_enum_in_dict() -> None:
    sim_id = uuid.uuid4()
    value = {"simulation_id": sim_id, "status": _Color.BLUE}
    round_tripped = from_json(to_json(value))
    assert round_tripped == {"simulation_id": str(sim_id), "status": "BLUE"}


def test_unsupported_type_raises_type_error() -> None:
    class Unsupported:
        pass

    with pytest.raises(TypeError):
        to_json(Unsupported())
