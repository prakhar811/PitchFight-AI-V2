"""SimulationService integration tests against real PostgreSQL, MongoDB,
and Redis (isolated test stores — see conftest.py fixtures).

Each test cleans up the SQL/Mongo/Redis state it creates. The `user`,
`judge_persona`, and `pitch` fixtures (conftest.py) already clean up their
own rows.
"""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import async_session_maker
from app.models import (
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
from app.repositories import (
    MongoConversationRepository,
    PitchRepository,
    RedisSessionStateRepository,
    ScoreRepository,
    UserRepository,
)
from app.services import (
    InvalidSimulationTransitionError,
    JudgePersonaNotFoundError,
    PitchNotFoundError,
    SimulationNotFoundError,
    SimulationPersistenceError,
    SimulationService,
    SimulationTerminalError,
)


def _build_service(
    session: AsyncSession, mongo_conversations_collection, redis_test_client
) -> SimulationService:
    return SimulationService(
        session,
        MongoConversationRepository(mongo_conversations_collection),
        RedisSessionStateRepository(redis_test_client),
    )


async def _cleanup_simulation(simulation_id: uuid.UUID, mongo_conversations_collection, redis_test_client) -> None:
    """Best-effort teardown across all three stores, bypassing service-level
    ownership checks so tests always leave a clean slate regardless of
    outcome."""
    await mongo_conversations_collection.delete_one({"simulation_id": str(simulation_id)})
    await redis_test_client.delete(f"session:{simulation_id}:state")
    async with async_session_maker() as session:
        await session.execute(delete(SimulationSession).where(SimulationSession.id == simulation_id))
        await session.commit()


# ---------------------------------------------------------------------------
# START
# ---------------------------------------------------------------------------


async def test_start_simulation_succeeds_with_correct_defaults(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        assert created.status == SimulationStatus.ACTIVE
        assert created.current_phase == SimulationPhase.PITCH_BATTLE
        assert created.battle_round_count == 0
        assert created.deal_round_count == 0
        assert created.deal_status == DealStatus.NOT_AVAILABLE
        assert created.judge_config_version == f"{judge_persona.persona_type}-v1"

        assert created.pitch_snapshot == {
            "startup_name": pitch.startup_name,
            "problem": pitch.problem,
            "target_users": pitch.target_users,
            "solution": pitch.solution,
            "why_ai": pitch.why_ai,
            "traction": pitch.traction,
            "competitors": pitch.competitors,
            "ask": pitch.ask,
        }

        document = await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)})
        assert document is not None
        assert document["events"] == []

        state = await redis_test_client.hgetall(f"session:{simulation_id}:state")
        assert state != {}
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# OWNERSHIP
# ---------------------------------------------------------------------------


async def test_user_cannot_start_simulation_using_another_users_pitch(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        other_user = await UserRepository(session).create(
            email=f"{uuid.uuid4()}@example.com", password_hash="hashed"
        )
        await session.commit()
        other_user_id = other_user.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(PitchNotFoundError):
                await service.start_simulation(
                    user_id=other_user_id,
                    pitch_id=pitch.id,
                    judge_persona_id=judge_persona.id,
                    difficulty=Difficulty.PRACTICE,
                )
    finally:
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == other_user_id))
            await session.commit()


async def test_user_cannot_read_another_users_simulation(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        other_user = await UserRepository(session).create(
            email=f"{uuid.uuid4()}@example.com", password_hash="hashed"
        )
        await session.commit()
        other_user_id = other_user.id

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(SimulationNotFoundError):
                await service.get_simulation(simulation_id, other_user_id)
            # Owner can still read it.
            assert (await service.get_simulation(simulation_id, user.id)).id == simulation_id
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == other_user_id))
            await session.commit()


async def test_user_cannot_transition_another_users_simulation(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        other_user = await UserRepository(session).create(
            email=f"{uuid.uuid4()}@example.com", password_hash="hashed"
        )
        await session.commit()
        other_user_id = other_user.id

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(SimulationNotFoundError):
                await service.transition_phase(simulation_id, other_user_id, SimulationPhase.PITCH_SCORING)
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == other_user_id))
            await session.commit()


