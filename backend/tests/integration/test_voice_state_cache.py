"""VoiceStateCache integration tests against real Redis (isolated test db)."""

import uuid

import pytest
import redis.asyncio as redis

from app.repositories.voice_state_cache import VoiceStateCache, voice_state_key


def _new_sim_id() -> uuid.UUID:
    return uuid.uuid4()


async def test_set_and_get_round_trips(redis_test_client: redis.Redis) -> None:
    cache = VoiceStateCache(redis_test_client)
    sim_id = _new_sim_id()
    turn_id = "turn-1"
    try:
        state = {"status": "PROCESSING", "transcript": "hello there"}
        await cache.set(sim_id, turn_id, state)

        fetched = await cache.get(sim_id, turn_id)
        assert fetched == state
    finally:
        await cache.delete(sim_id, turn_id)


async def test_get_missing_returns_none(redis_test_client: redis.Redis) -> None:
    cache = VoiceStateCache(redis_test_client)
    assert await cache.get(_new_sim_id(), "no-such-turn") is None


async def test_delete_removes_state(redis_test_client: redis.Redis) -> None:
    cache = VoiceStateCache(redis_test_client)
    sim_id = _new_sim_id()
    turn_id = "turn-1"
    await cache.set(sim_id, turn_id, {"status": "DONE"})
    await cache.delete(sim_id, turn_id)
    assert await cache.get(sim_id, turn_id) is None


async def test_independent_turn_ids_do_not_collide(redis_test_client: redis.Redis) -> None:
    cache = VoiceStateCache(redis_test_client)
    sim_id = _new_sim_id()
    try:
        await cache.set(sim_id, "turn-1", {"status": "PROCESSING"})
        await cache.set(sim_id, "turn-2", {"status": "DONE"})

        assert await cache.get(sim_id, "turn-1") == {"status": "PROCESSING"}
        assert await cache.get(sim_id, "turn-2") == {"status": "DONE"}
    finally:
        await cache.delete(sim_id, "turn-1")
        await cache.delete(sim_id, "turn-2")


async def test_independent_simulations_do_not_collide_on_same_turn_id(
    redis_test_client: redis.Redis,
) -> None:
    cache = VoiceStateCache(redis_test_client)
    sim_id_a = _new_sim_id()
    sim_id_b = _new_sim_id()
    try:
        await cache.set(sim_id_a, "turn-1", {"status": "PROCESSING"})
        await cache.set(sim_id_b, "turn-1", {"status": "DONE"})

        assert await cache.get(sim_id_a, "turn-1") == {"status": "PROCESSING"}
        assert await cache.get(sim_id_b, "turn-1") == {"status": "DONE"}
    finally:
        await cache.delete(sim_id_a, "turn-1")
        await cache.delete(sim_id_b, "turn-1")


async def test_set_applies_ttl(redis_test_client: redis.Redis) -> None:
    cache = VoiceStateCache(redis_test_client)
    sim_id = _new_sim_id()
    turn_id = "turn-1"
    try:
        await cache.set(sim_id, turn_id, {"status": "PROCESSING"})
        ttl = await redis_test_client.ttl(voice_state_key(sim_id, turn_id))
        assert 0 < ttl <= cache._ttl_seconds
    finally:
        await cache.delete(sim_id, turn_id)
