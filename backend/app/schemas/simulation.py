"""SimulationSession response schema.

Exposes durable relational metadata only — conversation history, retry
content, and other in-progress state live in MongoDB/Redis and are not
part of this schema.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import DealStatus, Difficulty, SimulationPhase, SimulationStatus


class SimulationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    pitch_id: uuid.UUID | None
    judge_persona_id: uuid.UUID
    pitch_snapshot: dict[str, Any]
    judge_config_version: str
    difficulty: Difficulty
    status: SimulationStatus
    current_phase: SimulationPhase
    battle_round_count: int
    deal_round_count: int
    deal_status: DealStatus
    deal_type: str | None
    started_at: datetime
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
