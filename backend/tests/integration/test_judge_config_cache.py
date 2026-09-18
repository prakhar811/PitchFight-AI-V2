"""JudgeConfigCache integration tests against real Redis (isolated test db)."""

import uuid

import pytest
import redis.asyncio as redis

from app.repositories.judge_config_cache import JudgeConfigCache, judge_config_key


def _unique_persona_type() -> str:
    return f"test_judge_{uuid.uuid4().hex[:8]}"


def _sample_config() -> dict:
    return {
        "persona_type": "skeptical_vc",
        "config_key": "skeptical_vc",
        "rubric_weights": {"market_size": 0.3, "moat": 0.2, "revenue_logic": 0.5},
        "tone": "direct",
        "focus_areas": ["Market Size", "Moat", "Revenue Logic"],
    }


async def test_set_and_get_round_trips(redis_test_client: redis.Redis) -> None:
    cache = JudgeConfigCache(redis_test_client)
    persona_type = _unique_persona_type()
    try:
        config = _sample_config()
        await cache.set(persona_type, config)

        fetched = await cache.get(persona_type)
        assert fetched == config
    finally:
        await cache.delete(persona_type)


async def test_get_missing_returns_none(redis_test_client: redis.Redis) -> None:
    cache = JudgeConfigCache(redis_test_client)
    assert await cache.get(_unique_persona_type()) is None


async def test_delete_removes_config(redis_test_client: redis.Redis) -> None:
    cache = JudgeConfigCache(redis_test_client)
    persona_type = _unique_persona_type()
    await cache.set(persona_type, _sample_config())
    await cache.delete(persona_type)
    assert await cache.get(persona_type) is None


async def test_delete_missing_is_a_no_op(redis_test_client: redis.Redis) -> None:
    cache = JudgeConfigCache(redis_test_client)
    await cache.delete(_unique_persona_type())  # must not raise


async def test_nested_configuration_round_trips(redis_test_client: redis.Redis) -> None:
    cache = JudgeConfigCache(redis_test_client)
    persona_type = _unique_persona_type()
    try:
        config = {
            "rubric_weights": {"market_size": 0.3},
            "focus_areas": ["Market Size", "Moat"],
            "scoring_calibration": {"floor": 32, "ranges": [[32, 48], [48, 65]]},
        }
        await cache.set(persona_type, config)
        fetched = await cache.get(persona_type)
        assert fetched == config
    finally:
        await cache.delete(persona_type)


async def test_set_applies_ttl(redis_test_client: redis.Redis) -> None:
    cache = JudgeConfigCache(redis_test_client)
    persona_type = _unique_persona_type()
    try:
        await cache.set(persona_type, _sample_config())
        ttl = await redis_test_client.ttl(judge_config_key(persona_type))
        assert 0 < ttl <= cache._ttl_seconds
    finally:
        await cache.delete(persona_type)
