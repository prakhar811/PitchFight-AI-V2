"""Redis connection layer: async client lifecycle and connectivity checks.

Infrastructure only — no session-state/judge-config/voice-cache business
logic here (see app/repositories/redis_*). Uses redis-py's native async
client (redis.asyncio), already a project dependency (redis[hiredis]).

Redis is a temporary live-state/cache layer. PostgreSQL and MongoDB remain
the permanent sources of truth — this module (and everything built on it)
must never become the only copy of anything important.
"""

import redis.asyncio as redis

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Lazily create the process-wide async Redis client.

    decode_responses=True so callers get str, not bytes, matching the
    JSON-string serialization strategy used throughout the Redis repositories.
    """
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def ping() -> None:
    """Startup connectivity check."""
    await get_redis_client().ping()


async def close_redis_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
