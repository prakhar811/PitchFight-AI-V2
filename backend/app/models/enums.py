"""Centralized enums shared across ORM models and Pydantic schemas."""

import enum

from sqlalchemy import Enum as SAEnum


class Difficulty(str, enum.Enum):
    PRACTICE = "PRACTICE"
    JUDGE = "JUDGE"
    INVESTOR = "INVESTOR"


class SimulationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"
    FAILED = "FAILED"


class SimulationPhase(str, enum.Enum):
    PITCH_BATTLE = "PITCH_BATTLE"
    PITCH_SCORING = "PITCH_SCORING"
    RETRY = "RETRY"
    DEAL = "DEAL"
    DEAL_SCORING = "DEAL_SCORING"
    COMPLETED = "COMPLETED"


class DealStatus(str, enum.Enum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    AVAILABLE = "AVAILABLE"
    SKIPPED = "SKIPPED"
    COMPLETED = "COMPLETED"


class ScorecardType(str, enum.Enum):
    PITCH = "PITCH"
    DEAL = "DEAL"
    FINAL = "FINAL"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Build a native PostgreSQL ENUM column type, keyed by member value."""
    return SAEnum(enum_cls, name=name, native_enum=True, values_callable=lambda e: [m.value for m in e])
