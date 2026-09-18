"""JudgePersonaRepository — minimal read access to the judge catalog.

Judge personas are seeded catalog data (see
app/database/seed_judge_personas.py) — no create/update/delete surface
here, only what simulation start needs to validate a judge selection.
"""

import uuid

from app.models import JudgePersona
from app.repositories.base import BaseRepository


class JudgePersonaRepository(BaseRepository):
    async def get_by_id(self, judge_persona_id: uuid.UUID) -> JudgePersona | None:
        return await self.session.get(JudgePersona, judge_persona_id)

    async def get_active_by_id(self, judge_persona_id: uuid.UUID) -> JudgePersona | None:
        persona = await self.get_by_id(judge_persona_id)
        if persona is None or not persona.active:
            return None
        return persona
