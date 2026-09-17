"""SimulationSession repository — database access only.

No phase-transition, scoring, or workflow decisions live here. This
repository persists exactly what it is told: creation with a given
pitch_snapshot, and durable checkpoint fields when the (future)
SimulationService decides they should change.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models import DealStatus, Difficulty, SimulationPhase, SimulationSession, SimulationStatus
from app.repositories.base import UNSET, BaseRepository, DEFAULT_LIMIT, Unset, clamp_limit


class SimulationSessionRepository(BaseRepository):
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        judge_persona_id: uuid.UUID,
        pitch_snapshot: dict[str, Any],
        judge_config_version: str,
        difficulty: Difficulty,
        pitch_id: uuid.UUID | None = None,
    ) -> SimulationSession:
        """Create a session. `pitch_snapshot` is accepted as-is — building it
        from a Pitch is SimulationService's job, not this repository's."""
        session_row = SimulationSession(
            user_id=user_id,
            pitch_id=pitch_id,
            judge_persona_id=judge_persona_id,
            pitch_snapshot=pitch_snapshot,
            judge_config_version=judge_config_version,
            difficulty=difficulty,
        )
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def get_by_id(self, session_id: uuid.UUID) -> SimulationSession | None:
        return await self.session.get(SimulationSession, session_id)

    async def get_by_id_for_user(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> SimulationSession | None:
        result = await self.session.execute(
            select(SimulationSession).where(
                SimulationSession.id == session_id, SimulationSession.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[SimulationSession]:
        result = await self.session.execute(
            select(SimulationSession)
            .where(SimulationSession.user_id == user_id)
            .order_by(SimulationSession.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_user_and_status(
        self,
        user_id: uuid.UUID,
        status: SimulationStatus,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[SimulationSession]:
        result = await self.session.execute(
            select(SimulationSession)
            .where(SimulationSession.user_id == user_id, SimulationSession.status == status)
            .order_by(SimulationSession.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_checkpoint(
        self,
        session_row: SimulationSession,
        *,
        status: SimulationStatus | Unset = UNSET,
        current_phase: SimulationPhase | Unset = UNSET,
        battle_round_count: int | Unset = UNSET,
        deal_round_count: int | Unset = UNSET,
        deal_status: DealStatus | Unset = UNSET,
        deal_type: str | None | Unset = UNSET,
        completed_at: datetime | None | Unset = UNSET,
        failure_reason: str | None | Unset = UNSET,
    ) -> SimulationSession:
        """Persist only the durable fields explicitly passed.

        Does not decide whether a transition is valid, whether a battle
        should end, whether Deal is available, or how rounds increment —
        those are SimulationService responsibilities.
        """
        if status is not UNSET:
            session_row.status = status
        if current_phase is not UNSET:
            session_row.current_phase = current_phase
        if battle_round_count is not UNSET:
            session_row.battle_round_count = battle_round_count
        if deal_round_count is not UNSET:
            session_row.deal_round_count = deal_round_count
        if deal_status is not UNSET:
            session_row.deal_status = deal_status
        if deal_type is not UNSET:
            session_row.deal_type = deal_type
        if completed_at is not UNSET:
            session_row.completed_at = completed_at
        if failure_reason is not UNSET:
            session_row.failure_reason = failure_reason
        await self.session.flush()
        return session_row

    async def delete(self, session_row: SimulationSession) -> None:
        """Deletes the session. PostgreSQL cascades this to its Scorecards."""
        await self.session.delete(session_row)
