"""Idempotent seed for the three initial judge personas.

Run with: python -m app.database.seed_judge_personas
Safe to run repeatedly — existing personas (matched by persona_type) are
left untouched rather than duplicated.
"""

import asyncio

from sqlalchemy import select

from app.database.postgres import async_session_maker
from app.models import JudgePersona

JUDGE_PERSONAS: list[dict[str, str]] = [
    {
        "persona_type": "skeptical_vc",
        "name": "Skeptical VC",
        "description": (
            "A direct, ROI-focused investor who presses on market size, moat, "
            "retention, and revenue logic before buying into the pitch."
        ),
        "config_key": "skeptical_vc",
    },
    {
        "persona_type": "technical_judge",
        "name": "Technical Judge",
        "description": (
            "A precise, systems-minded evaluator who questions whether AI is "
            "necessary and probes architecture, scalability, and data quality."
        ),
        "config_key": "technical_judge",
    },
    {
        "persona_type": "hackathon_judge",
        "name": "Hackathon Judge",
        "description": (
            "A fast-paced, demo-focused judge who prizes novelty, demo clarity, "
            "MVP strength, and clear user pain over hype."
        ),
        "config_key": "hackathon_judge",
    },
]


async def seed_judge_personas() -> None:
    async with async_session_maker() as session:
        existing = await session.execute(select(JudgePersona.persona_type))
        existing_types = {row[0] for row in existing.all()}

        for persona in JUDGE_PERSONAS:
            if persona["persona_type"] in existing_types:
                continue
            session.add(JudgePersona(active=True, **persona))

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_judge_personas())
