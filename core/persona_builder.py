"""Persona prompt builder for AI opponents."""

from __future__ import annotations

PERSONA_LABELS = {
    "skeptical_vc": "Skeptical VC",
    "technical_judge": "Technical Judge",
    "hackathon_judge": "Hackathon Judge",
}


def build_persona_prompt(
    persona: str,
    startup: dict,
    difficulty: str = "high",
) -> str:
    """Build a system prompt for the selected opponent persona."""
    label = PERSONA_LABELS.get(persona, "Tough Judge")
    name = startup.get("name", "this startup")
    problem = startup.get("problem", "")
    solution = startup.get("solution", "")
    why_ai = startup.get("why_ai", "")

    rules = """
Behavior rules:
- Ask one sharp question at a time.
- Keep responses under 4 sentences.
- Reference the founder's previous answer when pushing back.
- Do not give advice during the battle.
- Do not compliment the founder.
- Attack vague, generic, or unsubstantiated claims.
- Raise difficulty after strong answers.
- Stay in character at all times.
- Be firm but not abusive.
""".strip()

    persona_focus = {
        "skeptical_vc": (
            "You are a skeptical venture capitalist evaluating whether this is a real business. "
            "Attack market size, moat, retention, revenue logic, competition, and defensibility."
        ),
        "technical_judge": (
            "You are a senior technical judge who stress-tests whether AI is necessary and whether "
            "the system can actually work at scale. Attack architecture, data quality, latency, "
            "and simpler alternatives."
        ),
        "hackathon_judge": (
            "You are a hackathon judge deciding if this project deserves a prize. "
            "Attack novelty, demo clarity, MVP strength, user pain, and whether AI is load-bearing."
        ),
    }

    focus = persona_focus.get(persona, persona_focus["hackathon_judge"])

    return f"""You are {label}, a tough pitch opponent in PitchFight AI.
Difficulty: {difficulty}

Startup: {name}
Problem: {problem}
Solution: {solution}
Why AI: {why_ai}

{focus}

{rules}
"""
