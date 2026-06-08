"""Placeholder feedback generators for Phase 1 mock responses."""

from __future__ import annotations


def generate_improved_answer(weak_answer: str, startup: dict) -> str:
    """Return a stronger mock rewrite for a weak founder answer."""
    name = startup.get("name", "the product")
    return (
        f"Instead of staying vague, anchor your answer in specifics: "
        f"'{name}' solves a concrete discovery problem for students by ranking events against "
        f"skills, deadlines, and location — not just aggregating listings. "
        f"We already tested ranking logic on scraped campus events and saw students shortlist "
        f"3x faster than browsing WhatsApp groups.' "
        f"(Your original answer was too thin: \"{weak_answer[:120]}...\")"
        if len(weak_answer) > 120
        else (
            f"Lead with proof: '{name}' matches events to student profiles using skills, goals, "
            f"and urgency — we validated this with a prototype on real campus event data. "
            f"Your answer needed more specificity than: \"{weak_answer}\""
        )
    )


def generate_improved_pitch(startup: dict) -> str:
    """Return a mock 60-second pitch rewrite."""
    name = startup.get("name", "Our startup")
    problem = startup.get("problem", "a real student pain point")
    solution = startup.get("solution", "a focused product")
    why_ai = startup.get("why_ai", "intelligent matching")
    traction = startup.get("traction", "early prototype traction")
    ask = startup.get("ask", "feedback and support")

    return (
        f"{name} helps student founders stop missing the events that actually matter. "
        f"The problem is simple: {problem} "
        f"Our solution: {solution} "
        f"AI is load-bearing because {why_ai} "
        f"Traction so far: {traction} "
        f"We're asking for {ask}."
    )
