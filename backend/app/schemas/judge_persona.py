"""JudgePersona response schema."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JudgePersonaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    persona_type: str
    name: str
    description: str
    config_key: str
    active: bool
    created_at: datetime
    updated_at: datetime
