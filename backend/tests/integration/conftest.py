"""Shared fixtures for PostgreSQL integration tests.

Requires the docker-compose `postgres` service to be up with the initial
Alembic migration applied.
"""

import uuid

import pytest
from sqlalchemy import delete

from app.database.postgres import async_session_maker
from app.models import JudgePersona, User


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
