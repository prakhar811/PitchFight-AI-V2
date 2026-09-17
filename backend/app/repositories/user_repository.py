"""User repository — database access only.

No password hashing, verification, or JWT logic belongs here; this
repository only stores and retrieves the identity record.
"""

import uuid

from sqlalchemy import select

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, *, email: str, password_hash: str) -> User:
        """Persist a user. `password_hash` must already be hashed by the caller."""
        user = User(email=email, password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user

    async def delete(self, user: User) -> None:
        await self.session.delete(user)
