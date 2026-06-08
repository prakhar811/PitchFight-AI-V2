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
