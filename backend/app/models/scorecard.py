"""Scorecard model — immutable official evaluation results.

One table supports PITCH, DEAL, and FINAL scorecards. At most one official
scorecard of each type may exist per simulation session.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.postgres import Base
from app.models.enums import ScorecardType, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.simulation_session import SimulationSession


class Scorecard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scorecards"
    __table_args__ = (
        UniqueConstraint(
            "simulation_session_id", "scorecard_type", name="uq_scorecards_session_type"
        ),
        CheckConstraint(
            "overall_score >= 0 AND overall_score <= 100", name="ck_scorecards_overall_score_range"
        ),
    )

    simulation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scorecard_type: Mapped[ScorecardType] = mapped_column(
        pg_enum(ScorecardType, "scorecard_type"), nullable=False
    )

    overall_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    overall_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rubric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    basis: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # {"criterion_name": {"score": ..., "weight": ..., "reason": "...", "evidence": [...]}}
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    strengths: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    weaknesses: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    coaching: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb")
    )

    simulation_session: Mapped["SimulationSession"] = relationship(back_populates="scorecards")
