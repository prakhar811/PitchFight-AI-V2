"""Redis connectivity check against the real Docker container.

Uses the actual app-configured client (db 0 via REDIS_URL) — PING never
writes data, so this is safe without touching the isolated test db.
"""

from app.database.redis import get_redis_client, ping


async def test_redis_ping_succeeds() -> None:
    await ping()  # must not raise


async def test_redis_client_is_a_process_wide_singleton() -> None:
    assert get_redis_client() is get_redis_client()
