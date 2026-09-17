"""Scorecard repository — database access only.

Official scorecards are immutable once created: no update method is
provided on purpose. The DB's unique(simulation_session_id, scorecard_type)
constraint is the source of truth for "one scorecard per type per session";
this repository does not catch or hide IntegrityError from a duplicate.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.models import Scorecard, ScorecardType
from app.repositories.base import BaseRepository


class ScoreRepository(BaseRepository):
    async def create(
        self,
        *,
        simulation_session_id: uuid.UUID,
        scorecard_type: ScorecardType,
        overall_score: Decimal | str,
        rubric_version: str,
        dimensions: dict[str, Any],
        overall_label: str | None = None,
        basis: str | None = None,
        strengths: list[Any] | None = None,
        weaknesses: list[Any] | None = None,
        feedback: str | None = None,
        coaching: dict[str, Any] | None = None,
    ) -> Scorecard:
        """Store an already-calculated scorecard. No score aggregation happens here."""
        scorecard = Scorecard(
            simulation_session_id=simulation_session_id,
            scorecard_type=scorecard_type,
            overall_score=overall_score,
            rubric_version=rubric_version,
            dimensions=dimensions,
            overall_label=overall_label,
            basis=basis,
            feedback=feedback,
        )
        # Omit these entirely when not given, so the model's own JSONB
        # defaults ([] / {}) apply at flush instead of overwriting with None.
        if strengths is not None:
            scorecard.strengths = strengths
        if weaknesses is not None:
            scorecard.weaknesses = weaknesses
        if coaching is not None:
            scorecard.coaching = coaching

        self.session.add(scorecard)
        await self.session.flush()
        return scorecard

    async def get_by_id(self, scorecard_id: uuid.UUID) -> Scorecard | None:
        return await self.session.get(Scorecard, scorecard_id)

    async def get_by_session_and_type(
        self, simulation_session_id: uuid.UUID, scorecard_type: ScorecardType
    ) -> Scorecard | None:
        result = await self.session.execute(
            select(Scorecard).where(
                Scorecard.simulation_session_id == simulation_session_id,
                Scorecard.scorecard_type == scorecard_type,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_session(self, simulation_session_id: uuid.UUID) -> list[Scorecard]:
        result = await self.session.execute(
            select(Scorecard).where(Scorecard.simulation_session_id == simulation_session_id)
        )
        return list(result.scalars().all())

    async def get_final_for_session(self, simulation_session_id: uuid.UUID) -> Scorecard | None:
        return await self.get_by_session_and_type(simulation_session_id, ScorecardType.FINAL)
