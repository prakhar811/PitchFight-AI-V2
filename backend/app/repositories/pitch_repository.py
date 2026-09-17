"""Pitch repository — database access only, ownership-aware queries.

Ownership-scoped lookups exist so future API routes can never let one user
read or mutate another user's pitch. Authorization *decisions* still belong
to the service/route layer — this just exposes the queries needed to make
them safely.
"""

import uuid

from sqlalchemy import select

from app.models import Pitch
from app.repositories.base import UNSET, BaseRepository, DEFAULT_LIMIT, Unset, clamp_limit


class PitchRepository(BaseRepository):
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        startup_name: str,
        problem: str,
        target_users: str,
        solution: str,
        why_ai: str | None = None,
        traction: str | None = None,
        competitors: str | None = None,
        ask: str | None = None,
    ) -> Pitch:
        pitch = Pitch(
            user_id=user_id,
            startup_name=startup_name,
            problem=problem,
            target_users=target_users,
            solution=solution,
            why_ai=why_ai,
            traction=traction,
            competitors=competitors,
            ask=ask,
        )
        self.session.add(pitch)
        await self.session.flush()
        return pitch

    async def get_by_id(self, pitch_id: uuid.UUID) -> Pitch | None:
        return await self.session.get(Pitch, pitch_id)

    async def get_by_id_for_user(self, pitch_id: uuid.UUID, user_id: uuid.UUID) -> Pitch | None:
        result = await self.session.execute(
            select(Pitch).where(Pitch.id == pitch_id, Pitch.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Pitch]:
        result = await self.session.execute(
            select(Pitch)
            .where(Pitch.user_id == user_id)
            .order_by(Pitch.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update(
        self,
        pitch: Pitch,
        *,
        startup_name: str | Unset = UNSET,
        problem: str | Unset = UNSET,
        target_users: str | Unset = UNSET,
        solution: str | Unset = UNSET,
        why_ai: str | None | Unset = UNSET,
        traction: str | None | Unset = UNSET,
        competitors: str | None | Unset = UNSET,
        ask: str | None | Unset = UNSET,
    ) -> Pitch:
        """Apply only the fields explicitly passed; everything else is untouched.

        Does not touch historical SimulationSession.pitch_snapshot rows —
        those stay immutable by construction.
        """
        if startup_name is not UNSET:
            pitch.startup_name = startup_name
        if problem is not UNSET:
            pitch.problem = problem
        if target_users is not UNSET:
            pitch.target_users = target_users
        if solution is not UNSET:
            pitch.solution = solution
        if why_ai is not UNSET:
            pitch.why_ai = why_ai
        if traction is not UNSET:
            pitch.traction = traction
        if competitors is not UNSET:
            pitch.competitors = competitors
        if ask is not UNSET:
            pitch.ask = ask
        await self.session.flush()
        return pitch

    async def delete(self, pitch: Pitch) -> None:
        await self.session.delete(pitch)
