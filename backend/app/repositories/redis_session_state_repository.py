"""RedisSessionStateRepository — fast-changing live state for an ACTIVE
simulation.

Redis is a temporary cache/working-state layer only. PostgreSQL
(simulation_sessions) and MongoDB (conversation events) remain the durable
sources of truth; a missing Redis key is a normal cache miss, not data
loss — reconstruction from Postgres+Mongo is SimulationService's job
(future phase), not this repository's.

Stored as a Redis HASH, not one JSON string, specifically so update_state
can atomically merge a subset of fields: HSET on multiple fields is a
single atomic Redis command (Redis is single-threaded per command), so two
concurrent partial updates to different fields can never race each other
into a lost update the way a GET -> modify dict -> SET round trip could.
Nested values (attack_attempts, completed_attack_tags, ...) are JSON-encoded
as individual hash field values.
"""

import uuid
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.repositories.redis_base import from_json, to_json


def session_state_key(simulation_id: uuid.UUID) -> str:
    return f"session:{simulation_id}:state"


class RedisSessionStateRepository:
    def __init__(self, client: redis.Redis, ttl_seconds: int | None = None) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.REDIS_SESSION_TTL_SECONDS

    async def get_state(self, simulation_id: uuid.UUID) -> dict[str, Any] | None:
        raw = await self._client.hgetall(session_state_key(simulation_id))
        if not raw:
            return None
        return {field: from_json(value) for field, value in raw.items()}

    async def set_state(self, simulation_id: uuid.UUID, state: dict[str, Any]) -> None:
        """Replace the entire state (any previously stored fields are cleared)."""
        key = session_state_key(simulation_id)
        mapping = {field: to_json(value) for field, value in state.items()}
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            if mapping:
                pipe.hset(key, mapping=mapping)
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def update_state(self, simulation_id: uuid.UUID, updates: dict[str, Any]) -> None:
        """Atomically merge `updates` into the existing state, leaving other
        fields untouched, and refresh the TTL."""
        if not updates:
            await self.refresh_ttl(simulation_id)
            return
        key = session_state_key(simulation_id)
        mapping = {field: to_json(value) for field, value in updates.items()}
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=mapping)
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def refresh_ttl(self, simulation_id: uuid.UUID) -> None:
        await self._client.expire(session_state_key(simulation_id), self._ttl_seconds)

    async def delete_state(self, simulation_id: uuid.UUID) -> None:
        await self._client.delete(session_state_key(simulation_id))

    async def exists(self, simulation_id: uuid.UUID) -> bool:
        return bool(await self._client.exists(session_state_key(simulation_id)))
