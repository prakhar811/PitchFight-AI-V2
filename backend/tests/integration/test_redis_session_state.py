"""RedisSessionStateRepository integration tests against real Redis.

Runs against the isolated test db (see redis_test_client fixture in
conftest.py, Redis db 15) so these tests never touch real dev live-state
keys. Each test cleans up its own key by a unique simulation_id.
"""

import asyncio
import uuid

import pytest
import redis.asyncio as redis

from app.repositories.redis_session_state_repository import (
    RedisSessionStateRepository,
    session_state_key,
)

SHORT_TTL = 1


@pytest.fixture
def repo(redis_test_client: redis.Redis) -> RedisSessionStateRepository:
    return RedisSessionStateRepository(redis_test_client)


def _new_sim_id() -> uuid.UUID:
    return uuid.uuid4()


def _sample_state() -> dict:
    return {
        "simulation_id": "placeholder",
        "current_phase": "PITCH_BATTLE",
        "battle_round": 2,
        "deal_round": 0,
        "active_attack_tag": "business_model",
        "attack_attempts": {"business_model": 1},
        "completed_attack_tags": ["problem_clarity", "market_awareness"],
        "last_answer_quality": 0.78,
        "last_event_sequence": 8,
    }


# ---------------------------------------------------------------------------
# set_state / get_state
# ---------------------------------------------------------------------------


async def test_set_and_get_state_round_trips(
    repo: RedisSessionStateRepository, redis_test_client: redis.Redis
) -> None:
    sim_id = _new_sim_id()
    try:
        state = _sample_state()
        await repo.set_state(sim_id, state)

        fetched = await repo.get_state(sim_id)
        assert fetched == state
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


async def test_get_state_missing_returns_none(repo: RedisSessionStateRepository) -> None:
    assert await repo.get_state(_new_sim_id()) is None


async def test_set_state_round_trips_nested_dict_and_list(
    repo: RedisSessionStateRepository, redis_test_client: redis.Redis
) -> None:
    sim_id = _new_sim_id()
    try:
        state = {
            "attack_attempts": {"business_model": 2, "market_size": 1},
            "completed_attack_tags": ["a", "b", "c"],
        }
        await repo.set_state(sim_id, state)
        fetched = await repo.get_state(sim_id)
        assert fetched["attack_attempts"] == {"business_model": 2, "market_size": 1}
        assert fetched["completed_attack_tags"] == ["a", "b", "c"]
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


async def test_set_state_replaces_previous_fields_entirely(
    repo: RedisSessionStateRepository, redis_test_client: redis.Redis
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.set_state(sim_id, {"battle_round": 1, "deal_round": 0})
        await repo.set_state(sim_id, {"battle_round": 2})

        fetched = await repo.get_state(sim_id)
        assert fetched == {"battle_round": 2}
        assert "deal_round" not in fetched
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


# ---------------------------------------------------------------------------
# update_state
# ---------------------------------------------------------------------------


async def test_update_state_merges_one_field_without_destroying_others(
    repo: RedisSessionStateRepository, redis_test_client: redis.Redis
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.set_state(sim_id, {"battle_round": 1, "deal_round": 0, "current_phase": "PITCH_BATTLE"})
        await repo.update_state(sim_id, {"battle_round": 2})

        fetched = await repo.get_state(sim_id)
        assert fetched["battle_round"] == 2
        assert fetched["deal_round"] == 0
        assert fetched["current_phase"] == "PITCH_BATTLE"
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


async def test_update_state_merges_several_fields(
    repo: RedisSessionStateRepository, redis_test_client: redis.Redis
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.set_state(sim_id, {"battle_round": 1, "deal_round": 0})
        await repo.update_state(sim_id, {"battle_round": 2, "deal_round": 1, "new_field": "x"})

        fetched = await repo.get_state(sim_id)
        assert fetched == {"battle_round": 2, "deal_round": 1, "new_field": "x"}
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


# ---------------------------------------------------------------------------
# exists / delete
# ---------------------------------------------------------------------------


async def test_exists_true_after_set_false_after_delete(
    repo: RedisSessionStateRepository,
) -> None:
    sim_id = _new_sim_id()
    assert await repo.exists(sim_id) is False

    await repo.set_state(sim_id, {"battle_round": 0})
    assert await repo.exists(sim_id) is True

    await repo.delete_state(sim_id)
    assert await repo.exists(sim_id) is False
    assert await repo.get_state(sim_id) is None


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------


async def test_set_state_applies_ttl(
    repo: RedisSessionStateRepository, redis_test_client: redis.Redis
) -> None:
    sim_id = _new_sim_id()
    try:
        await repo.set_state(sim_id, {"battle_round": 0})
        ttl = await redis_test_client.ttl(session_state_key(sim_id))
        assert 0 < ttl <= repo._ttl_seconds
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


async def test_update_state_refreshes_ttl(
    redis_test_client: redis.Redis,
) -> None:
    sim_id = _new_sim_id()
    try:
        repo = RedisSessionStateRepository(redis_test_client, ttl_seconds=100)
        await repo.set_state(sim_id, {"battle_round": 0})
        # Artificially shrink the TTL, then confirm update_state restores it.
        await redis_test_client.expire(session_state_key(sim_id), 2)
        await repo.update_state(sim_id, {"battle_round": 1})

        ttl = await redis_test_client.ttl(session_state_key(sim_id))
        assert ttl > 2
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


async def test_refresh_ttl_explicit(redis_test_client: redis.Redis) -> None:
    sim_id = _new_sim_id()
    try:
        repo = RedisSessionStateRepository(redis_test_client, ttl_seconds=100)
        await repo.set_state(sim_id, {"battle_round": 0})
        await redis_test_client.expire(session_state_key(sim_id), 2)

        await repo.refresh_ttl(sim_id)

        ttl = await redis_test_client.ttl(session_state_key(sim_id))
        assert ttl > 2
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


async def test_state_expires_after_short_ttl(redis_test_client: redis.Redis) -> None:
    sim_id = _new_sim_id()
    try:
        repo = RedisSessionStateRepository(redis_test_client, ttl_seconds=SHORT_TTL)
        await repo.set_state(sim_id, {"battle_round": 0})
        assert await repo.exists(sim_id) is True

        await asyncio.sleep(SHORT_TTL + 0.7)

        assert await repo.exists(sim_id) is False
        assert await repo.get_state(sim_id) is None
    finally:
        await redis_test_client.delete(session_state_key(sim_id))


# ---------------------------------------------------------------------------
# Concurrency: atomic partial updates to independent fields
# ---------------------------------------------------------------------------


async def test_concurrent_updates_to_independent_fields_do_not_lose_writes(
    redis_test_client: redis.Redis,
) -> None:
    sim_id = _new_sim_id()
    try:
        repo = RedisSessionStateRepository(redis_test_client)
        await repo.set_state(sim_id, {f"field_{i}": 0 for i in range(20)})

        await asyncio.gather(
            *(repo.update_state(sim_id, {f"field_{i}": i}) for i in range(20))
        )

        fetched = await repo.get_state(sim_id)
        assert fetched == {f"field_{i}": i for i in range(20)}
    finally:
        await redis_test_client.delete(session_state_key(sim_id))
