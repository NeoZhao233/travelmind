from __future__ import annotations

from math import ceil

from travelmind.planner.candidates import (
    CandidatePlanningProblem,
    ExplainableGreedyPlanner,
    PlaceCandidate,
    PlanningDayWindow,
)
from travelmind.repair.models import RepairOutcome, RepairRequest
from travelmind.schemas import Activity, Itinerary, TravelConstraints

_LOCAL_DAY_CODES = {
    "TIME_CONFLICT",
    "ACTIVITY_EVIDENCE_MISSING",
    "AVAILABILITY_MISSING",
    "AVAILABILITY_UNKNOWN",
    "AVAILABILITY_STALE",
    "PLACE_CLOSED",
    "OUTSIDE_OPENING_HOURS",
    "BOOKING_UNCONFIRMED",
    "DAY_WINDOW_VIOLATION",
    "TRAVEL_TIME_MISSING",
    "TRAVEL_TIME_UNKNOWN",
    "TRAVEL_TIME_STALE",
    "TRAVEL_TIME_INFEASIBLE",
}


class DeterministicDayRepairer:
    """Repair totals, individual removals, or affected days without touching safe days."""

    def __init__(self, planner: ExplainableGreedyPlanner | None = None) -> None:
        self._planner = planner or ExplainableGreedyPlanner()

    def repair(self, request: RepairRequest) -> RepairOutcome:
        itinerary = request.itinerary.model_copy(deep=True)
        modified_days: set[int] = set()
        reasons: list[str] = []
        violation_codes = {item.code for item in request.violations}

        if "EXCLUDED_PLACE_PRESENT" in violation_codes:
            excluded = set(request.constraints.excluded_places)
            for day in itinerary.days:
                kept = [
                    item
                    for item in day.activities
                    if item.place_id not in excluded and item.name not in excluded
                ]
                if len(kept) != len(day.activities):
                    day.activities = kept
                    modified_days.add(day.day)
            reasons.append("removed_excluded_activity")

        if "BUDGET_EXCEEDED" in violation_codes and request.constraints.budget is not None:
            required = set(request.constraints.required_places)
            removable = sorted(
                (
                    (activity.estimated_cost, day.day, activity.place_id)
                    for day in itinerary.days
                    for activity in day.activities
                    if activity.place_id not in required and activity.name not in required
                ),
                key=lambda item: (-item[0], item[1], item[2]),
            )
            for _, day_number, place_id in removable:
                if self._computed_total(itinerary) <= request.constraints.budget:
                    break
                day = next(item for item in itinerary.days if item.day == day_number)
                day.activities = [item for item in day.activities if item.place_id != place_id]
                modified_days.add(day_number)
                reasons.append("removed_optional_for_budget")

        affected_days = {
            item.day
            for item in request.violations
            if item.code in _LOCAL_DAY_CODES and item.day is not None
        }
        if "REQUIRED_PLACE_MISSING" in violation_codes and itinerary.days:
            affected_days.add(itinerary.days[-1].day)

        candidate_by_id = {item.place_id: item for item in request.candidates}
        for day in itinerary.days:
            for activity in day.activities:
                candidate_by_id.setdefault(
                    activity.place_id, self._candidate_from_activity(activity)
                )

        for day_number in sorted(affected_days):
            day = next((item for item in itinerary.days if item.day == day_number), None)
            if day is None or any(
                value is None
                for value in (
                    day.available_from,
                    day.available_until,
                    day.origin_place_id,
                )
            ):
                reasons.append("day_window_missing")
                continue
            used_elsewhere = {
                activity.place_id
                for other_day in itinerary.days
                if other_day.day != day_number
                for activity in other_day.activities
            }
            local_candidates = [
                item for item in candidate_by_id.values() if item.place_id not in used_elsewhere
            ]
            if not local_candidates:
                reasons.append("candidate_pool_empty")
                continue
            other_cost = itinerary.non_activity_cost + sum(
                activity.estimated_cost
                for other_day in itinerary.days
                if other_day.day != day_number
                for activity in other_day.activities
            )
            local_budget = (
                None
                if request.constraints.budget is None
                else max(0.0, request.constraints.budget - other_cost)
            )
            present_elsewhere = {
                identifier
                for other_day in itinerary.days
                if other_day.day != day_number
                for activity in other_day.activities
                for identifier in (activity.place_id, activity.name)
            }
            required_here = [
                place
                for place in request.constraints.required_places
                if place not in present_elsewhere
            ]
            local_constraints = TravelConstraints(
                destination=request.constraints.destination,
                days=1,
                budget=local_budget,
                pace=request.constraints.pace,
                interests=request.constraints.interests,
                required_places=required_here,
                excluded_places=request.constraints.excluded_places,
            )
            assert day.available_from is not None
            assert day.available_until is not None
            assert day.origin_place_id is not None
            result = self._planner.generate(
                CandidatePlanningProblem(
                    constraints=local_constraints,
                    day_windows=[
                        PlanningDayWindow(
                            day=1,
                            available_from=day.available_from,
                            available_until=day.available_until,
                            origin_place_id=day.origin_place_id,
                        )
                    ],
                    candidates=local_candidates,
                    availability=request.context.availability,
                    travel_times=request.context.travel_times,
                    minimum_transfer_buffer_minutes=(
                        request.context.minimum_transfer_buffer_minutes
                    ),
                )
            )
            repaired_day = result.itinerary.days[0].model_copy(
                update={"day": day_number}, deep=True
            )
            changed = repaired_day.model_dump(mode="json") != day.model_dump(mode="json")
            itinerary.days = [
                repaired_day if item.day == day_number else item for item in itinerary.days
            ]
            if changed:
                modified_days.add(day_number)
                reasons.append("replanned_affected_day")
            else:
                reasons.append("replan_produced_no_change")

        itinerary.estimated_total_cost = self._computed_total(itinerary)
        if modified_days:
            action = "replanned_day" if affected_days else "removed_activity"
        elif "COST_TOTAL_MISMATCH" in violation_codes:
            action = "recomputed_total"
            reasons.append("recomputed_claimed_total")
        else:
            action = "unchanged"
            reasons.append("no_safe_local_repair")
        return RepairOutcome(
            itinerary=itinerary,
            modified_days=sorted(modified_days),
            action=action,
            reason_codes=list(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _candidate_from_activity(activity: Activity) -> PlaceCandidate:
        duration = ceil((activity.end_at - activity.start_at).total_seconds() / 60)
        return PlaceCandidate(
            place_id=activity.place_id,
            name=activity.name,
            duration_minutes=duration,
            estimated_cost=activity.estimated_cost,
            evidence_ids=activity.evidence_ids,
            booking_status=activity.booking_status,
        )

    @staticmethod
    def _computed_total(itinerary: Itinerary) -> float:
        return itinerary.non_activity_cost + sum(
            activity.estimated_cost for day in itinerary.days for activity in day.activities
        )
