"""Shared fixtures for PostgreSQL and MongoDB integration tests.

Requires the docker-compose `postgres` and `mongo` services to be up (with
the initial Alembic migration applied for Postgres).
"""

import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
import redis.asyncio as redis
from pymongo.asynchronous.collection import AsyncCollection
from sqlalchemy import delete

from app.core.config import settings
from app.database.mongo import get_mongo_client
from app.database.postgres import async_session_maker
from app.models import JudgePersona, User

# Mongo tests run against a dedicated database, never the dev `pitchfight`
# database, so leftover/failed test runs can never pollute real dev data.
MONGO_TEST_DB_NAME = "pitchfight_test"

# Redis tests run against a dedicated logical DB (same server, same
# REDIS_URL host/port/auth, different db index) — never the app's real
# db 0 — so a session-end FLUSHDB can never wipe real dev keys.
REDIS_TEST_DB_INDEX = 15


@pytest.fixture
async def user() -> User:
    async with async_session_maker() as session:
        new_user = User(email=f"{uuid.uuid4()}@example.com", password_hash="hashed")
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        yield new_user
        # Bulk delete (not session.delete on a possibly stale identity-mapped
        # object) since a test may have already deleted this row itself, and
        # the row may since have been cascade-deleted at the DB level without
        # this session's identity map knowing.
        await session.execute(delete(User).where(User.id == new_user.id))
        await session.commit()


@pytest.fixture
async def judge_persona() -> JudgePersona:
    async with async_session_maker() as session:
        persona = JudgePersona(
            persona_type=f"test_{uuid.uuid4().hex[:8]}",
            name="Test Judge",
            description="A judge used only in tests.",
            config_key="test_judge",
        )
        session.add(persona)
        await session.commit()
        await session.refresh(persona)
        yield persona
        await session.execute(delete(JudgePersona).where(JudgePersona.id == persona.id))
        await session.commit()


@pytest.fixture(scope="session")
async def mongo_conversations_collection() -> AsyncCollection:
    client = get_mongo_client()
    collection = client[MONGO_TEST_DB_NAME]["simulation_conversations"]
    await collection.create_index(
        "simulation_id", unique=True, name="uq_simulation_conversations_simulation_id"
    )
    yield collection
    await client.drop_database(MONGO_TEST_DB_NAME)


def _with_db_index(url: str, db: int) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db}"))


@pytest.fixture(scope="session")
async def redis_test_client() -> redis.Redis:
    test_url = _with_db_index(settings.REDIS_URL, REDIS_TEST_DB_INDEX)
    client = redis.from_url(test_url, decode_responses=True)
    await client.ping()
    yield client
    await client.flushdb()  # safe: only ever touches the isolated test db
    await client.aclose()
