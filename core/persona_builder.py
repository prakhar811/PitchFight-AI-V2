"""Persona prompt builder for AI opponents."""

from __future__ import annotations

from core.judge_settings import get_question_style, normalize_difficulty

PERSONA_LABELS = {
    "skeptical_vc": "Skeptical VC",
    "technical_judge": "Technical Judge",
    "hackathon_judge": "Hackathon Judge",
}


def build_persona_prompt(
    persona: str,
    startup: dict,
    difficulty: str = "practice",
) -> str:
    """Build a system prompt for the selected opponent persona.

    The difficulty argument accepts any alias (e.g. "high", "practice",
    "beginner") — it is normalized to a canonical profile internally.
    question_style.instruction from the profile is injected so Nemotron
    adjusts wording complexity, jargon level, and tone accordingly.
    """
    profile_name = normalize_difficulty(difficulty)
    qs = get_question_style(profile_name)

    label = PERSONA_LABELS.get(persona, "Tough Judge")
    name = startup.get("name", "this startup")
    problem = startup.get("problem", "")
    solution = startup.get("solution", "")
    why_ai = startup.get("why_ai", "")

    # Behavior rules shared across all personas
    max_sentences = qs.get("max_sentences", 3)
    avoid_jargon = qs.get("avoid_jargon", False)
    jargon_note = (
        "\n- FORBIDDEN WORDS for this profile: unit economics, contribution margin, defensibility, "
        "TAM, SAM, SOM, moat, CAC, LTV, load-bearing, demonstrably, quantify match accuracy, "
        "precision threshold. Use plain student-friendly language instead."
        if avoid_jargon else ""
    )
    rules = f"""Behavior rules:
- Ask one question at a time — never ask two questions in a single response.
- Keep responses under {max_sentences} sentences.
- Reference the founder's previous answer when pushing back.
- Do not give advice during the battle.
- Do not compliment the founder.
- Attack vague, generic, or unsubstantiated claims.
- Raise difficulty after strong answers.
- Stay in character at all times.
- Be firm but not abusive.
- Use plain, clear language unless the difficulty profile explicitly allows jargon.{jargon_note}
- Voice-style or casual answers that contain concrete numbers or validation still deserve credit — do not dismiss them for tone.
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

    # Difficulty-specific question instruction from config
    question_instruction = qs.get("instruction", "")

    return f"""You are {label}, a tough pitch opponent in PitchFight AI.
Difficulty profile: {profile_name}

Startup: {name}
Problem: {problem}
Solution: {solution}
Why AI: {why_ai}

{focus}

QUESTION STYLE ({profile_name}):
{question_instruction}

{rules}
"""
