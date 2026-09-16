"""Attack tag taxonomy and round-based tag selection."""

from __future__ import annotations

ATTACK_TAGS: dict[str, list[str]] = {
    "skeptical_vc": [
        "Market Size",
        "Moat",
        "Retention",
        "Revenue Logic",
        "First 100 Users",
        "Why Now",
        "Competition",
        "Defensibility",
    ],
    "technical_judge": [
        "AI Justification",
        "Architecture",
        "Scalability",
        "Latency",
        "Data Quality",
        "Failure Mode",
        "Simpler Alternative",
        "Technical Feasibility",
    ],
    "hackathon_judge": [
        "Novelty",
        "Demo Clarity",
        "MVP Strength",
        "User Pain",
        "AI Load-Bearing",
        "Backyard Fit",
        "Practical Impact",
        "Judging Memorability",
    ],
}


# "Minimum viable answer" recipes — what a student should try to include for each
# question type. A recipe, not a script: short, plain, one or two concrete things.
ANSWER_CHECKLISTS: dict[str, str] = {
    # skeptical_vc
    "Market Size": "Try to include: who exactly + roughly how many of them.",
    "Moat": "Name one thing only you do — and why it's hard to copy.",
    "Retention": "Give one number: how many came back, or how often.",
    "Revenue Logic": "Say who pays + one price or amount.",
    "First 100 Users": "Name where your first users came from.",
    "Why Now": "One reason this works today and not 2 years ago.",
    "Competition": "Name one competitor + one thing you do differently.",
    "Defensibility": "One thing that gets stronger as you grow.",
    # technical_judge
    "AI Justification": "Say what breaks if you remove the AI.",
    "Architecture": "Walk through the main steps, in order.",
    "Scalability": "One number: users or load you can handle.",
    "Latency": "Roughly how fast does it respond?",
    "Data Quality": "Where your data comes from + how much.",
    "Failure Mode": "What happens when the model is wrong.",
    "Simpler Alternative": "Why a simpler tool wouldn't be enough.",
    "Technical Feasibility": "One thing you've already built and tested.",
    # hackathon_judge
    "Novelty": "Name one thing that's actually new here.",
    "Demo Clarity": "Walk through your demo in 3 steps.",
    "MVP Strength": "What works right now (not someday).",
    "User Pain": "Who hurts + one proof they care.",
    "AI Load-Bearing": "Say what the AI does that nothing else could.",
    "Backyard Fit": "Why this fits a small/scrappy build.",
    "Practical Impact": "One real result or test you ran.",
    "Judging Memorability": "The one line you want remembered.",
}

_DEFAULT_CHECKLIST = "Try to include: one number, one user, or one real result."


def get_answer_checklist(attack_tag: str) -> str:
    """Return a one-line 'minimum viable answer' recipe for a question type."""
    return ANSWER_CHECKLISTS.get(attack_tag, _DEFAULT_CHECKLIST)


def get_attack_tags(persona: str) -> list[str]:
    """Return attack tags for a persona."""
    return list(ATTACK_TAGS.get(persona, ATTACK_TAGS["technical_judge"]))


def get_next_attack_tag(persona: str, round_number: int) -> str:
    """Pick the next attack tag based on persona and round (1-indexed)."""
    tags = get_attack_tags(persona)
    if not tags:
        return "General Pressure"
    index = max(0, round_number - 1) % len(tags)
    return tags[index]
