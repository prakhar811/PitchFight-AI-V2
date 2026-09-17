"""AuthService tests against real PostgreSQL.

AuthService owns its transaction boundary (Phase 5's repositories
deliberately don't commit), so these tests exercise that directly rather
than mocking the session.
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.security import verify_password
from app.database.postgres import async_session_maker
from app.models import User
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError, InvalidCredentialsError


async def _cleanup_user_by_email(email: str) -> None:
    async with async_session_maker() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


# ---------------------------------------------------------------------------
# register_user
# ---------------------------------------------------------------------------


async def test_register_user_creates_user_with_hashed_password() -> None:
    email = f"  {uuid.uuid4()}@Example.com  "  # deliberately messy casing/whitespace
    normalized_email = email.strip().lower()
    try:
        async with async_session_maker() as session:
            user = await AuthService(session).register_user(email=email, password="correcthorse123")

            assert user.email == normalized_email
            assert user.password_hash != "correcthorse123"
            assert verify_password("correcthorse123", user.password_hash)

        # Committed: visible from a fresh session.
        async with async_session_maker() as verify_session:
            fetched = await verify_session.get(User, user.id)
            assert fetched is not None
            assert fetched.email == normalized_email
    finally:
        await _cleanup_user_by_email(normalized_email)


async def test_register_user_rejects_duplicate_email() -> None:
    email = f"{uuid.uuid4()}@example.com"
    try:
        async with async_session_maker() as session:
            await AuthService(session).register_user(email=email, password="correcthorse123")

        async with async_session_maker() as session:
            with pytest.raises(EmailAlreadyRegisteredError):
                await AuthService(session).register_user(email=email, password="anotherpassword")
    finally:
        await _cleanup_user_by_email(email)


async def test_register_user_duplicate_check_is_case_and_whitespace_insensitive() -> None:
    base_email = f"{uuid.uuid4()}@example.com"
    try:
        async with async_session_maker() as session:
            await AuthService(session).register_user(email=base_email, password="correcthorse123")

        async with async_session_maker() as session:
            with pytest.raises(EmailAlreadyRegisteredError):
                await AuthService(session).register_user(
                    email=f"  {base_email.upper()}  ", password="anotherpassword"
                )
    finally:
        await _cleanup_user_by_email(base_email)


async def test_register_user_converts_database_race_into_domain_error(monkeypatch) -> None:
    """A pre-check alone can't catch a true race between two requests. Force
    that scenario deterministically: make the pre-check report "no such
    user" even though one already exists, so register_user must fall
    through to the DB's unique constraint and translate the resulting
    IntegrityError into EmailAlreadyRegisteredError (with a rollback)
    instead of leaking a raw database error."""
    email = f"{uuid.uuid4()}@example.com"
    try:
        async with async_session_maker() as session:
            await AuthService(session).register_user(email=email, password="correcthorse123")

        async with async_session_maker() as session:
            service = AuthService(session)

            async def _fake_get_by_email(_email: str) -> None:
                return None

            monkeypatch.setattr(service.users, "get_by_email", _fake_get_by_email)

            with pytest.raises(EmailAlreadyRegisteredError):
                await service.register_user(email=email, password="anotherpassword123")

            # The session must still be usable after the rollback.
            assert await session.execute(delete(User).where(User.email == "no-op@example.com"))
    finally:
        await _cleanup_user_by_email(email)


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------


async def test_authenticate_user_succeeds_with_correct_credentials() -> None:
    email = f"{uuid.uuid4()}@example.com"
    try:
        async with async_session_maker() as session:
            registered = await AuthService(session).register_user(
                email=email, password="correcthorse123"
            )

        async with async_session_maker() as session:
            authenticated = await AuthService(session).authenticate_user(
                email=email, password="correcthorse123"
            )
            assert authenticated.id == registered.id
    finally:
        await _cleanup_user_by_email(email)


async def test_authenticate_user_fails_with_wrong_password() -> None:
    email = f"{uuid.uuid4()}@example.com"
    try:
        async with async_session_maker() as session:
            await AuthService(session).register_user(email=email, password="correcthorse123")

        async with async_session_maker() as session:
            with pytest.raises(InvalidCredentialsError):
                await AuthService(session).authenticate_user(email=email, password="wrong-password")
    finally:
        await _cleanup_user_by_email(email)


async def test_authenticate_user_fails_with_unknown_email() -> None:
    async with async_session_maker() as session:
        with pytest.raises(InvalidCredentialsError):
            await AuthService(session).authenticate_user(
                email="nobody-really@example.com", password="whatever123"
            )


async def test_authenticate_user_wrong_password_and_unknown_email_raise_same_error_type() -> None:
    email = f"{uuid.uuid4()}@example.com"
    try:
        async with async_session_maker() as session:
            await AuthService(session).register_user(email=email, password="correcthorse123")

        async with async_session_maker() as session:
            service = AuthService(session)
            with pytest.raises(InvalidCredentialsError) as wrong_password_exc:
                await service.authenticate_user(email=email, password="wrong-password")
            with pytest.raises(InvalidCredentialsError) as unknown_email_exc:
                await service.authenticate_user(
                    email="definitely-nobody@example.com", password="wrong-password"
                )
        assert type(wrong_password_exc.value) is type(unknown_email_exc.value)
    finally:
        await _cleanup_user_by_email(email)
