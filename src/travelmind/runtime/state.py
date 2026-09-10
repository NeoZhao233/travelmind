from typing import Literal, TypedDict

from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    GroundingIssue,
    ToolObservation,
)
from travelmind.schemas import ConstraintViolation, Evidence, Itinerary, TravelRequest


class TravelRuntimeState(TypedDict, total=False):
    request: TravelRequest
    evidence: list[Evidence]
    current_plan: ExecutionPlan
    plan_history: list[ExecutionPlan]
    observations: list[ToolObservation]
    current_failure: FailureAttribution | None
    failure_history: list[FailureAttribution]
    grounding_issues: list[GroundingIssue]
    violations: list[ConstraintViolation]
    itinerary: Itinerary | None
    replan_count: int
    tool_call_count: int
    trajectory: list[dict[str, object]]
    status: Literal[
        "initialized",
        "planning",
        "executing",
        "generating",
        "validating",
        "completed",
        "failed",
    ]
    failure_reason: str | None
