"""ORM model import and definition sanity checks."""

from app.models import (
    Base,
    DealStatus,
    Difficulty,
    JudgePersona,
    Pitch,
    Scorecard,
    ScorecardType,
    SimulationPhase,
    SimulationSession,
    SimulationStatus,
    User,
)


def test_models_register_expected_tables() -> None:
    assert set(Base.metadata.tables.keys()) == {
        "users",
        "pitches",
        "judge_personas",
        "simulation_sessions",
        "scorecards",
    }


def test_difficulty_enum_members() -> None:
    assert {member.value for member in Difficulty} == {"PRACTICE", "JUDGE", "INVESTOR"}


def test_simulation_status_enum_members() -> None:
    assert {member.value for member in SimulationStatus} == {
        "ACTIVE",
        "COMPLETED",
        "ABANDONED",
        "FAILED",
    }


def test_simulation_phase_enum_members() -> None:
    assert {member.value for member in SimulationPhase} == {
        "PITCH_BATTLE",
        "PITCH_SCORING",
        "RETRY",
        "DEAL",
        "DEAL_SCORING",
        "COMPLETED",
    }


def test_deal_status_enum_members() -> None:
    assert {member.value for member in DealStatus} == {
        "NOT_AVAILABLE",
        "AVAILABLE",
        "SKIPPED",
        "COMPLETED",
    }


def test_scorecard_type_enum_members() -> None:
    assert {member.value for member in ScorecardType} == {"PITCH", "DEAL", "FINAL"}


def test_simulation_session_column_defaults() -> None:
    # SQLAlchemy applies Mapped `default=` at flush/INSERT time, not at
    # __init__, so these are checked at the column definition level.
    columns = SimulationSession.__table__.c
    assert columns.status.default.arg == SimulationStatus.ACTIVE
    assert columns.current_phase.default.arg == SimulationPhase.PITCH_BATTLE
    assert columns.deal_status.default.arg == DealStatus.NOT_AVAILABLE
    assert columns.battle_round_count.default.arg == 0
    assert columns.deal_round_count.default.arg == 0


def test_judge_persona_default_active() -> None:
    assert JudgePersona.__table__.c.active.default.arg is True


def test_scorecard_unique_constraint_defined() -> None:
    constraint_names = {c.name for c in Scorecard.__table__.constraints}
    assert "uq_scorecards_session_type" in constraint_names


def test_user_and_pitch_have_no_stray_columns() -> None:
    assert {c.name for c in User.__table__.columns} == {
        "id",
        "email",
        "password_hash",
        "created_at",
        "updated_at",
    }
    assert {c.name for c in Pitch.__table__.columns} == {
        "id",
        "user_id",
        "startup_name",
        "problem",
        "target_users",
        "solution",
        "why_ai",
        "traction",
        "competitors",
        "ask",
        "created_at",
        "updated_at",
    }
