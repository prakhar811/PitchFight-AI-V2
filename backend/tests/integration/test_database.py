"""Integration tests against the local PostgreSQL instance.

Requires the docker-compose `postgres` service to be up with the initial
Alembic migration applied. Each test cleans up after itself.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.postgres import async_session_maker
from app.models import JudgePersona, Pitch, Scorecard, ScorecardType, SimulationSession, User


async def test_deleting_user_cascades_to_pitches(user: User) -> None:
    async with async_session_maker() as session:
        pitch = Pitch(
            user_id=user.id,
            startup_name="PitchFight",
            problem="p",
            target_users="t",
            solution="s",
        )
        session.add(pitch)
        await session.commit()
        pitch_id = pitch.id

        db_user = await session.get(User, user.id)
        await session.delete(db_user)
        await session.commit()

    # The User -> Pitch relationship uses passive_deletes=True (trusting the
    # DB's ON DELETE CASCADE), so the deleting session's identity map is
    # never told the child row is gone. Verify with a fresh session instead.
    async with async_session_maker() as verify_session:
        assert await verify_session.get(Pitch, pitch_id) is None


async def test_deleting_pitch_sets_simulation_pitch_id_null(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        pitch = Pitch(
            user_id=user.id,
            startup_name="PitchFight",
            problem="p",
            target_users="t",
            solution="s",
        )
        session.add(pitch)
        await session.flush()

        session_row = SimulationSession(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={"startup_name": "PitchFight"},
            judge_config_version="v1",
            difficulty="PRACTICE",
        )
        session.add(session_row)
        await session.commit()
        session_id = session_row.id

        await session.delete(await session.get(Pitch, pitch.id))
        await session.commit()

        refreshed = await session.get(SimulationSession, session_id)
        assert refreshed is not None
        assert refreshed.pitch_id is None

        await session.delete(refreshed)
        await session.commit()


async def test_scorecard_type_unique_per_session(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        session_row = SimulationSession(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty="PRACTICE",
        )
        session.add(session_row)
        await session.flush()
        session_row_id = session_row.id  # captured before rollback expires the object

        session.add(
            Scorecard(
                simulation_session_id=session_row_id,
                scorecard_type=ScorecardType.PITCH,
                overall_score="72.50",
                rubric_version="v1",
                dimensions={},
            )
        )
        await session.commit()

        session.add(
            Scorecard(
                simulation_session_id=session_row_id,
                scorecard_type=ScorecardType.PITCH,
                overall_score="80.00",
                rubric_version="v1",
                dimensions={},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    # Use a fresh session for cleanup — the failed commit/rollback leaves the
    # prior session's objects in a state that can't be safely reused.
    async with async_session_maker() as cleanup_session:
        await cleanup_session.delete(await cleanup_session.get(SimulationSession, session_row_id))
        await cleanup_session.commit()