async def test_user_cannot_delete_another_users_simulation(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        other_user = await UserRepository(session).create(
            email=f"{uuid.uuid4()}@example.com", password_hash="hashed"
        )
        await session.commit()
        other_user_id = other_user.id

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(SimulationNotFoundError):
                await service.delete_simulation(simulation_id, other_user_id)
        # Still there afterward, untouched.
        async with async_session_maker() as session:
            assert await session.get(SimulationSession, simulation_id) is not None
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == other_user_id))
            await session.commit()


# ---------------------------------------------------------------------------
# JUDGE VALIDATION
# ---------------------------------------------------------------------------


async def test_start_simulation_rejects_nonexistent_judge(
    user: User, pitch: Pitch, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        with pytest.raises(JudgePersonaNotFoundError):
            await service.start_simulation(
                user_id=user.id,
                pitch_id=pitch.id,
                judge_persona_id=uuid.uuid4(),
                difficulty=Difficulty.PRACTICE,
            )


async def test_start_simulation_rejects_inactive_judge(
    user: User, pitch: Pitch, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        inactive = JudgePersona(
            persona_type=f"inactive_{uuid.uuid4().hex[:8]}",
            name="Inactive Judge",
            description="Retired judge.",
            config_key="inactive_judge",
            active=False,
        )
        session.add(inactive)
        await session.commit()
        await session.refresh(inactive)
        inactive_id = inactive.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(JudgePersonaNotFoundError):
                await service.start_simulation(
                    user_id=user.id,
                    pitch_id=pitch.id,
                    judge_persona_id=inactive_id,
                    difficulty=Difficulty.PRACTICE,
                )
    finally:
        async with async_session_maker() as session:
            await session.execute(delete(JudgePersona).where(JudgePersona.id == inactive_id))
            await session.commit()


# ---------------------------------------------------------------------------
# PHASE TRANSITIONS
# ---------------------------------------------------------------------------


async def test_valid_phase_transition_succeeds(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            updated = await service.transition_phase(
                simulation_id, user.id, SimulationPhase.PITCH_SCORING
            )
            assert updated.current_phase == SimulationPhase.PITCH_SCORING

        state = await redis_test_client.hget(f"session:{simulation_id}:state", "current_phase")
        assert state == '"PITCH_SCORING"'
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_invalid_phase_transition_rejected(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            # PITCH_BATTLE -> DEAL directly is not in the locked graph.
            with pytest.raises(InvalidSimulationTransitionError):
                await service.transition_phase(simulation_id, user.id, SimulationPhase.DEAL)
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_backwards_phase_transition_rejected(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.transition_phase(simulation_id, user.id, SimulationPhase.PITCH_SCORING)

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(InvalidSimulationTransitionError):
                await service.transition_phase(simulation_id, user.id, SimulationPhase.PITCH_BATTLE)
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_terminal_session_cannot_transition(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.mark_abandoned(simulation_id, user.id)

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(SimulationTerminalError):
                await service.transition_phase(simulation_id, user.id, SimulationPhase.PITCH_SCORING)
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_deal_phase_blocked_while_deal_status_not_available(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.transition_phase(simulation_id, user.id, SimulationPhase.PITCH_SCORING)
            # deal_status is still NOT_AVAILABLE (default) — entering DEAL must fail.
            with pytest.raises(InvalidSimulationTransitionError):
                await service.transition_phase(simulation_id, user.id, SimulationPhase.DEAL)
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# EVENTS
# ---------------------------------------------------------------------------


async def test_record_event_persists_to_mongo_and_returns_assigned_sequence(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            persisted = await service.record_event(
                simulation_id,
                user.id,
                event_type="JUDGE_QUESTION",
                role="JUDGE",
                content="What proves this market is real?",
            )
        assert persisted["sequence"] == 1
        assert persisted["event_id"]
        assert persisted["content"] == "What proves this market is real?"

        document = await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)})
        assert len(document["events"]) == 1
        assert document["events"][0]["sequence"] == 1

        last_seq = await redis_test_client.hget(f"session:{simulation_id}:state", "last_event_sequence")
        assert last_seq == "1"
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_record_event_state_patch_updates_redis(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.record_event(
                simulation_id,
                user.id,
                event_type="FOUNDER_ANSWER",
                content="We have 500 signups.",
                metadata={"attack_tag": "market_awareness"},
                state_patch={"active_attack_tag": "market_awareness", "last_answer_quality": 0.74},
            )

        state = await RedisSessionStateRepository(redis_test_client).get_state(simulation_id)
        assert state["active_attack_tag"] == "market_awareness"
        assert state["last_answer_quality"] == 0.74
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_record_event_rejects_invalid_state_patch_key(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(ValueError):
                await service.record_event(
                    simulation_id,
                    user.id,
                    event_type="FOUNDER_ANSWER",
                    state_patch={"current_phase": "COMPLETED"},  # durable field, not allowed
                )

        # No event should have been written for the rejected call.
        document = await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)})
        assert document["events"] == []
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_record_event_rejected_for_terminal_session(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.mark_abandoned(simulation_id, user.id)

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(SimulationTerminalError):
                await service.record_event(simulation_id, user.id, event_type="FOUNDER_ANSWER")
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_event_ordering_sequence_and_redis_stay_in_sync(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        for i in range(5):
            async with async_session_maker() as session:
                service = _build_service(session, mongo_conversations_collection, redis_test_client)
                persisted = await service.record_event(
                    simulation_id, user.id, event_type="FOUNDER_ANSWER", content=f"answer-{i}"
                )
                assert persisted["sequence"] == i + 1

        document = await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)})
        assert [e["sequence"] for e in document["events"]] == [1, 2, 3, 4, 5]

        last_seq = await redis_test_client.hget(f"session:{simulation_id}:state", "last_event_sequence")
        assert last_seq == "5"
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# CHECKPOINT
# ---------------------------------------------------------------------------


async def test_update_runtime_checkpoint_persists_to_sql_and_redis(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            updated = await service.update_runtime_checkpoint(
                simulation_id, user.id, battle_round_count=1
            )
            assert updated.battle_round_count == 1

        async with async_session_maker() as session:
            fresh = await session.get(SimulationSession, simulation_id)
            assert fresh.battle_round_count == 1

        redis_round = await redis_test_client.hget(f"session:{simulation_id}:state", "battle_round")
        assert redis_round == "1"
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_update_runtime_checkpoint_rejects_negative_round_count(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(ValueError):
                await service.update_runtime_checkpoint(
                    simulation_id, user.id, battle_round_count=-1
                )
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_update_runtime_checkpoint_rejects_decreasing_round_count(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.update_runtime_checkpoint(simulation_id, user.id, battle_round_count=2)

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            with pytest.raises(ValueError):
                await service.update_runtime_checkpoint(
                    simulation_id, user.id, battle_round_count=1
                )
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# RECOVERY — the most important Phase 9 behavior.
# ---------------------------------------------------------------------------


async def test_recovery_reconstructs_live_state_after_redis_deletion(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.record_event(
                simulation_id,
                user.id,
                event_type="JUDGE_QUESTION",
                content="Q1",
                state_patch={"active_attack_tag": "market_size"},
            )
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.record_event(
                simulation_id,
                user.id,
                event_type="FOUNDER_ANSWER",
                content="A1",
                state_patch={
                    "last_answer_quality": 0.6,
                    "completed_attack_tags": ["market_size"],
                    "attack_attempts": {"market_size": 1},
                },
            )
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            third = await service.record_event(
                simulation_id,
                user.id,
                event_type="JUDGE_QUESTION",
                content="Q2",
                state_patch={"active_attack_tag": "moat"},
            )

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.update_runtime_checkpoint(simulation_id, user.id, battle_round_count=2)
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.transition_phase(simulation_id, user.id, SimulationPhase.PITCH_SCORING)

        state_before = await RedisSessionStateRepository(redis_test_client).get_state(simulation_id)
        assert state_before["active_attack_tag"] == "moat"
        assert state_before["battle_round"] == 2
        assert state_before["current_phase"] == "PITCH_SCORING"

        # Simulate a cache loss.
        await redis_test_client.delete(f"session:{simulation_id}:state")
        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            recovered = await service.get_live_state(simulation_id, user.id)

        assert recovered["current_phase"] == "PITCH_SCORING"  # durable, from SQL
        assert recovered["battle_round"] == 2  # durable, from SQL
        assert recovered["deal_round"] == 0  # durable, from SQL
        assert recovered["active_attack_tag"] == "moat"  # latest state_patch wins
        assert recovered["last_answer_quality"] == 0.6
        assert recovered["completed_attack_tags"] == ["market_size"]
        assert recovered["attack_attempts"] == {"market_size": 1}
        assert recovered["last_event_sequence"] == third["sequence"]

        # Redis was actually repopulated with the reconstructed state. Compare
        # everything except updated_at: the value round-tripped through Redis
        # comes back as its JSON-serialized ISO string, not a datetime object,
        # which is expected (see redis_base.to_json), not a bug.
        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 1
        repopulated = await RedisSessionStateRepository(redis_test_client).get_state(simulation_id)
        assert {k: v for k, v in repopulated.items() if k != "updated_at"} == {
            k: v for k, v in recovered.items() if k != "updated_at"
        }
        assert repopulated["updated_at"] == recovered["updated_at"].isoformat()
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_get_live_state_for_terminal_session_does_not_revive_redis(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.mark_abandoned(simulation_id, user.id)  # also deletes Redis state

        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            result = await service.get_live_state(simulation_id, user.id)

        assert result is None
        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# TERMINAL TRANSITIONS
# ---------------------------------------------------------------------------


async def test_mark_completed_persists_sql_and_removes_redis_keeps_mongo(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            await service.record_event(simulation_id, user.id, event_type="JUDGE_QUESTION", content="Q1")
            await service.transition_phase(simulation_id, user.id, SimulationPhase.PITCH_SCORING)

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            updated = await service.mark_completed(simulation_id, user.id)

        assert updated.status == SimulationStatus.COMPLETED
        assert updated.current_phase == SimulationPhase.COMPLETED
        assert updated.completed_at is not None

        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0

        document = await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)})
        assert document is not None
        assert len(document["events"]) == 1
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_mark_abandoned_persists_sql_and_removes_redis_keeps_mongo(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            updated = await service.mark_abandoned(simulation_id, user.id)

        assert updated.status == SimulationStatus.ABANDONED
        assert updated.completed_at is None  # not fabricated

        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0
        assert await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)}) is not None
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_mark_failed_stores_safe_failure_reason_and_removes_redis_keeps_mongo(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    try:
        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            updated = await service.mark_failed(
                simulation_id, user.id, failure_reason="Judge configuration could not be loaded."
            )

        assert updated.status == SimulationStatus.FAILED
        assert updated.failure_reason == "Judge configuration could not be loaded."

        assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0
        assert await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)}) is not None
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


async def test_delete_simulation_removes_mongo_redis_and_sql(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        await service.record_event(simulation_id, user.id, event_type="JUDGE_QUESTION", content="Q1")

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        await service.delete_simulation(simulation_id, user.id)

    assert await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)}) is None
    assert await redis_test_client.exists(f"session:{simulation_id}:state") == 0
    async with async_session_maker() as session:
        assert await session.get(SimulationSession, simulation_id) is None


