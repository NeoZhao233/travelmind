from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from travelmind.planner.candidates import PlaceCandidate
from travelmind.schemas import (
    ConstraintViolation,
    Itinerary,
    PlanningValidationContext,
    TravelConstraints,
)


class RepairRequest(BaseModel):
    itinerary: Itinerary
    constraints: TravelConstraints
    context: PlanningValidationContext
    candidates: list[PlaceCandidate] = Field(default_factory=list)
    violations: list[ConstraintViolation]


class RepairOutcome(BaseModel):
    itinerary: Itinerary
    modified_days: list[int] = Field(default_factory=list)
    action: Literal["recomputed_total", "removed_activity", "replanned_day", "unchanged"]
    reason_codes: list[str] = Field(default_factory=list)


class RepairTrajectoryEvent(BaseModel):
    node: str
    attempt: int = Field(ge=0)
    outcome: str
    violation_codes: list[str] = Field(default_factory=list)
    modified_days: list[int] = Field(default_factory=list)
    error_type: str | None = None
