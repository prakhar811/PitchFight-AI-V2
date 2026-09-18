"""JudgeConfigCache — Redis cache for resolved/versioned judge configuration.

A plain Redis STRING per persona_type: the whole config is replaced as one
unit (no partial-field update requirement here, unlike session state), so a
single JSON string is simpler than a HASH.

This phase only implements cache mechanics — it does not load real judge
prompts/config files. That's for the future Prompt/Simulation layers.
"""

from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.repositories.redis_base import from_json, to_json


def judge_config_key(persona_type: str) -> str:
    return f"judge:{persona_type}:config"


class JudgeConfigCache:
    def __init__(self, client: redis.Redis, ttl_seconds: int | None = None) -> None:
        self._client = client
        self._ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.REDIS_JUDGE_CONFIG_TTL_SECONDS
        )

    async def get(self, persona_type: str) -> Any | None:
        raw = await self._client.get(judge_config_key(persona_type))
        if raw is None:
            return None
        return from_json(raw)

    async def set(self, persona_type: str, config: Any) -> None:
        await self._client.set(judge_config_key(persona_type), to_json(config), ex=self._ttl_seconds)

    async def delete(self, persona_type: str) -> None:
        await self._client.delete(judge_config_key(persona_type))
