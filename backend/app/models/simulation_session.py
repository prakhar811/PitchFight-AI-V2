"""SimulationSession model.

The permanent record for one complete founder journey: pitch battle ->
pitch score -> optional retry -> optional deal -> final result. There is
no separate PitchBattle or Deal SQL entity — those are phases of a single
session. Conversation history and live working state live in MongoDB and
Redis respectively, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.postgres import Base
from app.models.enums import DealStatus, Difficulty, SimulationPhase, SimulationStatus, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.judge_persona import JudgePersona
    from app.models.pitch import Pitch
    from app.models.scorecard import Scorecard
    from app.models.user import User


class SimulationSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "simulation_sessions"
    __table_args__ = (
        CheckConstraint("battle_round_count >= 0", name="ck_simulation_sessions_battle_round_count_nonneg"),
        CheckConstraint("deal_round_count >= 0", name="ck_simulation_sessions_deal_round_count_nonneg"),
        Index("ix_simulation_sessions_user_id_created_at", "user_id", "created_at"),
        Index("ix_simulation_sessions_user_id_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pitch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pitches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    judge_persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("judge_personas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Immutable copy of the eight pitch fields as they were when this
    # simulation started — survives edits or deletion of the source Pitch.
    pitch_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    judge_config_version: Mapped[str] = mapped_column(String(64), nullable=False)

    difficulty: Mapped[Difficulty] = mapped_column(
        pg_enum(Difficulty, "difficulty"), nullable=False
    )
    status: Mapped[SimulationStatus] = mapped_column(
        pg_enum(SimulationStatus, "simulation_status"),
        nullable=False,
        default=SimulationStatus.ACTIVE,
        server_default=text(f"'{SimulationStatus.ACTIVE.value}'"),
    )
    current_phase: Mapped[SimulationPhase] = mapped_column(
        pg_enum(SimulationPhase, "simulation_phase"),
        nullable=False,
        default=SimulationPhase.PITCH_BATTLE,
        server_default=text(f"'{SimulationPhase.PITCH_BATTLE.value}'"),
    )

    battle_round_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    deal_round_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    deal_status: Mapped[DealStatus] = mapped_column(
        pg_enum(DealStatus, "deal_status"),
        nullable=False,
        default=DealStatus.NOT_AVAILABLE,
        server_default=text(f"'{DealStatus.NOT_AVAILABLE.value}'"),
    )
    deal_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="simulation_sessions")
    pitch: Mapped["Pitch | None"] = relationship(back_populates="simulation_sessions")
    judge_persona: Mapped["JudgePersona"] = relationship(back_populates="simulation_sessions")
    scorecards: Mapped[list["Scorecard"]] = relationship(
        back_populates="simulation_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
