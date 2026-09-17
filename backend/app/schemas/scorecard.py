"""Scorecard response schema."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ScorecardType
from app.schemas.common import CriterionResult


class ScorecardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    simulation_session_id: uuid.UUID
    scorecard_type: ScorecardType
    overall_score: Decimal
    overall_label: str | None
    rubric_version: str
    basis: str | None
    dimensions: dict[str, CriterionResult]
    strengths: list[Any]
    weaknesses: list[Any]
    feedback: str | None
    coaching: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
