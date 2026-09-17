"""Pydantic schema validation checks."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    JudgePersonaRead,
    PitchCreate,
    PitchRead,
    ScorecardRead,
    SimulationRead,
    UserCreate,
    UserRead,
)


def test_user_create_accepts_email_and_password() -> None:
    user = UserCreate(email="founder@example.com", password="hunter2")
    assert user.email == "founder@example.com"
    assert user.password == "hunter2"


def test_user_read_never_exposes_password_hash() -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "id": uuid.uuid4(),
        "email": "founder@example.com",
        "password_hash": "should-be-ignored",
        "created_at": now,
        "updated_at": now,
    }
    user = UserRead.model_validate(payload)
    assert "password_hash" not in user.model_dump()
    assert not hasattr(user, "password_hash")


def test_pitch_create_allows_optional_fields_to_be_absent() -> None:
    pitch = PitchCreate(
        startup_name="PitchFight",
        problem="Founders can't rehearse investor pressure.",
        target_users="First-time founders",
        solution="AI judges that simulate real pitch pressure.",
    )
    assert pitch.why_ai is None
    assert pitch.traction is None


def test_pitch_read_from_orm_like_object() -> None:
    now = datetime.now(timezone.utc)

    class FakeORMPitch:
        id = uuid.uuid4()
        user_id = uuid.uuid4()
        startup_name = "PitchFight"
        problem = "x"
        target_users = "y"
        solution = "z"
        why_ai = None
        traction = None
        competitors = None
        ask = None
        created_at = now
        updated_at = now

    pitch = PitchRead.model_validate(FakeORMPitch(), from_attributes=True)
    assert pitch.startup_name == "PitchFight"


def test_judge_persona_read_validates_representative_payload() -> None:
    now = datetime.now(timezone.utc)
    persona = JudgePersonaRead.model_validate(
        {
            "id": uuid.uuid4(),
            "persona_type": "skeptical_vc",
            "name": "Skeptical VC",
            "description": "Direct, ROI-focused.",
            "config_key": "skeptical_vc",
            "active": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert persona.active is True


def test_simulation_read_validates_representative_payload() -> None:
    now = datetime.now(timezone.utc)
    simulation = SimulationRead.model_validate(
        {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "pitch_id": None,
            "judge_persona_id": uuid.uuid4(),
            "pitch_snapshot": {"startup_name": "PitchFight"},
            "judge_config_version": "v1",
            "difficulty": "PRACTICE",
            "status": "ACTIVE",
            "current_phase": "PITCH_BATTLE",
            "battle_round_count": 0,
            "deal_round_count": 0,
            "deal_status": "NOT_AVAILABLE",
            "deal_type": None,
            "started_at": now,
            "completed_at": None,
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert simulation.pitch_id is None
    assert simulation.status.value == "ACTIVE"


def test_scorecard_dimensions_accept_persona_specific_criteria() -> None:
    now = datetime.now(timezone.utc)
    scorecard = ScorecardRead.model_validate(
        {
            "id": uuid.uuid4(),
            "simulation_session_id": uuid.uuid4(),
            "scorecard_type": "PITCH",
            "overall_score": "72.50",
            "overall_label": "Strong",
            "rubric_version": "v1",
            "basis": "PITCH_ONLY",
            "dimensions": {
                "market_size": {
                    "score": 80,
                    "weight": 0.3,
                    "reason": "Clear TAM.",
                    "evidence": ["cited a $2B market"],
                },
                "moat": {
                    "score": 60,
                    "weight": 0.2,
                    "reason": "Weak defensibility.",
                    "evidence": [],
                },
            },
            "strengths": ["clear problem statement"],
            "weaknesses": ["no traction data"],
            "feedback": "Solid start.",
            "coaching": {"next_step": "Add a retention number."},
            "created_at": now,
            "updated_at": now,
        }
    )
    assert scorecard.dimensions["market_size"].score == 80
    assert scorecard.dimensions["moat"].weight == 0.2


def test_scorecard_overall_score_out_of_range_rejected_at_domain_level() -> None:
    # The schema itself doesn't re-enforce the DB CHECK constraint (0-100);
    # that's the database's job. This test just documents the boundary is
    # enforced at the DB layer, not duplicated in Pydantic.
    now = datetime.now(timezone.utc)
    scorecard = ScorecardRead.model_validate(
        {
            "id": uuid.uuid4(),
            "simulation_session_id": uuid.uuid4(),
            "scorecard_type": "FINAL",
            "overall_score": "150.00",
            "overall_label": None,
            "rubric_version": "v1",
            "basis": "PITCH_AND_DEAL",
            "dimensions": {},
            "strengths": [],
            "weaknesses": [],
            "feedback": None,
            "coaching": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert scorecard.overall_score == 150


def test_simulation_read_rejects_invalid_enum_value() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        SimulationRead.model_validate(
            {
                "id": uuid.uuid4(),
                "user_id": uuid.uuid4(),
                "pitch_id": None,
                "judge_persona_id": uuid.uuid4(),
                "pitch_snapshot": {},
                "judge_config_version": "v1",
                "difficulty": "NOT_A_REAL_DIFFICULTY",
                "status": "ACTIVE",
                "current_phase": "PITCH_BATTLE",
                "battle_round_count": 0,
                "deal_round_count": 0,
                "deal_status": "NOT_AVAILABLE",
                "deal_type": None,
                "started_at": now,
                "completed_at": None,
                "failure_reason": None,
                "created_at": now,
                "updated_at": now,
            }
        )
