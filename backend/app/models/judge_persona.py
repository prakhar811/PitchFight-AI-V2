"""JudgePersona model — stable catalog of selectable judges."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.postgres import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.simulation_session import SimulationSession


class JudgePersona(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "judge_personas"

    persona_type: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    config_key: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    simulation_sessions: Mapped[list["SimulationSession"]] = relationship(
        back_populates="judge_persona"
    )
