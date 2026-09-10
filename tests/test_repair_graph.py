from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from travelmind.planner.candidates import PlaceCandidate
from travelmind.repair import build_itinerary_repair_graph
from travelmind.schemas import (
    Activity,
    DayPlan,
    Itinerary,
    OperatingWindow,
    PlaceAvailability,
    PlanningValidationContext,
    TravelConstraints,
    TravelTimeEstimate,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def activity(place_id: str, day: int, cost: float = 10) -> Activity:
    start = BASE + timedelta(days=day - 1, hours=9)
    return Activity(
        place_id=place_id,
        name=place_id,
        start_at=start,
        end_at=start + timedelta(hours=1),
        estimated_cost=cost,
        evidence_ids=[f"doc-{place_id}"],
        booking_status="not_required",
    )


def day_plan(day: int, activities: list[Activity]) -> DayPlan:
    start = BASE + timedelta(days=day - 1, hours=8)
    return DayPlan(
        day=day,
        activities=activities,
        available_from=start,
        available_until=start + timedelta(hours=10),
        origin_place_id="hotel",
    )


def availability(place_id: str, service_date: date, status: str = "open") -> PlaceAvailability:
    start = datetime.combine(service_date, datetime.min.time(), tzinfo=UTC)
    return PlaceAvailability(
        place_id=place_id,
        service_date=service_date,
        status=status,
        windows=(
            [
                OperatingWindow(
                    opens_at=start + timedelta(hours=8),
                    closes_at=start + timedelta(hours=18),
                )
            ]
            if status == "open"
            else []
        ),
        evidence_ids=[f"hours-{place_id}-{service_date}"],
    )


def travel(origin: str, destination: str, service_date: date) -> TravelTimeEstimate:
    return TravelTimeEstimate(
        origin_place_id=origin,
        destination_place_id=destination,
        service_date=service_date,
        status="known",
        duration_minutes=15,
        evidence_ids=[f"route-{origin}-{destination}-{service_date}"],
    )


def test_repair_graph_skips_repair_for_valid_itinerary() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[activity("safe", 1)])],
        estimated_total_cost=10,
    )
    graph = build_itinerary_repair_graph()

    result = graph.invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=1),
            "context": PlanningValidationContext(fail_closed_on_missing_availability=False),
            "candidates": [],
        }
    )

    assert result["status"] == "completed"
    assert result["repair_attempts"] == 0
    assert [item.node for item in result["trajectory"]] == ["initialize", "validate"]


def test_repair_graph_recomputes_false_total_without_touching_days() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[activity("safe", 1)])],
        estimated_total_cost=1,
    )
    graph = build_itinerary_repair_graph()

    result = graph.invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=1),
            "context": PlanningValidationContext(fail_closed_on_missing_availability=False),
        }
    )

    assert result["status"] == "completed"
    assert result["itinerary"].estimated_total_cost == 10
    assert result["modified_days"] == []
    assert result["repair_attempts"] == 1


def test_repair_graph_replans_only_affected_day_and_preserves_safe_day() -> None:
    first_date = BASE.date()
    second_date = (BASE + timedelta(days=1)).date()
    safe_day = day_plan(2, [activity("safe", 2)])
    safe_snapshot = safe_day.model_dump(mode="json")
    itinerary = Itinerary(
        days=[day_plan(1, [activity("closed", 1)]), safe_day],
        estimated_total_cost=20,
    )
    context = PlanningValidationContext(
        availability=[
            availability("closed", first_date, "closed"),
            availability("alternative", first_date),
            availability("safe", second_date),
        ],
        travel_times=[
            travel("hotel", "closed", first_date),
            travel("closed", "hotel", first_date),
            travel("hotel", "alternative", first_date),
            travel("alternative", "hotel", first_date),
            travel("hotel", "safe", second_date),
            travel("safe", "hotel", second_date),
        ],
        minimum_transfer_buffer_minutes=15,
    )
    candidates = [
        PlaceCandidate(
            place_id="closed",
            name="closed",
            duration_minutes=60,
            estimated_cost=10,
            evidence_ids=["doc-closed"],
            booking_status="not_required",
        ),
        PlaceCandidate(
            place_id="alternative",
            name="alternative",
            duration_minutes=60,
            estimated_cost=15,
            relevance_score=0.8,
            evidence_ids=["doc-alternative"],
            booking_status="not_required",
        ),
        PlaceCandidate(
            place_id="safe",
            name="safe",
            duration_minutes=60,
            estimated_cost=10,
            evidence_ids=["doc-safe"],
            booking_status="not_required",
        ),
    ]

    result = build_itinerary_repair_graph().invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=2, pace="relaxed"),
            "context": context,
            "candidates": candidates,
        }
    )

    assert result["status"] == "completed"
    assert result["modified_days"] == [1]
    assert [item.place_id for item in result["itinerary"].days[0].activities] == ["alternative"]
    assert result["itinerary"].days[1].model_dump(mode="json") == safe_snapshot


