"""VoiceStateCache — short-lived state for a voice interaction being processed.

A plain Redis STRING keyed by (simulation_id, turn_id). Holds only small
temporary processing metadata (e.g. status, transcript, delivery metadata)
— never raw audio (no base64/wav/mp3 bytes). Transcription itself is a
future phase; this only provides the cache mechanics.
"""

import uuid
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.repositories.redis_base import from_json, to_json


def voice_state_key(simulation_id: uuid.UUID, turn_id: str) -> str:
    return f"session:{simulation_id}:voice:{turn_id}"


class VoiceStateCache:
    def __init__(self, client: redis.Redis, ttl_seconds: int | None = None) -> None:
        self._client = client
        self._ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.REDIS_VOICE_TTL_SECONDS
        )

    async def get(self, simulation_id: uuid.UUID, turn_id: str) -> Any | None:
        raw = await self._client.get(voice_state_key(simulation_id, turn_id))
        if raw is None:
            return None
        return from_json(raw)

    async def set(self, simulation_id: uuid.UUID, turn_id: str, state: Any) -> None:
        await self._client.set(
            voice_state_key(simulation_id, turn_id), to_json(state), ex=self._ttl_seconds
        )

    async def delete(self, simulation_id: uuid.UUID, turn_id: str) -> None:
        await self._client.delete(voice_state_key(simulation_id, turn_id))
