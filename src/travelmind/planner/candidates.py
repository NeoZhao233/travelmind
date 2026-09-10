from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from travelmind.planner.constraints import validate_itinerary
from travelmind.schemas import (
    Activity,
    ConstraintViolation,
    DayPlan,
    Itinerary,
    PlaceAvailability,
    PlanningValidationContext,
    TravelConstraints,
    TravelTimeEstimate,
)


class PlaceCandidate(BaseModel):
    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    duration_minutes: int = Field(ge=15, le=720)
    estimated_cost: float = Field(ge=0)
    relevance_score: float = Field(default=0, ge=0, le=1)
    interest_tags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    booking_status: Literal["not_required", "confirmed", "unconfirmed", "unknown"] = "unknown"


class PlanningDayWindow(BaseModel):
    day: int = Field(ge=1)
    available_from: datetime
    available_until: datetime
    origin_place_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_window(self) -> PlanningDayWindow:
        if self.available_from.utcoffset() is None or self.available_until.utcoffset() is None:
            raise ValueError("planning day timestamps must be timezone-aware")
        if self.available_until <= self.available_from:
            raise ValueError("available_until must be later than available_from")
        return self


class CandidatePlanningProblem(BaseModel):
    constraints: TravelConstraints
    day_windows: list[PlanningDayWindow] = Field(min_length=1)
    candidates: list[PlaceCandidate] = Field(min_length=1)
    availability: list[PlaceAvailability]
    travel_times: list[TravelTimeEstimate]
    non_activity_cost: float = Field(default=0, ge=0)
    minimum_transfer_buffer_minutes: int = Field(default=15, ge=0, le=180)

    @model_validator(mode="after")
    def validate_problem(self) -> CandidatePlanningProblem:
        candidate_ids = [item.place_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate place_id values must be unique")
        day_numbers = [item.day for item in self.day_windows]
        if day_numbers != list(range(1, len(day_numbers) + 1)):
            raise ValueError("day_windows must be sequential and ordered")
        if self.constraints.days is not None and len(day_numbers) != self.constraints.days:
            raise ValueError("day_windows count must equal constraints.days")
        PlanningValidationContext(
            availability=self.availability,
            travel_times=self.travel_times,
            minimum_transfer_buffer_minutes=self.minimum_transfer_buffer_minutes,
        )
        return self


class PlanningDecision(BaseModel):
    place_id: str
    action: Literal["selected", "skipped"]
    reason_code: str
    day: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    utility_score: float | None = None
    score_components: dict[str, float] = Field(default_factory=dict)


class CandidatePlanningResult(BaseModel):
    itinerary: Itinerary
    decisions: list[PlanningDecision]
    violations: list[ConstraintViolation]
    unscheduled_required_places: list[str]
    algorithm: str = "explainable-greedy-v1"


class _FeasiblePlacement(BaseModel):
    start_at: datetime
    end_at: datetime
    inbound_minutes: int
    utility_score: float
    score_components: dict[str, float]


class ExplainableGreedyPlanner:
    """Deterministic candidate scheduler and fallback baseline, not a global optimizer."""

    _PACE_LIMITS = {"relaxed": 2, "balanced": 3, "intensive": 4}

    def generate(self, problem: CandidatePlanningProblem) -> CandidatePlanningResult:
        availability = {(item.place_id, item.service_date): item for item in problem.availability}
        travel_times = {
            (item.origin_place_id, item.destination_place_id, item.service_date): item
            for item in problem.travel_times
        }
        required = set(problem.constraints.required_places)
        excluded = set(problem.constraints.excluded_places)
        remaining = {
            item.place_id: item
            for item in problem.candidates
            if item.place_id not in excluded and item.name not in excluded
        }
        decisions = [
            PlanningDecision(
                place_id=item.place_id,
                action="skipped",
                reason_code="excluded_by_request",
            )
            for item in problem.candidates
            if item.place_id in excluded or item.name in excluded
        ]
        selected_ids: set[str] = set()
        total_cost = problem.non_activity_cost
        days: list[DayPlan] = []
        last_reasons: dict[str, str] = {}

        for day_window in problem.day_windows:
            activities: list[Activity] = []
            cursor = day_window.available_from
            previous_place_id = day_window.origin_place_id
            capacity = self._PACE_LIMITS[problem.constraints.pace]
            while remaining and len(activities) < capacity:
                feasible: list[tuple[float, str, _FeasiblePlacement]] = []
                for candidate in remaining.values():
                    placement, reason = self._place_candidate(
                        candidate=candidate,
                        day_window=day_window,
                        cursor=cursor,
                        previous_place_id=previous_place_id,
                        current_total_cost=total_cost,
                        constraints=problem.constraints,
                        availability=availability,
                        travel_times=travel_times,
                        buffer_minutes=problem.minimum_transfer_buffer_minutes,
                    )
                    if placement is None:
                        last_reasons[candidate.place_id] = reason
                        continue
                    is_required = candidate.place_id in required or candidate.name in required
                    required_bonus = 1000.0 if is_required else 0.0
                    placement.utility_score += required_bonus
                    placement.score_components["required_bonus"] = required_bonus
                    feasible.append((placement.utility_score, candidate.place_id, placement))
                if not feasible:
                    break
                _, selected_id, placement = min(feasible, key=lambda item: (-item[0], item[1]))
                candidate = remaining.pop(selected_id)
                activity = Activity(
                    place_id=candidate.place_id,
                    name=candidate.name,
                    start_at=placement.start_at,
                    end_at=placement.end_at,
                    estimated_cost=candidate.estimated_cost,
                    evidence_ids=candidate.evidence_ids,
                    booking_status=candidate.booking_status,
                )
                activities.append(activity)
                selected_ids.add(candidate.place_id)
                total_cost += candidate.estimated_cost
                cursor = activity.end_at
                previous_place_id = activity.place_id
                decisions.append(
                    PlanningDecision(
                        place_id=candidate.place_id,
                        action="selected",
                        reason_code=(
                            "selected_required"
                            if placement.score_components["required_bonus"]
                            else "selected_highest_utility"
                        ),
                        day=day_window.day,
                        start_at=activity.start_at,
                        end_at=activity.end_at,
                        utility_score=round(placement.utility_score, 4),
                        score_components=placement.score_components,
                    )
                )
            days.append(
                DayPlan(
                    day=day_window.day,
                    activities=activities,
                    available_from=day_window.available_from,
                    available_until=day_window.available_until,
                    origin_place_id=day_window.origin_place_id,
                )
            )

        for candidate in remaining.values():
            decisions.append(
                PlanningDecision(
                    place_id=candidate.place_id,
                    action="skipped",
                    reason_code=last_reasons.get(candidate.place_id, "pace_capacity_exhausted"),
                )
            )

        itinerary = Itinerary(
            days=days,
            estimated_total_cost=total_cost,
            non_activity_cost=problem.non_activity_cost,
            assumptions=[
                "Deterministic greedy baseline; scores are heuristics, not a global optimum."
            ],
        )
        context = PlanningValidationContext(
            availability=problem.availability,
            travel_times=problem.travel_times,
            minimum_transfer_buffer_minutes=problem.minimum_transfer_buffer_minutes,
        )
        violations = validate_itinerary(itinerary, problem.constraints, context)
        scheduled_identifiers = selected_ids | {
            item.name for item in problem.candidates if item.place_id in selected_ids
        }
        unscheduled_required = sorted(required - scheduled_identifiers)
        return CandidatePlanningResult(
            itinerary=itinerary,
            decisions=decisions,
            violations=violations,
            unscheduled_required_places=unscheduled_required,
        )

    def _place_candidate(
        self,
        *,
        candidate: PlaceCandidate,
        day_window: PlanningDayWindow,
        cursor: datetime,
        previous_place_id: str,
        current_total_cost: float,
        constraints: TravelConstraints,
        availability: dict[tuple[str, date], PlaceAvailability],
        travel_times: dict[tuple[str, str, date], TravelTimeEstimate],
        buffer_minutes: int,
    ) -> tuple[_FeasiblePlacement | None, str]:
        projected_cost = current_total_cost + candidate.estimated_cost
        if constraints.budget is not None and projected_cost > constraints.budget:
            return None, "budget_exceeded"
        operational = availability.get((candidate.place_id, day_window.available_from.date()))
        if operational is None:
            return None, "availability_missing"
        if operational.status != "open" or not operational.evidence_ids:
            return None, f"availability_{operational.status}"
        if operational.valid_until is not None and cursor > operational.valid_until:
            return None, "availability_stale"
        if operational.booking_required and candidate.booking_status != "confirmed":
            return None, "booking_unconfirmed"
        inbound = self._travel_minutes(
            previous_place_id,
            candidate.place_id,
            cursor,
            travel_times,
        )
        if inbound is None:
            return None, "inbound_travel_unavailable"
        earliest = cursor + timedelta(minutes=inbound + buffer_minutes)
        duration = timedelta(minutes=candidate.duration_minutes)
        possible_slots = [
            (max(earliest, window.opens_at), window.closes_at) for window in operational.windows
        ]
        fitting = [
            (start, closes_at)
            for start, closes_at in possible_slots
            if start + duration <= closes_at
        ]
        if not fitting:
            return None, "outside_opening_hours"
        start_at, _ = min(fitting, key=lambda item: item[0])
        end_at = start_at + duration
        if operational.valid_until is not None and start_at > operational.valid_until:
            return None, "availability_stale"
        outbound = self._travel_minutes(
            candidate.place_id,
            day_window.origin_place_id,
            end_at,
            travel_times,
        )
        if outbound is None:
            return None, "return_travel_unavailable"
        if end_at + timedelta(minutes=outbound + buffer_minutes) > day_window.available_until:
            return None, "cannot_return_within_day_window"

        interest_matches = len(set(candidate.interest_tags) & set(constraints.interests))
        components = {
            "relevance": candidate.relevance_score * 100,
            "interest_match": interest_matches * 20.0,
            "inbound_travel_penalty": -inbound * 0.2,
            "cost_penalty": -candidate.estimated_cost * 0.02,
        }
        return (
            _FeasiblePlacement(
                start_at=start_at,
                end_at=end_at,
                inbound_minutes=inbound,
                utility_score=sum(components.values()),
                score_components=components,
            ),
            "feasible",
        )

    @staticmethod
    def _travel_minutes(
        origin: str,
        destination: str,
        departure_at: datetime,
        travel_times: dict[tuple[str, str, date], TravelTimeEstimate],
    ) -> int | None:
        if origin == destination:
            return 0
        estimate = travel_times.get((origin, destination, departure_at.date()))
        if (
            estimate is None
            or estimate.status != "known"
            or estimate.duration_minutes is None
            or not estimate.evidence_ids
            or (estimate.valid_until is not None and departure_at > estimate.valid_until)
        ):
            return None
        return estimate.duration_minutes