def test_budget_repair_removes_optional_activity_but_keeps_required() -> None:
    itinerary = Itinerary(
        days=[
            DayPlan(
                day=1,
                activities=[activity("required", 1, 60), activity("optional", 1, 50)],
            )
        ],
        estimated_total_cost=110,
    )

    result = build_itinerary_repair_graph().invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=1, budget=70, required_places=["required"]),
            "context": PlanningValidationContext(fail_closed_on_missing_availability=False),
        }
    )

    assert result["status"] == "completed"
    assert [item.place_id for item in result["itinerary"].days[0].activities] == ["required"]
    assert result["itinerary"].estimated_total_cost == 60


class ExplodingRepairer:
    def repair(self, request: Any) -> Any:
        del request
        raise RuntimeError("secret itinerary and provider payload")


def test_repairer_failure_uses_deterministic_fallback_without_leaking_error() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1, activities=[activity("safe", 1)])],
        estimated_total_cost=1,
    )

    result = build_itinerary_repair_graph(repairer=ExplodingRepairer()).invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=1),
            "context": PlanningValidationContext(fail_closed_on_missing_availability=False),
        }
    )

    assert result["status"] == "completed"
    assert result["degraded_components"] == ["itinerary_repairer"]
    assert result["dependency_errors"] == [
        {"component": "itinerary_repairer", "error_type": "RuntimeError"}
    ]
    assert "secret" not in str(result)


def test_impossible_required_place_stops_after_bounded_repairs() -> None:
    service_date = BASE.date()
    itinerary = Itinerary(days=[day_plan(1, [])], estimated_total_cost=0)
    candidate = PlaceCandidate(
        place_id="required",
        name="required",
        duration_minutes=60,
        estimated_cost=0,
        evidence_ids=["doc-required"],
    )

    result = build_itinerary_repair_graph(max_repair_attempts=2).invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=1, required_places=["required"]),
            "context": PlanningValidationContext(
                availability=[availability("required", service_date)]
            ),
            "candidates": [candidate],
        }
    )

    assert result["status"] == "failed"
    assert result["repair_attempts"] == 2
    assert {item.code for item in result["violations"]} == {"REQUIRED_PLACE_MISSING"}
    assert result["failure_reason"] == ("Itinerary remains invalid after bounded local repair.")
    assert [item.node for item in result["trajectory"]].count("repair") == 2


def test_repair_graph_rejects_nonpositive_retry_budget() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        build_itinerary_repair_graph(max_repair_attempts=0)


def test_nonrepairable_day_numbering_fails_without_wasting_retry_budget() -> None:
    itinerary = Itinerary(
        days=[DayPlan(day=1), DayPlan(day=1)],
        estimated_total_cost=0,
    )

    result = build_itinerary_repair_graph().invoke(
        {
            "itinerary": itinerary,
            "constraints": TravelConstraints(days=2),
            "context": PlanningValidationContext(fail_closed_on_missing_availability=False),
        }
    )

    assert result["status"] == "failed"
    assert result["repair_attempts"] == 0
    assert result["failure_reason"] == ("No safe local repair strategy exists for the violations.")
