"""Difficulty profile loader for PitchFight AI.

Reads config/judge_settings.json and exposes typed accessors for:
  - question style (tone, jargon avoidance, max sentences)
  - scoring calibration (floors, ranges per profile)
  - battle phase tone
  - coaching style

Safe defaults are embedded here so the app works even if the JSON is missing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "judge_settings.json"
)

# ---------------------------------------------------------------------------
# Alias normalization map
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {
    # practice
    "practice": "practice",
    "easy": "practice",
    "beginner": "practice",
    "student": "practice",
    # judge
    "judge": "judge",
    "medium": "judge",
    "balanced": "judge",
    "hackathon": "judge",
    "high": "judge",       # legacy frontend sent "high"
    # investor
    "investor": "investor",
    "hard": "investor",
    "vc": "investor",
    "expert": "investor",
}

# ---------------------------------------------------------------------------
# Hardcoded safe defaults (used when config file is absent or invalid)
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS: dict[str, Any] = {
    "default_profile": "practice",
    "profiles": {
        "practice": {
            "label": "Practice Mode",
            "description": "Student-friendly pitch practice for first/second-time founders.",
            "profile_display": {
                "pressure_labels": {
                    "explore": "Warm-up",
                    "pressure": "Focused",
                    "close": "Final Practice",
                },
            },
            "question_style": {
                "plain_language": True,
                "avoid_jargon": True,
                "avoid_compound_questions": True,
                "one_question_only": True,
                "max_sentences": 3,
                "tone": "challenging_but_supportive",
                "instruction": (
                    "This founder is practicing for the first or second time. "
                    "Challenge them enough to help them improve, but do not destroy confidence. "
                    "Ask one clear focused question at a time. "
                    "Use plain language and avoid jargon-heavy VC terminology."
                ),
            },
            "coaching_style": {
                "tone": "encouraging_actionable",
                "instruction": (
                    "Be encouraging but honest. Explain what the founder did right, "
                    "then show exactly how to make the answer stronger with one specific number, "
                    "example, or proof point."
                ),
                "example": (
                    "Your answer touched on the right idea. "
                    "Here's how to make it more convincing with one specific number or example."
                ),
            },
            "battle_phase_tone": {
                "explore": "medium",
                "pressure": "medium_high_but_clear",
                "close": "firm_but_supportive",
            },
            "scoring_calibration": {
                "attempted_answer_floor": 35,
                "partial_signal_floor": 40,
                "concrete_signal_floor": 52,
                "non_answer_max": 20,
                "startup_context_max": 45,
                "vague_on_topic_range": [35, 45],
                "one_concrete_signal_range": [52, 62],
                "strong_answer_range": [71, 85],
                "excellent_answer_range": [86, 100],
            },
        },
        "judge": {
            "label": "Judge Mode",
            "description": "Balanced hackathon judge simulation.",
            "profile_display": {
                "pressure_labels": {
                    "explore": "Moderate",
                    "pressure": "High",
                    "close": "Panel Ready",
                },
            },
            "question_style": {
                "plain_language": True,
                "avoid_jargon": True,
                "avoid_compound_questions": True,
                "one_question_only": True,
                "max_sentences": 3,
                "tone": "realistic_hackathon_judge",
                "instruction": (
                    "Act like a realistic hackathon judge. Be sharp and specific, "
                    "but keep questions understandable. Ask one clear question at a time "
                    "and focus on demo strength, novelty, user pain, and feasibility."
                ),
            },
            "coaching_style": {
                "tone": "balanced_judge_feedback",
                "instruction": (
                    "Be direct and fair. Highlight what would convince a hackathon judge "
                    "and what still needs proof before demo time."
                ),
                "example": (
                    "This answer has a useful signal, but a judge still needs to see proof "
                    "in the demo. Make the claim measurable and show it quickly."
                ),
            },
            "battle_phase_tone": {
                "explore": "medium_high",
                "pressure": "high_but_fair",
                "close": "firm_judging_panel",
            },
            "scoring_calibration": {
                "attempted_answer_floor": 30,
                "partial_signal_floor": 38,
                "concrete_signal_floor": 48,
                "non_answer_max": 18,
                "startup_context_max": 40,
                "vague_on_topic_range": [30, 42],
                "one_concrete_signal_range": [48, 60],
                "strong_answer_range": [70, 85],
                "excellent_answer_range": [86, 100],
            },
        },
        "investor": {
            "label": "Investor Mode",
            "description": "Harder skeptical VC-style pressure.",
            "profile_display": {
                "pressure_labels": {
                    "explore": "High",
                    "pressure": "Very High",
                    "close": "Investor Pressure",
                },
            },
            "question_style": {
                "plain_language": False,
                "avoid_jargon": False,
                "avoid_compound_questions": False,
                "one_question_only": True,
                "max_sentences": 4,
                "tone": "skeptical_investor",
                "instruction": (
                    "Act like a skeptical early-stage investor. Pressure-test market size, "
                    "moat, retention, revenue logic, distribution, and why now. "
                    "Be tougher than Practice Mode, but still focus on one main pressure point per round."
                ),
            },
            "coaching_style": {
                "tone": "sharp_investor_feedback",
                "instruction": (
                    "Be sharper and more business-focused. Explain what would worry an investor "
                    "and what proof is needed to reduce that concern."
                ),
                "example": (
                    "This answer lacks defensibility. A real investor needs to hear your moat mechanism, "
                    "not just what the product does."
                ),
            },
            "battle_phase_tone": {
                "explore": "high",
                "pressure": "very_high",
                "close": "investment_committee",
            },
            "scoring_calibration": {
                "attempted_answer_floor": 25,
                "partial_signal_floor": 35,
                "concrete_signal_floor": 45,
                "non_answer_max": 15,
                "startup_context_max": 35,
                "vague_on_topic_range": [25, 38],
                "one_concrete_signal_range": [45, 58],
                "strong_answer_range": [70, 85],
                "excellent_answer_range": [86, 100],
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Module-level singleton (loaded once)
# ---------------------------------------------------------------------------

_settings: dict[str, Any] | None = None


def load_judge_settings() -> dict[str, Any]:
    """Load and cache judge_settings.json. Falls back to hardcoded defaults."""
    global _settings
    if _settings is not None:
        return _settings

    path = os.path.abspath(_CONFIG_PATH)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "profiles" not in data:
            raise ValueError("Missing 'profiles' key")
        _settings = data
        logger.info("judge_settings: loaded from %s", path)
    except FileNotFoundError:
        logger.warning("judge_settings: config not found at %s — using defaults", path)
        _settings = _DEFAULT_SETTINGS
    except Exception as exc:
        logger.warning("judge_settings: failed to load (%s) — using defaults", exc)
        _settings = _DEFAULT_SETTINGS

    return _settings


def get_default_profile() -> str:
    s = load_judge_settings()
    return s.get("default_profile", "practice")


def normalize_difficulty(value: str | None) -> str:
    """Map any incoming difficulty string to a canonical profile name.

    Supports legacy frontend values like "high" → "judge" and aliases like
    "beginner" → "practice". Unknown values fall back to the default profile.
    """
    if not value:
        return get_default_profile()
    key = str(value).strip().lower()
    normalized = _ALIAS_MAP.get(key)
    if normalized:
        return normalized
    # If the value is already a valid profile name, accept it
    s = load_judge_settings()
    if key in s.get("profiles", {}):
        return key
    logger.warning("judge_settings: unknown difficulty %r — using default", value)
    return get_default_profile()


def get_profile(profile_name: str | None) -> dict[str, Any]:
    """Return the full profile dict for the given (or default) profile."""
    s = load_judge_settings()
    name = normalize_difficulty(profile_name)
    profiles = s.get("profiles", {})
    profile = profiles.get(name)
    if not profile:
        logger.warning("judge_settings: profile %r not found — falling back to practice", name)
        profile = profiles.get("practice") or list(profiles.values())[0]
    return profile


def get_question_style(profile_name: str | None) -> dict[str, Any]:
    return get_profile(profile_name).get("question_style", {})


def get_scoring_calibration(profile_name: str | None) -> dict[str, Any]:
    return get_profile(profile_name).get("scoring_calibration", {})


def get_battle_phase_tone(profile_name: str | None, battle_phase: str) -> str:
    tones = get_profile(profile_name).get("battle_phase_tone", {})
    return tones.get(battle_phase, "medium")


def get_coaching_style(profile_name: str | None) -> dict[str, Any]:
    return get_profile(profile_name).get("coaching_style", {})


def get_label(profile_name: str | None) -> str:
    return get_profile(profile_name).get("label", "Practice Mode")


_PRESSURE_FALLBACKS: dict[str, dict[str, str]] = {
    "practice": {"explore": "Warm-up", "pressure": "Focused", "close": "Final Practice"},
    "judge":    {"explore": "Moderate", "pressure": "High", "close": "Panel Ready"},
    "investor": {"explore": "High", "pressure": "Very High", "close": "Investor Pressure"},
}


def get_pressure_display_label(profile_name: str | None, battle_phase: str) -> str:
    """Return a human-readable pressure label for the sidebar.

    Never returns "Extreme" for Practice Mode.
    Falls back to hardcoded defaults if config is missing.
    """
    profile = get_profile(profile_name)
    display = profile.get("profile_display", {})
    labels = display.get("pressure_labels", {})
    phase_key = battle_phase if battle_phase in ("explore", "pressure", "close") else "explore"
    if labels and phase_key in labels:
        return labels[phase_key]
    canonical = normalize_difficulty(profile_name)
    return _PRESSURE_FALLBACKS.get(canonical, _PRESSURE_FALLBACKS["practice"]).get(
        phase_key, "Warm-up"
    )
