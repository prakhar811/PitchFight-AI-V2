"""Shared repository infrastructure.

Kept intentionally tiny — a generic repository framework is not needed for
five concrete repositories.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def clamp_limit(limit: int) -> int:
    """Keep list-query page sizes within sane, safe bounds."""
    return max(1, min(limit, MAX_LIMIT))


class Unset:
    """Sentinel distinguishing 'field not provided' from 'field set to None'.

    Lets partial-update repository methods use explicit keyword parameters
    (safe) instead of `setattr(model, **arbitrary_kwargs)` (unsafe).
    """

    def __repr__(self) -> str:
        return "<UNSET>"


UNSET: Any = Unset()


class BaseRepository:
    """Holds the AsyncSession. Does not commit — callers own transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
