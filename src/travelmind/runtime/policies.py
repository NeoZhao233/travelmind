from __future__ import annotations

from travelmind.runtime.models import (
    ExecutionPlan,
    FailureAttribution,
    RuntimeStep,
    StepKind,
    ToolObservation,
)
from travelmind.schemas import TravelRequest


class DeterministicMultiStepRuntimePlanner:
    """Interview baseline that visibly replaces downstream work after a failed action."""

    def __init__(
        self,
        *,
        origin_place_id: str,
        primary_place_id: str,
        fallback_place_id: str,
    ) -> None:
        self.origin_place_id = origin_place_id
        self.primary_place_id = primary_place_id
        self.fallback_place_id = fallback_place_id

    def plan(
        self,
        request: TravelRequest,
        *,
        observations: list[ToolObservation],
        previous_plan: ExecutionPlan | None,
        failure: FailureAttribution | None,
    ) -> ExecutionPlan:
        revision = 1 if previous_plan is None else previous_plan.revision + 1
        if previous_plan is None:
            return self._initial_plan(request)

        successful_retrieval = any(
            item.tool_name == "candidate_search" and item.outcome == "success"
            for item in observations
        )
        reason = (
            f"Reuse candidate observation and replace downstream path after {failure.reason_code}."
            if failure and successful_retrieval
            else "Replace the failed downstream path with the configured safe alternative."
        )
        return ExecutionPlan(
            plan_id=previous_plan.plan_id,
            revision=revision,
            goal=previous_plan.goal,
            reason=reason,
            steps=self._place_checks(self.fallback_place_id, suffix="fallback"),
        )

    def _initial_plan(self, request: TravelRequest) -> ExecutionPlan:
        search_id = "search_candidates"
        availability_id = "primary_availability"
        booking_id = "primary_booking"
        travel_id = "primary_travel_time"
        return ExecutionPlan(
            plan_id="multi-step-beijing-day-trip",
            revision=1,
            goal=request.query,
            reason="Search, verify availability and booking, then validate travel feasibility.",
            steps=[
                RuntimeStep(
                    step_id=search_id,
                    kind=StepKind.RETRIEVE,
                    tool_name="candidate_search",
                    arguments={"query": request.query},
                ),
                RuntimeStep(
                    step_id=availability_id,
                    kind=StepKind.CHECK_AVAILABILITY,
                    tool_name="availability",
                    arguments={"place_id": self.primary_place_id},
                    depends_on=[search_id],
                ),
                RuntimeStep(
                    step_id=booking_id,
                    kind=StepKind.CHECK_BOOKING,
                    tool_name="booking",
                    arguments={"place_id": self.primary_place_id},
                    depends_on=[availability_id],
                ),
                RuntimeStep(
                    step_id=travel_id,
                    kind=StepKind.ESTIMATE_TRAVEL_TIME,
                    tool_name="travel_time",
                    arguments={
                        "origin_place_id": self.origin_place_id,
                        "destination_place_id": self.primary_place_id,
                    },
                    depends_on=[booking_id],
                ),
            ],
        )

    def _place_checks(self, place_id: str, *, suffix: str) -> list[RuntimeStep]:
        availability_id = f"{suffix}_availability"
        travel_id = f"{suffix}_travel_time"
        return [
            RuntimeStep(
                step_id=availability_id,
                kind=StepKind.CHECK_AVAILABILITY,
                tool_name="availability",
                arguments={"place_id": place_id},
            ),
            RuntimeStep(
                step_id=travel_id,
                kind=StepKind.ESTIMATE_TRAVEL_TIME,
                tool_name="travel_time",
                arguments={
                    "origin_place_id": self.origin_place_id,
                    "destination_place_id": place_id,
                },
                depends_on=[availability_id],
            ),
        ]
