from typing import Literal, TypedDict

from travelmind.planner.candidates import PlaceCandidate
from travelmind.repair.models import RepairTrajectoryEvent
from travelmind.schemas import (
    ConstraintViolation,
    Itinerary,
    PlanningValidationContext,
    TravelConstraints,
)


class RepairState(TypedDict, total=False):
    itinerary: Itinerary
    constraints: TravelConstraints
    context: PlanningValidationContext
    candidates: list[PlaceCandidate]
    violations: list[ConstraintViolation]
    repair_attempts: int
    modified_days: list[int]
    trajectory: list[RepairTrajectoryEvent]
    degraded_components: list[str]
    dependency_errors: list[dict[str, str]]
    status: Literal["initialized", "validating", "repairing", "completed", "failed"]
    failure_reason: str | None
