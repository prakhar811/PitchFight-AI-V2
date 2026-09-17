"""Shared nested Pydantic models used inside JSONB fields."""

from pydantic import BaseModel


class CriterionResult(BaseModel):
    """One rubric criterion's result within a Scorecard's `dimensions` JSONB.

    Criterion names are persona/rubric-specific and therefore not modeled
    as fixed fields — `dimensions` on ScorecardRead stays a
    `dict[str, CriterionResult]` so any criterion key is accepted.
    """

    score: float
    weight: float
    reason: str
    evidence: list[str] = []