async def test_delete_simulation_cascades_scorecards(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id

    async with async_session_maker() as session:
        score_repo = ScoreRepository(session)
        scorecard = await score_repo.create(
            simulation_session_id=simulation_id,
            scorecard_type=ScorecardType.PITCH,
            overall_score="72.50",
            rubric_version="v1",
            dimensions={},
        )
        await session.commit()
        scorecard_id = scorecard.id

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        await service.delete_simulation(simulation_id, user.id)

    async with async_session_maker() as session:
        assert await session.get(Scorecard, scorecard_id) is None
        assert await session.get(SimulationSession, simulation_id) is None


# ---------------------------------------------------------------------------
# PITCH SNAPSHOT IMMUTABILITY / PITCH DELETION HISTORY
# ---------------------------------------------------------------------------


async def test_pitch_snapshot_remains_unchanged_after_editing_pitch(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch.id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id
        original_snapshot = dict(created.pitch_snapshot)

    try:
        async with async_session_maker() as session:
            pitch_repo = PitchRepository(session)
            fetched_pitch = await pitch_repo.get_by_id(pitch.id)
            await pitch_repo.update(
                fetched_pitch, startup_name="Totally Different Name", traction="1M users now"
            )
            await session.commit()

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            reloaded = await service.get_simulation(simulation_id, user.id)

        assert reloaded.pitch_snapshot == original_snapshot
        assert reloaded.pitch_snapshot["startup_name"] == "PitchFight"
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


async def test_deleting_pitch_nulls_simulation_pitch_id_but_snapshot_survives(
    user: User, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    async with async_session_maker() as session:
        pitch_repo = PitchRepository(session)
        own_pitch = await pitch_repo.create(
            user_id=user.id,
            startup_name="Temporary",
            problem="p",
            target_users="t",
            solution="s",
        )
        await session.commit()
        pitch_id = own_pitch.id

    async with async_session_maker() as session:
        service = _build_service(session, mongo_conversations_collection, redis_test_client)
        created = await service.start_simulation(
            user_id=user.id,
            pitch_id=pitch_id,
            judge_persona_id=judge_persona.id,
            difficulty=Difficulty.PRACTICE,
        )
        simulation_id = created.id
        original_snapshot = dict(created.pitch_snapshot)

    try:
        async with async_session_maker() as session:
            pitch_repo = PitchRepository(session)
            await pitch_repo.delete(await pitch_repo.get_by_id(pitch_id))
            await session.commit()

        async with async_session_maker() as session:
            service = _build_service(session, mongo_conversations_collection, redis_test_client)
            reloaded = await service.get_simulation(simulation_id, user.id)

        assert reloaded.pitch_id is None
        assert reloaded.pitch_snapshot == original_snapshot
    finally:
        await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)


# ---------------------------------------------------------------------------
# FAILURE COMPENSATION — start_simulation with a broken Redis dependency.
# Uses real Postgres + real Mongo, a fake Redis repo that deliberately
# fails, per the task's guidance for compensation-path testing.
# ---------------------------------------------------------------------------


class _FailingRedisStateRepo:
    """Minimal fake matching RedisSessionStateRepository's used surface,
    for deterministically exercising start_simulation's compensation path."""

    def __init__(self) -> None:
        self.attempted_simulation_id: uuid.UUID | None = None

    async def set_state(self, simulation_id: uuid.UUID, state: dict) -> None:
        self.attempted_simulation_id = simulation_id
        raise RuntimeError("simulated Redis outage")

    async def delete_state(self, simulation_id: uuid.UUID) -> None:
        return None

    async def get_state(self, simulation_id: uuid.UUID):
        return None


async def test_start_simulation_compensates_when_redis_initialization_fails(
    user: User, pitch: Pitch, judge_persona: JudgePersona, mongo_conversations_collection, redis_test_client
) -> None:
    fake_redis = _FailingRedisStateRepo()
    simulation_id: uuid.UUID | None = None
    try:
        async with async_session_maker() as session:
            service = SimulationService(
                session, MongoConversationRepository(mongo_conversations_collection), fake_redis
            )
            with pytest.raises(SimulationPersistenceError):
                await service.start_simulation(
                    user_id=user.id,
                    pitch_id=pitch.id,
                    judge_persona_id=judge_persona.id,
                    difficulty=Difficulty.PRACTICE,
                )

        simulation_id = fake_redis.attempted_simulation_id
        assert simulation_id is not None

        # SQL rolled back: no half-created session remains.
        async with async_session_maker() as session:
            assert await session.get(SimulationSession, simulation_id) is None
            result = await session.execute(
                select(SimulationSession).where(SimulationSession.user_id == user.id)
            )
            assert result.scalars().all() == []

        # Mongo cleanup was attempted and succeeded (Mongo itself is real/healthy).
        document = await mongo_conversations_collection.find_one({"simulation_id": str(simulation_id)})
        assert document is None
    finally:
        if simulation_id is not None:
            await _cleanup_simulation(simulation_id, mongo_conversations_collection, redis_test_client)
