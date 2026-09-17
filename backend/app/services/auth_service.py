"""Auth orchestration: registration and login.

No SQL lives here — that's UserRepository's job. No HTTP concerns either —
routes translate these domain exceptions into responses. This is also the
first service, so it owns the transaction boundary that Phase 5 repositories
deliberately left open: it commits/rolls back, repositories only flush.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models import User
from app.repositories.user_repository import UserRepository


class EmailAlreadyRegisteredError(Exception):
    """Raised when registering an email that already has an account."""


class InvalidCredentialsError(Exception):
    """Raised for any login failure. Never says which part was wrong."""


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register_user(self, *, email: str, password: str) -> User:
        normalized_email = _normalize_email(email)

        if await self.users.get_by_email(normalized_email) is not None:
            raise EmailAlreadyRegisteredError(normalized_email)

        password_hash = hash_password(password)

        try:
            # UserRepository.create() flushes internally, so a concurrent
            # duplicate registration (the pre-check above can't catch a
            # race) surfaces here as an IntegrityError from the DB's unique
            # constraint on email — not deferred to commit().
            user = await self.users.create(email=normalized_email, password_hash=password_hash)
        except IntegrityError:
            await self.session.rollback()
            raise EmailAlreadyRegisteredError(normalized_email) from None

        await self.session.commit()
        return user

    async def authenticate_user(self, *, email: str, password: str) -> User:
        normalized_email = _normalize_email(email)
        user = await self.users.get_by_email(normalized_email)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        return user
