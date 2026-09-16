"""Sample startup data for demos and testing."""

EVENTRADAR_SAMPLE = {
    "name": "EventRadar AI",
    "problem": (
        "Students miss hackathons, tech events, and startup opportunities because "
        "discovery is scattered across WhatsApp groups, LinkedIn, Luma, college clubs, "
        "and random websites."
    ),
    "target_users": "College students, student founders, and early-stage builders.",
    "solution": (
        "AI-powered event discovery that ranks opportunities based on skills, goals, "
        "location, and deadline urgency."
    ),
    "why_ai": (
        "The app does not just list events. It matches events to a student's profile "
        "and explains why each event is worth attending."
    ),
    "competitors": "Luma, LinkedIn Events, WhatsApp groups, college club pages.",
    "traction": "Prototype built with scraped event data and ranking logic.",
    "ask": "Hackathon prize and mentor feedback.",
}


def get_sample_startup() -> dict:
    """Return the EventRadar AI sample startup."""
    return dict(EVENTRADAR_SAMPLE)
