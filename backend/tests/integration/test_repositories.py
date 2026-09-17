"""Integration tests for the repository layer, against real PostgreSQL.

Repositories flush but never commit, so most tests commit explicitly where
a check needs to be visible across a session boundary — matching the
Phase 4 database test conventions (fresh sessions for cascade checks, since
passive_deletes=True + expire_on_commit=False can make a same-session
object look stale after a DB-level cascade).
"""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.database.postgres import async_session_maker
from app.models import (
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
from app.repositories import (
    PitchRepository,
    ScoreRepository,
    SimulationSessionRepository,
    UserRepository,
)

# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------


async def test_user_repository_create_and_get_by_id() -> None:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        created = await repo.create(email=f"{uuid.uuid4()}@example.com", password_hash="hashed")

        fetched = await repo.get_by_id(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.password_hash == "hashed"
        # No commit: closing the session below rolls this back automatically.


async def test_user_repository_get_by_email() -> None:
    email = f"{uuid.uuid4()}@example.com"
    async with async_session_maker() as session:
        repo = UserRepository(session)
        created = await repo.create(email=email, password_hash="hashed")

        fetched = await repo.get_by_email(email)

        assert fetched is not None
        assert fetched.id == created.id


async def test_user_repository_get_by_id_nonexistent_returns_none() -> None:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        assert await repo.get_by_id(uuid.uuid4()) is None


async def test_user_repository_get_by_email_nonexistent_returns_none() -> None:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        assert await repo.get_by_email("nobody@example.com") is None


async def test_user_repository_does_not_commit() -> None:
    """A flushed-but-uncommitted create() must be invisible from another session."""
    email = f"{uuid.uuid4()}@example.com"
    async with async_session_maker() as setup_session:
        await UserRepository(setup_session).create(email=email, password_hash="hashed")
        # deliberately no commit here

    async with async_session_maker() as verify_session:
        assert await UserRepository(verify_session).get_by_email(email) is None


# ---------------------------------------------------------------------------
# PitchRepository
# ---------------------------------------------------------------------------


async def test_pitch_repository_create_get_list_update_delete(user: User) -> None:
    async with async_session_maker() as session:
        repo = PitchRepository(session)
        pitch = await repo.create(
            user_id=user.id,
            startup_name="PitchFight",
            problem="Founders can't rehearse investor pressure.",
            target_users="First-time founders",
            solution="AI judges that simulate real pressure.",
        )
        await session.commit()
        pitch_id = pitch.id

    async with async_session_maker() as session:
        repo = PitchRepository(session)

        fetched = await repo.get_by_id(pitch_id)
        assert fetched is not None
        assert fetched.startup_name == "PitchFight"

        assert await repo.get_by_id_for_user(pitch_id, user.id) is not None
        assert await repo.get_by_id_for_user(pitch_id, uuid.uuid4()) is None

        listed = await repo.list_by_user(user.id)
        assert any(p.id == pitch_id for p in listed)

        updated = await repo.update(fetched, traction="10 paying pilots")
        await session.commit()
        assert updated.traction == "10 paying pilots"
        assert updated.startup_name == "PitchFight"  # untouched field unchanged

    async with async_session_maker() as session:
        repo = PitchRepository(session)
        await repo.delete(await repo.get_by_id(pitch_id))
        await session.commit()

    async with async_session_maker() as verify_session:
        assert await verify_session.get(Pitch, pitch_id) is None


async def test_pitch_repository_list_by_user_orders_newest_first(user: User) -> None:
    # Separate transactions so each gets its own now() — Postgres now() is
    # frozen per-transaction, so two inserts in one transaction/commit would
    # tie on created_at and make ordering non-deterministic.
    async with async_session_maker() as session:
        first = await PitchRepository(session).create(
            user_id=user.id, startup_name="First", problem="p", target_users="t", solution="s"
        )
        await session.commit()
        first_id = first.id

    async with async_session_maker() as session:
        second = await PitchRepository(session).create(
            user_id=user.id, startup_name="Second", problem="p", target_users="t", solution="s"
        )
        await session.commit()
        second_id = second.id

    async with async_session_maker() as session:
        repo = PitchRepository(session)
        listed = await repo.list_by_user(user.id)
        listed_ids = [p.id for p in listed]
        assert listed_ids.index(second_id) < listed_ids.index(first_id)

    async with async_session_maker() as session:
        repo = PitchRepository(session)
        for pitch_id in (first_id, second_id):
            await repo.delete(await repo.get_by_id(pitch_id))
        await session.commit()


async def test_pitch_repository_ownership_isolation_across_users(user: User) -> None:
    async with async_session_maker() as session:
        other_user = await UserRepository(session).create(
            email=f"{uuid.uuid4()}@example.com", password_hash="hashed"
        )
        await session.commit()
        other_user_id = other_user.id

    async with async_session_maker() as session:
        repo = PitchRepository(session)
        pitch = await repo.create(
            user_id=user.id, startup_name="Secret", problem="p", target_users="t", solution="s"
        )
        await session.commit()
        pitch_id = pitch.id

    async with async_session_maker() as session:
        repo = PitchRepository(session)
        # User B must not be able to reach User A's pitch through the
        # ownership-scoped lookup.
        assert await repo.get_by_id_for_user(pitch_id, other_user_id) is None
        assert await repo.get_by_id_for_user(pitch_id, user.id) is not None

    async with async_session_maker() as session:
        repo = PitchRepository(session)
        await repo.delete(await repo.get_by_id(pitch_id))
        await session.execute(delete(User).where(User.id == other_user_id))
        await session.commit()


# ---------------------------------------------------------------------------
# SimulationSessionRepository
# ---------------------------------------------------------------------------


async def test_session_repository_create_stores_snapshot_and_defaults(
    user: User, judge_persona: JudgePersona
) -> None:
    snapshot = {"startup_name": "PitchFight", "problem": "p"}
    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        created = await repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot=snapshot,
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.commit()
        session_id = created.id

        assert created.pitch_snapshot == snapshot
        assert created.pitch_id is None
        assert created.status == SimulationStatus.ACTIVE
        assert created.current_phase == SimulationPhase.PITCH_BATTLE

    async with async_session_maker() as verify_session:
        fetched = await verify_session.get(SimulationSession, session_id)
        assert fetched is not None
        assert fetched.pitch_snapshot == snapshot

    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        await repo.delete(await repo.get_by_id(session_id))
        await session.commit()


async def test_session_repository_ownership_and_history_listing(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        active_session = await repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.flush()
        completed_session = await repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty=Difficulty.JUDGE,
        )
        await repo.update_checkpoint(completed_session, status=SimulationStatus.COMPLETED)
        await session.commit()
        active_id, completed_id = active_session.id, completed_session.id

    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)

        assert await repo.get_by_id_for_user(active_id, user.id) is not None
        assert await repo.get_by_id_for_user(active_id, uuid.uuid4()) is None

        history_ids = {s.id for s in await repo.list_by_user(user.id)}
        assert {active_id, completed_id} <= history_ids

        active_only = {s.id for s in await repo.list_by_user_and_status(
            user.id, SimulationStatus.ACTIVE
        )}
        assert active_id in active_only
        assert completed_id not in active_only

        completed_only = {s.id for s in await repo.list_by_user_and_status(
            user.id, SimulationStatus.COMPLETED
        )}
        assert completed_id in completed_only

    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        for sid in (active_id, completed_id):
            await repo.delete(await repo.get_by_id(sid))
        await session.commit()


async def test_session_repository_update_checkpoint_touches_only_given_fields(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        created = await repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.commit()
        session_id = created.id

        updated = await repo.update_checkpoint(
            created, battle_round_count=3, current_phase=SimulationPhase.RETRY
        )
        await session.commit()

        assert updated.battle_round_count == 3
        assert updated.current_phase == SimulationPhase.RETRY
        # Fields not passed remain at their model defaults.
        assert updated.deal_round_count == 0
        assert updated.status == SimulationStatus.ACTIVE
        assert updated.completed_at is None

    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        await repo.delete(await repo.get_by_id(session_id))
        await session.commit()


async def test_deleting_pitch_nulls_session_pitch_id_but_snapshot_survives(
    user: User, judge_persona: JudgePersona
) -> None:
    snapshot = {"startup_name": "PitchFight"}
    async with async_session_maker() as session:
        pitch_repo = PitchRepository(session)
        session_repo = SimulationSessionRepository(session)

        pitch = await pitch_repo.create(
            user_id=user.id, startup_name="PitchFight", problem="p", target_users="t", solution="s"
        )
        await session.flush()

        sim_session = await session_repo.create(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot=snapshot,
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.commit()
        session_id = sim_session.id

        await pitch_repo.delete(pitch)
        await session.commit()

    async with async_session_maker() as verify_session:
        repo = SimulationSessionRepository(verify_session)
        refreshed = await repo.get_by_id(session_id)
        assert refreshed is not None
        assert refreshed.pitch_id is None
        assert refreshed.pitch_snapshot == snapshot

    async with async_session_maker() as session:
        repo = SimulationSessionRepository(session)
        await repo.delete(await repo.get_by_id(session_id))
        await session.commit()


# ---------------------------------------------------------------------------
# ScoreRepository
# ---------------------------------------------------------------------------


async def test_score_repository_create_get_list(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        session_repo = SimulationSessionRepository(session)
        score_repo = ScoreRepository(session)

        sim_session = await session_repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.flush()

        pitch_score = await score_repo.create(
            simulation_session_id=sim_session.id,
            scorecard_type=ScorecardType.PITCH,
            overall_score="72.50",
            rubric_version="v1",
            dimensions={"market_size": {"score": 80, "weight": 0.3, "reason": "ok", "evidence": []}},
        )
        final_score = await score_repo.create(
            simulation_session_id=sim_session.id,
            scorecard_type=ScorecardType.FINAL,
            overall_score="72.50",
            rubric_version="v1",
            dimensions={},
            basis="PITCH_ONLY",
        )
        await session.commit()
        session_id = sim_session.id

        fetched = await score_repo.get_by_session_and_type(session_id, ScorecardType.PITCH)
        assert fetched is not None
        assert fetched.id == pitch_score.id
        assert fetched.strengths == []  # model default applied, not None

        final = await score_repo.get_final_for_session(session_id)
        assert final is not None
        assert final.id == final_score.id

        all_scores = {s.id for s in await score_repo.list_by_session(session_id)}
        assert all_scores == {pitch_score.id, final_score.id}

    async with async_session_maker() as session:
        session_repo = SimulationSessionRepository(session)
        await session_repo.delete(await session_repo.get_by_id(session_id))
        await session.commit()


async def test_score_repository_duplicate_type_rejected_by_database(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        session_repo = SimulationSessionRepository(session)
        score_repo = ScoreRepository(session)

        sim_session = await session_repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.flush()
        session_id = sim_session.id

        await score_repo.create(
            simulation_session_id=session_id,
            scorecard_type=ScorecardType.PITCH,
            overall_score="72.50",
            rubric_version="v1",
            dimensions={},
        )
        await session.commit()

        # ScoreRepository.create() flushes internally, so the DB rejects the
        # duplicate (session_id, PITCH) pair right there rather than at commit.
        with pytest.raises(IntegrityError):
            await score_repo.create(
                simulation_session_id=session_id,
                scorecard_type=ScorecardType.PITCH,
                overall_score="80.00",
                rubric_version="v1",
                dimensions={},
            )
        await session.rollback()

    async with async_session_maker() as session:
        session_repo = SimulationSessionRepository(session)
        await session_repo.delete(await session_repo.get_by_id(session_id))
        await session.commit()


async def test_deleting_session_cascades_to_scorecards(
    user: User, judge_persona: JudgePersona
) -> None:
    async with async_session_maker() as session:
        session_repo = SimulationSessionRepository(session)
        score_repo = ScoreRepository(session)

        sim_session = await session_repo.create(
            user_id=user.id,
            judge_persona_id=judge_persona.id,
            pitch_snapshot={},
            judge_config_version="v1",
            difficulty=Difficulty.PRACTICE,
        )
        await session.flush()

        scorecard = await score_repo.create(
            simulation_session_id=sim_session.id,
            scorecard_type=ScorecardType.PITCH,
            overall_score="72.50",
            rubric_version="v1",
            dimensions={},
        )
        await session.commit()
        session_id, scorecard_id = sim_session.id, scorecard.id

        await session_repo.delete(await session_repo.get_by_id(session_id))
        await session.commit()

    async with async_session_maker() as verify_session:
        assert await verify_session.get(SimulationSession, session_id) is None
        assert await verify_session.get(Scorecard, scorecard_id) is None
