"""Pure unit tests for SimulationService's internal logic: the phase
transition graph and small helper functions. No database of any kind."""

import pytest

from app.models.enums import SimulationPhase
from app.services.simulation_service import (
    SimulationService,
    _build_pitch_snapshot,
    _current_judge_config_version,
)

# ---------------------------------------------------------------------------
# Phase transition graph
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (SimulationPhase.PITCH_BATTLE, SimulationPhase.PITCH_SCORING),
        (SimulationPhase.PITCH_SCORING, SimulationPhase.RETRY),
        (SimulationPhase.PITCH_SCORING, SimulationPhase.DEAL),
        (SimulationPhase.PITCH_SCORING, SimulationPhase.COMPLETED),
        (SimulationPhase.RETRY, SimulationPhase.DEAL),
        (SimulationPhase.RETRY, SimulationPhase.COMPLETED),
        (SimulationPhase.DEAL, SimulationPhase.DEAL_SCORING),
        (SimulationPhase.DEAL_SCORING, SimulationPhase.COMPLETED),
    ],
)
def test_allowed_transitions_pass(current: SimulationPhase, target: SimulationPhase) -> None:
    SimulationService._ensure_transition_allowed(current, target)  # must not raise


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # Skipping ahead.
        (SimulationPhase.PITCH_BATTLE, SimulationPhase.DEAL),
        (SimulationPhase.PITCH_BATTLE, SimulationPhase.COMPLETED),
        (SimulationPhase.PITCH_BATTLE, SimulationPhase.DEAL_SCORING),
        # Backwards.
        (SimulationPhase.DEAL, SimulationPhase.RETRY),
        (SimulationPhase.DEAL_SCORING, SimulationPhase.DEAL),
        (SimulationPhase.PITCH_SCORING, SimulationPhase.PITCH_BATTLE),
        (SimulationPhase.COMPLETED, SimulationPhase.PITCH_BATTLE),
        # No-ops / self-loops are not modeled as valid transitions.
        (SimulationPhase.PITCH_BATTLE, SimulationPhase.PITCH_BATTLE),
    ],
)
def test_disallowed_transitions_raise(current: SimulationPhase, target: SimulationPhase) -> None:
    from app.services.simulation_service import InvalidSimulationTransitionError

    with pytest.raises(InvalidSimulationTransitionError):
        SimulationService._ensure_transition_allowed(current, target)


def test_completed_has_no_outgoing_transitions() -> None:
    from app.services.simulation_service import _ALLOWED_TRANSITIONS

    assert _ALLOWED_TRANSITIONS[SimulationPhase.COMPLETED] == frozenset()


# ---------------------------------------------------------------------------
# _build_pitch_snapshot
# ---------------------------------------------------------------------------


class _FakePitch:
    """Anything with the eight pitch attributes — doesn't need to be a real
    ORM Pitch instance to exercise this pure function."""

    startup_name = "PitchFight"
    problem = "Founders can't rehearse pressure."
    target_users = "First-time founders"
    solution = "AI judges."
    why_ai = "Adaptive tone."
    traction = "10 pilots"
    competitors = "Practicing with friends"
    ask = "Pre-seed"
    # Deliberately present but must NOT leak into the snapshot:
    id = "should-not-appear"
    user_id = "should-not-appear"
    created_at = "should-not-appear"


def test_build_pitch_snapshot_contains_exactly_the_eight_fields() -> None:
    snapshot = _build_pitch_snapshot(_FakePitch())
    assert set(snapshot.keys()) == {
        "startup_name",
        "problem",
        "target_users",
        "solution",
        "why_ai",
        "traction",
        "competitors",
        "ask",
    }
    assert snapshot["startup_name"] == "PitchFight"
    assert "id" not in snapshot
    assert "user_id" not in snapshot


def test_build_pitch_snapshot_preserves_none_for_optional_fields() -> None:
    class _MinimalPitch(_FakePitch):
        why_ai = None
        traction = None
        competitors = None
        ask = None

    snapshot = _build_pitch_snapshot(_MinimalPitch())
    assert snapshot["why_ai"] is None
    assert snapshot["traction"] is None


# ---------------------------------------------------------------------------
# _current_judge_config_version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "persona_type", ["skeptical_vc", "technical_judge", "hackathon_judge", "some_future_persona"]
)
def test_current_judge_config_version_convention(persona_type: str) -> None:
    assert _current_judge_config_version(persona_type) == f"{persona_type}-v1"


# ---------------------------------------------------------------------------
# _ensure_round_count_valid
# ---------------------------------------------------------------------------


def test_round_count_rejects_negative() -> None:
    with pytest.raises(ValueError):
        SimulationService._ensure_round_count_valid("battle_round_count", -1, 0)


def test_round_count_rejects_decrease() -> None:
    with pytest.raises(ValueError):
        SimulationService._ensure_round_count_valid("battle_round_count", 1, 2)


def test_round_count_allows_same_value() -> None:
    SimulationService._ensure_round_count_valid("battle_round_count", 2, 2)  # must not raise


def test_round_count_allows_increase() -> None:
    SimulationService._ensure_round_count_valid("battle_round_count", 3, 2)  # must not raise
