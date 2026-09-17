"""Pitch request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PitchCreate(BaseModel):
    startup_name: str
    problem: str
    target_users: str
    solution: str
    why_ai: str | None = None
    traction: str | None = None
    competitors: str | None = None
    ask: str | None = None


class PitchUpdate(BaseModel):
    startup_name: str | None = None
    problem: str | None = None
    target_users: str | None = None
    solution: str | None = None
    why_ai: str | None = None
    traction: str | None = None
    competitors: str | None = None
    ask: str | None = None


class PitchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    startup_name: str
    problem: str
    target_users: str
    solution: str
    why_ai: str | None
    traction: str | None
    competitors: str | None
    ask: str | None
    created_at: datetime
    updated_at: datetime
